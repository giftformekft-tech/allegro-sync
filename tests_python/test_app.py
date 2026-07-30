from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from allegro_app.config import AppConfig
from allegro_app.database import Database
from allegro_app.importer import build_title, parse_csv
from allegro_app.offers import (
    OfferService,
    build_offer_payload,
    parameter_is_required,
    serialize_parameter,
    suggested_parameter_source,
    suggested_parameter_value,
)
from allegro_app.server import Application, AppServer


SAMPLE = """sku;parent_sku;name;description;type;type_label;color;size;price_huf;stock;image_url
TEST-POLO-S;TEST;Vidám nyári minta;<p>Pamut póló.</p>;polo;Póló;Fekete;S;5990;20;https://example.com/a.webp
HIBAS;TEST;A;;polo;Póló;Kék;M;0;0;rossz-url
"""


class TitleBuilderTests(unittest.TestCase):
    def test_builds_valid_title_and_removes_redundant_type(self) -> None:
        title, problem = build_title(["Vicces macskás póló", "Póló", "Fekete", "M"])
        self.assertEqual("Vicces macskás póló Fekete M", title)
        self.assertIsNone(problem)

    def test_truncates_on_word_boundary(self) -> None:
        title, problem = build_title(["nagyon " * 30, "Póló", "Fekete", "M"])
        self.assertLessEqual(len(title), 75)
        self.assertFalse(title.endswith("nag"))
        self.assertIsNone(problem)


class CsvTests(unittest.TestCase):
    def test_sample_has_one_valid_and_one_invalid_row(self) -> None:
        rows = parse_csv(SAMPLE)
        self.assertEqual(2, len(rows))
        self.assertEqual([], rows[0]["problems"])
        self.assertEqual(4, len(rows[1]["problems"]))

    def test_missing_required_column_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Hiányzó kötelező"):
            parse_csv("sku;name\nA;Teszt")

    def test_duplicate_sku_is_reported(self) -> None:
        duplicated = SAMPLE.splitlines()[0] + "\n" + SAMPLE.splitlines()[1] + "\n" + SAMPLE.splitlines()[1]
        rows = parse_csv(duplicated)
        self.assertIn("Ismétlődő SKU.", rows[1]["problems"])


class DatabaseTests(unittest.TestCase):
    def test_commit_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "state.sqlite")
            rows = parse_csv(SAMPLE)
            import_id = db.create_preview("sample.csv", rows)
            self.assertEqual(1, db.commit_import(import_id))
            self.assertEqual(1, db.commit_import(import_id))
            self.assertEqual(1, len(db.list_products()))

    def test_offer_template_can_be_saved_updated_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "state.sqlite")
            saved = db.save_offer_template(
                "Pamut póló",
                "123",
                "Férfi pólók",
                [
                    {"parameter_id": "condition", "mode": "fixed", "value": "new"},
                    {"parameter_id": "color", "mode": "product", "value": "ignored"},
                    {"parameter_id": "__stock__", "mode": "fixed", "value": "12"},
                ],
            )
            self.assertEqual("", saved["rules"][1]["value"])
            updated = db.save_offer_template(
                "Pamut póló", "456", "Női pólók", []
            )
            self.assertEqual(saved["id"], updated["id"])
            self.assertEqual("456", db.list_offer_templates()[0]["category_id"])
            db.delete_offer_template(saved["id"])
            self.assertEqual([], db.list_offer_templates())


class OfferPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.product = {
            "id": 1,
            "sku": "CICA-POLO-FEKETE-M",
            "title": "Vicces macskás minta Póló Fekete M",
            "description": "<p>Prémium pamut póló.</p>",
            "brand": "forme",
            "material": "100% pamut",
            "color": "Fekete",
            "size": "M",
            "price_huf": "5990",
            "stock": 25,
            "image_url": "https://example.com/polo.webp",
        }
        self.category = {
            "id": "123",
            "leaf": True,
            "product_creation_enabled": True,
            "offer_creation_enabled": True,
            "gtin_required": False,
            "parameters": [
                {
                    "id": "brand",
                    "name": "Marka",
                    "type": "dictionary",
                    "required": True,
                    "required_for_product": True,
                    "describes_product": True,
                    "is_gtin": False,
                    "dictionary": [{"id": "brand_forme", "value": "forme"}],
                },
                {
                    "id": "condition",
                    "name": "Állapot",
                    "type": "dictionary",
                    "required": True,
                    "required_for_product": False,
                    "describes_product": False,
                    "is_gtin": False,
                    "dictionary": [{"id": "new", "value": "Új"}],
                },
            ],
        }

    def test_builds_inactive_huf_offer(self) -> None:
        payload = build_offer_payload(
            self.product, self.category, {"brand": "brand_forme", "condition": "new"}
        )
        self.assertEqual("INACTIVE", payload["publication"]["status"])
        self.assertEqual("HUF", payload["sellingMode"]["price"]["currency"])
        self.assertEqual("CICA-POLO-FEKETE-M", payload["external"]["id"])
        self.assertEqual([{"id": "brand", "valuesIds": ["brand_forme"]}], payload["productSet"][0]["product"]["parameters"])
        self.assertEqual([{"id": "condition", "valuesIds": ["new"]}], payload["parameters"])

    def test_missing_required_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Hiányzó kötelező"):
            build_offer_payload(self.product, self.category, {"brand": "brand_forme"})

    def test_gtin_category_is_rejected_without_gtin(self) -> None:
        self.category["parameters"].append({
            "id": "225693",
            "name": "EAN (GTIN)",
            "type": "string",
            "required": True,
            "required_for_product": True,
            "describes_product": True,
            "is_gtin": True,
        })
        with self.assertRaisesRegex(ValueError, "GTIN"):
            build_offer_payload(self.product, self.category, {"brand": "brand_forme", "condition": "new"})

    def test_conditional_gtin_is_optional_for_unlisted_brand(self) -> None:
        gtin = {
            "id": "225693",
            "name": "EAN (GTIN)",
            "type": "string",
            "required": True,
            "required_for_product": True,
            "describes_product": True,
            "is_gtin": True,
            "required_if": {
                "parametersWithValue": [
                    {"id": "condition", "oneOfValueIds": ["new"]},
                    {"id": "brand", "oneOfValueIds": ["protected_brand"]},
                ],
                "parametersWithoutValue": [],
            },
        }
        self.category["parameters"].append(gtin)
        selections = {"brand": "brand_forme", "condition": "new"}
        self.assertFalse(parameter_is_required(gtin, selections))
        payload = build_offer_payload(self.product, self.category, selections)
        self.assertNotIn("225693", {item["id"] for item in payload["productSet"][0]["product"]["parameters"]})

    def test_conditional_gtin_is_required_for_listed_brand(self) -> None:
        gtin = {
            "id": "225693",
            "name": "EAN (GTIN)",
            "type": "string",
            "required": True,
            "required_for_product": True,
            "describes_product": True,
            "is_gtin": True,
            "required_if": {
                "parametersWithValue": [
                    {"id": "condition", "oneOfValueIds": ["new"]},
                    {"id": "brand", "oneOfValueIds": ["protected_brand"]},
                ]
            },
        }
        self.category["parameters"].append(gtin)
        selections = {"brand": "protected_brand", "condition": "new"}
        self.assertTrue(parameter_is_required(gtin, selections))
        with self.assertRaisesRegex(ValueError, "GTIN"):
            build_offer_payload(self.product, self.category, selections)

    def test_dictionary_suggestion_matches_imported_value(self) -> None:
        parameter = self.category["parameters"][0]
        self.assertEqual("brand_forme", suggested_parameter_value(parameter, self.product))
        self.assertEqual("brand", suggested_parameter_source(parameter))
        self.assertIsNone(suggested_parameter_source({"name": "EAN (GTIN)"}))

    def test_parameter_serialization(self) -> None:
        self.assertEqual(
            {"id": "brand", "valuesIds": ["brand_forme"]},
            serialize_parameter(self.category["parameters"][0], "brand_forme"),
        )

    def test_uses_marketplace_currency_language_and_manual_price(self) -> None:
        payload = build_offer_payload(
            self.product,
            self.category,
            {"brand": "brand_forme", "condition": "new"},
            currency="PLN",
            language="pl-PL",
            price_amount="59,90",
        )
        self.assertEqual({"amount": "59.90", "currency": "PLN"}, payload["sellingMode"]["price"])
        self.assertEqual("pl-PL", payload["language"])

    def test_invalid_price_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "nem érvényes"):
            build_offer_payload(
                self.product,
                self.category,
                {"brand": "brand_forme", "condition": "new"},
                price_amount="nem-ár",
            )

    def test_template_can_override_stock(self) -> None:
        payload = build_offer_payload(
            self.product,
            self.category,
            {"brand": "brand_forme", "condition": "new"},
            stock_available="7",
        )
        self.assertEqual(7, payload["stock"]["available"])

    def test_negative_template_stock_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "nem lehet negatív"):
            build_offer_payload(
                self.product,
                self.category,
                {"brand": "brand_forme", "condition": "new"},
                stock_available="-1",
            )


class MarketplaceTests(unittest.TestCase):
    class Client:
        def request(self, method: str, path: str, **_: object) -> dict:
            if path == "/me":
                return {"body": {"baseMarketplace": {"id": "allegro-hu"}}}
            return {
                "body": {
                    "marketplaces": [{
                        "id": "allegro-hu",
                        "currencies": {"base": {"code": "HUF"}},
                        "languages": {"offerCreation": [{"code": "hu-HU"}, {"code": "en-US"}]},
                    }]
                }
            }

    def test_reads_base_marketplace_currency_and_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(root, {"ALLEGRO_LANGUAGE": "hu-HU"})
            service = OfferService(config, Database(root / "state.sqlite"), self.Client())
            self.assertEqual(
                {"id": "allegro-hu", "currency": "HUF", "language": "hu-HU", "languages": ["hu-HU", "en-US"]},
                service.marketplace(),
            )


class WebAssetTests(unittest.TestCase):
    def test_javascript_element_ids_exist_and_are_unique(self) -> None:
        root = Path(__file__).resolve().parent.parent
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (root / "web" / "app.js").read_text(encoding="utf-8")
        html_ids = re.findall(r'\bid="([^"]+)"', html)
        referenced_ids = set(re.findall(r"\$\('#([^']+)'\)", javascript))
        self.assertEqual(len(html_ids), len(set(html_ids)))
        self.assertEqual(set(), referenced_ids - set(html_ids))

    def test_test_upload_button_is_not_disabled(self) -> None:
        root = Path(__file__).resolve().parent.parent
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        button = re.search(r'<button[^>]+id="createOffer"[^>]*>', html)
        self.assertIsNotNone(button)
        self.assertNotIn("disabled", button.group(0))


class ConfigTests(unittest.TestCase):
    def test_secrets_are_not_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                'ALLEGRO_ENV="sandbox"\nALLEGRO_CLIENT_SECRET="top-secret"\n', encoding="utf-8"
            )
            config = AppConfig.load(root)
            public = config.public_values()
            self.assertTrue(public["client_secret_set"])
            self.assertNotIn("top-secret", public.values())


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / ".env.example").write_text("ALLEGRO_ENV=sandbox\n", encoding="utf-8")
        self.server = AppServer(("127.0.0.1", 0), Application(root))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read())

    def test_import_flow(self) -> None:
        health = self.request("/api/health")
        self.assertTrue(health["ok"])
        preview = self.request("/api/import/preview", {"filename": "sample.csv", "content": SAMPLE})
        self.assertEqual(1, preview["summary"]["valid"])
        committed = self.request("/api/import/commit", {"import_id": preview["import_id"]})
        self.assertEqual(1, committed["imported"])
        products = self.request("/api/products")
        self.assertEqual("TEST-POLO-S", products["products"][0]["sku"])

    def test_template_api_flow(self) -> None:
        created = self.request("/api/templates", {
            "name": "Alap póló",
            "category_id": "123",
            "category_name": "Pólók",
            "rules": [{"parameter_id": "__stock__", "mode": "fixed", "value": "10"}],
        })
        template_id = created["template"]["id"]
        self.assertEqual("10", self.request("/api/templates")["templates"][0]["rules"][0]["value"])
        request = Request(self.base + f"/api/templates/{template_id}", method="DELETE")
        with urlopen(request, timeout=3) as response:
            self.assertTrue(json.loads(response.read())["ok"])
        self.assertEqual([], self.request("/api/templates")["templates"])


if __name__ == "__main__":
    unittest.main()
