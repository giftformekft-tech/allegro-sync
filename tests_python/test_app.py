from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from allegro_app.config import AppConfig
from allegro_app.database import Database
from allegro_app.importer import build_title, parse_csv
from allegro_app.invoices import InvoiceError, InvoiceService, build_invoice_xml
from allegro_app.offers import (
    OfferService,
    build_offer_payload,
    parameter_is_required,
    serialize_parameter,
    suggested_parameter_source,
    suggested_parameter_value,
)
from allegro_app.server import Application, AppServer
from allegro_app.temu import TemuClient, sign_payload


SAMPLE = """sku;parent_sku;name;description;type;type_label;color;size;price_huf;stock;image_url;length_cm;width_cm
TEST-POLO-S;TEST;Vidám nyári minta;<p>Pamut póló.</p>;polo;Póló;Fekete;S;5990;20;https://example.com/a.webp;70;50
HIBAS;TEST;A;;polo;Póló;Kék;M;0;0;rossz-url;;
"""


def sample_order() -> dict:
    return {
        "id": "ffc396b0-9584-11e8-8d53-07c966f77738",
        "status": "READY_FOR_PROCESSING",
        "updatedAt": "2026-07-30T10:00:00Z",
        "buyer": {
            "email": "buyer+order@allegromail.com",
            "firstName": "Minta",
            "lastName": "Vevő",
            "login": "mintavevo",
        },
        "payment": {"type": "ONLINE", "finishedAt": "2026-07-30T09:59:00Z"},
        "invoice": {
            "required": True,
            "address": {
                "street": "Fő utca 1.", "city": "Budapest", "zipCode": "1011", "countryCode": "HU",
                "company": {"name": "Minta Kft.", "taxId": "12345678-2-41"},
            },
        },
        "delivery": {
            "address": {
                "firstName": "Minta", "lastName": "Vevő", "street": "Fő utca 1.",
                "city": "Budapest", "zipCode": "1011", "countryCode": "HU",
            },
            "cost": {"amount": "990.00", "currency": "HUF"},
        },
        "lineItems": [{
            "offer": {"name": "Pamut póló"}, "quantity": 2,
            "price": {"amount": "5000.00", "currency": "HUF"},
        }],
        "summary": {"totalToPay": {"amount": "10990.00", "currency": "HUF"}},
    }


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
        self.assertEqual("70", rows[0]["length_cm"])
        self.assertEqual("50", rows[0]["width_cm"])
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
            self.assertEqual("70", db.list_products()[0]["length_cm"])
            self.assertEqual("50", db.list_products()[0]["width_cm"])

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
            "length_cm": "72",
            "width_cm": "53",
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

    def build(self, selections: dict, **overrides: object) -> dict:
        options = {
            "shipping_rate_id": "rate-1",
            "responsible_producer_id": "producer-1",
            "safety_information": "Rendeltetésszerű használatra. Nyílt lángtól távol tartandó.",
        }
        options.update(overrides)
        return build_offer_payload(self.product, self.category, selections, **options)

    def test_builds_inactive_huf_offer(self) -> None:
        payload = self.build({"brand": "brand_forme", "condition": "new"})
        self.assertEqual("INACTIVE", payload["publication"]["status"])
        self.assertEqual("HUF", payload["sellingMode"]["price"]["currency"])
        self.assertEqual("CICA-POLO-FEKETE-M", payload["external"]["id"])
        self.assertEqual([{"id": "brand", "valuesIds": ["brand_forme"]}], payload["productSet"][0]["product"]["parameters"])
        self.assertEqual([{"id": "condition", "valuesIds": ["new"]}], payload["parameters"])
        self.assertEqual("rate-1", payload["delivery"]["shippingRates"]["id"])
        self.assertEqual("PT24H", payload["delivery"]["handlingTime"])
        self.assertEqual("producer-1", payload["productSet"][0]["responsibleProducer"]["id"])
        self.assertEqual("TEXT", payload["productSet"][0]["safetyInformation"]["type"])

    def test_missing_required_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Hiányzó kötelező"):
            self.build({"brand": "brand_forme"})

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
            self.build({"brand": "brand_forme", "condition": "new"})

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
        payload = self.build(selections)
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
            self.build(selections)

    def test_dictionary_suggestion_matches_imported_value(self) -> None:
        parameter = self.category["parameters"][0]
        self.assertEqual("brand_forme", suggested_parameter_value(parameter, self.product))
        self.assertEqual("brand", suggested_parameter_source(parameter))
        self.assertIsNone(suggested_parameter_source({"name": "EAN (GTIN)"}))

    def test_measurement_parameters_use_imported_variant_values(self) -> None:
        adult_length = {"id": "201033", "name": "Teljes hosszúság"}
        adult_width = {"id": "201041", "name": "Szélesség hónalj alatt"}
        child_length = {"id": "202517", "name": "Teljes hosszúság"}
        self.assertEqual("length_cm", suggested_parameter_source(adult_length))
        self.assertEqual("72", suggested_parameter_value(adult_length, self.product))
        self.assertEqual("width_cm", suggested_parameter_source(adult_width))
        self.assertEqual("53", suggested_parameter_value(adult_width, self.product))
        self.assertEqual("length_cm", suggested_parameter_source(child_length))

    def test_measurements_are_sent_as_product_parameters(self) -> None:
        for parameter_id, name in (
            ("201033", "Teljes hosszúság"),
            ("201041", "Szélesség hónalj alatt"),
        ):
            self.category["parameters"].append({
                "id": parameter_id,
                "name": name,
                "type": "float",
                "required": False,
                "required_for_product": False,
                "describes_product": True,
                "is_gtin": False,
            })
        payload = self.build({
            "brand": "brand_forme",
            "condition": "new",
            "201033": "72",
            "201041": "53",
        })
        parameters = payload["productSet"][0]["product"]["parameters"]
        self.assertIn({"id": "201033", "values": ["72"]}, parameters)
        self.assertIn({"id": "201041", "values": ["53"]}, parameters)

    def test_tshirt_pattern_and_front_print_defaults(self) -> None:
        adult_pattern = {
            "id": "3766",
            "name": "Fő minta",
            "type": "dictionary",
            "dictionary": [{"id": "3766_218065", "value": "mintás (nyomatos)"}],
        }
        child_pattern = {
            "id": "202497",
            "name": "Fő minta",
            "type": "dictionary",
            "dictionary": [{"id": "202497_680829", "value": "nyomott mintás"}],
        }
        print_area = {
            "id": "249926",
            "name": "Nyomtatási terület",
            "type": "dictionary",
            "dictionary": [{"id": "249926_1783211", "value": "elülső"}],
        }
        self.assertEqual("allegro_default", suggested_parameter_source(adult_pattern))
        self.assertEqual("3766_218065", suggested_parameter_value(adult_pattern, self.product))
        self.assertEqual("202497_680829", suggested_parameter_value(child_pattern, self.product))
        self.assertEqual("249926_1783211", suggested_parameter_value(print_area, self.product))

    def test_parameter_serialization(self) -> None:
        self.assertEqual(
            {"id": "brand", "valuesIds": ["brand_forme"]},
            serialize_parameter(self.category["parameters"][0], "brand_forme"),
        )

    def test_uses_marketplace_currency_language_and_manual_price(self) -> None:
        payload = self.build(
            {"brand": "brand_forme", "condition": "new"},
            currency="PLN",
            language="pl-PL",
            price_amount="59,90",
        )
        self.assertEqual({"amount": "59.90", "currency": "PLN"}, payload["sellingMode"]["price"])
        self.assertEqual("pl-PL", payload["language"])

    def test_invalid_price_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "nem érvényes"):
            self.build(
                {"brand": "brand_forme", "condition": "new"},
                price_amount="nem-ár",
            )

    def test_template_can_override_stock(self) -> None:
        payload = self.build(
            {"brand": "brand_forme", "condition": "new"},
            stock_available="7",
        )
        self.assertEqual(7, payload["stock"]["available"])

    def test_negative_template_stock_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "nem lehet negatív"):
            self.build(
                {"brand": "brand_forme", "condition": "new"},
                stock_available="-1",
            )

    def test_missing_delivery_and_gpsr_are_rejected(self) -> None:
        selections = {"brand": "brand_forme", "condition": "new"}
        with self.assertRaisesRegex(ValueError, "szállítási árlistát"):
            build_offer_payload(
                self.product, self.category, selections,
                responsible_producer_id="producer-1", safety_information="Biztonsági szöveg.",
            )
        with self.assertRaisesRegex(ValueError, "GPSR"):
            self.build(selections, responsible_producer_id="")
        with self.assertRaisesRegex(ValueError, "1–5000"):
            self.build(selections, safety_information="")

    def test_preorder_adds_future_shipment_date(self) -> None:
        payload = self.build(
            {"brand": "brand_forme", "condition": "new"},
            shipment_date="2099-05-01T12:00:00Z",
            responsible_person_id="person-1",
        )
        self.assertEqual("2099-05-01T12:00:00Z", payload["delivery"]["shipmentDate"])
        self.assertEqual("person-1", payload["productSet"][0]["responsiblePerson"]["id"])


class MarketplaceTests(unittest.TestCase):
    class Client:
        def request(self, method: str, path: str, **_: object) -> dict:
            if path == "/me":
                return {"body": {"baseMarketplace": {"id": "allegro-hu"}}}
            if path == "/sale/shipping-rates":
                return {"body": {"shippingRates": [{
                    "id": "rate-1", "name": "futár", "marketplaces": [{"id": "allegro-hu"}],
                }]}}
            if path == "/sale/responsible-producers":
                return {"body": {"responsibleProducers": [{
                    "id": "producer-1", "name": "Forme",
                    "producerData": {"address": {"countryCode": "HU"}},
                }]}}
            if path == "/sale/responsible-persons":
                return {"body": {"responsiblePersons": [{"id": "person-1", "name": "EU felelős"}]}}
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

    def test_reads_shipping_and_gpsr_account_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = OfferService(
                AppConfig(root, {"ALLEGRO_LANGUAGE": "hu-HU"}),
                Database(root / "state.sqlite"), self.Client(),
            )
            options = service.upload_options()
            self.assertEqual("futár", options["shipping_rates"][0]["name"])
            self.assertEqual("Forme", options["responsible_producers"][0]["name"])
            service._validate_account_choices("allegro-hu", "rate-1", "producer-1", "")


class InvoiceTests(unittest.TestCase):
    def test_invoice_xml_uses_masked_email_and_fallback_flag(self) -> None:
        xml = build_invoice_xml(sample_order(), "agent-key", "ALLEGRO", True)
        root = ET.fromstring(xml)
        namespace = {"s": "http://www.szamlazz.hu/xmlszamla"}
        self.assertEqual(
            "buyer+order@allegromail.com", root.findtext("s:vevo/s:email", namespaces=namespace)
        )
        self.assertEqual("true", root.findtext("s:vevo/s:sendEmail", namespaces=namespace))
        self.assertEqual("Minta Kft.", root.findtext("s:vevo/s:nev", namespaces=namespace))
        self.assertEqual("12345678-2-41", root.findtext("s:vevo/s:adoszam", namespaces=namespace))
        self.assertEqual("ALLEGRO", root.findtext("s:fejlec/s:szamlaszamElotag", namespaces=namespace))
        self.assertEqual(2, len(root.findall("s:tetelek/s:tetel", namespaces=namespace)))

    def test_invoice_rejects_mismatching_order_total(self) -> None:
        order = sample_order()
        order["summary"]["totalToPay"]["amount"] = "9999.00"
        with self.assertRaisesRegex(InvoiceError, "nem egyezik"):
            build_invoice_xml(order, "agent-key")

    def test_invoice_is_uploaded_to_allegro_and_not_duplicated(self) -> None:
        class Allegro:
            def __init__(self) -> None:
                self.posts = 0
                self.uploads = 0

            def request(self, method: str, path: str, **_: object) -> dict:
                if method == "GET":
                    return {"body": sample_order()}
                self.posts += 1
                return {"body": {"id": "invoice-on-allegro"}}

            def upload_pdf(self, path: str, content: bytes) -> dict:
                self.uploads += 1
                self.asserted_path = path
                if not content.startswith(b"%PDF"):
                    raise AssertionError("not a PDF")
                return {"status": 200}

        class Szamlazz:
            calls = 0

            def create_invoice(self, order: dict) -> tuple[str, bytes, str]:
                self.calls += 1
                return "ALLEGRO-2026-1", b"%PDF-test", order["buyer"]["email"]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(root, {
                "INVOICE_DRIVER": "szamlazz", "SZAMLAZZ_AGENT_KEY": "key",
                "SZAMLAZZ_SEND_EMAIL": "true", "ALLEGRO_ENV": "sandbox",
            })
            database = Database(root / "state.sqlite")
            allegro = Allegro()
            service = InvoiceService(config, database, allegro)  # type: ignore[arg-type]
            service.szamlazz = Szamlazz()  # type: ignore[assignment]
            result = service.create_and_upload(sample_order()["id"])
            self.assertEqual("ALLEGRO-2026-1", result["invoice_number"])
            self.assertEqual(1, allegro.posts)
            self.assertEqual(1, allegro.uploads)
            self.assertEqual("uploaded", database.get_order_invoice(sample_order()["id"])["status"])
            with self.assertRaisesRegex(InvoiceError, "már feltöltöttük"):
                service.create_and_upload(sample_order()["id"])

    def test_failed_allegro_upload_reuses_existing_pdf(self) -> None:
        class Allegro:
            fail = True
            posts = 0

            def request(self, method: str, path: str, **_: object) -> dict:
                if method == "GET":
                    return {"body": sample_order()}
                self.posts += 1
                return {"body": {"id": "invoice-on-allegro"}}

            def upload_pdf(self, path: str, content: bytes) -> dict:
                if self.fail:
                    raise RuntimeError("temporary upload error")
                return {"status": 200}

        class Szamlazz:
            calls = 0

            def create_invoice(self, order: dict) -> tuple[str, bytes, str]:
                self.calls += 1
                return "ALLEGRO-2026-2", b"%PDF-test", order["buyer"]["email"]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = InvoiceService(
                AppConfig(root, {
                    "INVOICE_DRIVER": "szamlazz", "SZAMLAZZ_AGENT_KEY": "key",
                    "ALLEGRO_ENV": "sandbox",
                }),
                Database(root / "state.sqlite"),
                Allegro(),  # type: ignore[arg-type]
            )
            fake = Szamlazz()
            service.szamlazz = fake  # type: ignore[assignment]
            with self.assertRaisesRegex(RuntimeError, "temporary"):
                service.create_and_upload(sample_order()["id"])
            service.allegro.fail = False  # type: ignore[attr-defined]
            service.create_and_upload(sample_order()["id"])
            self.assertEqual(1, fake.calls)
            self.assertEqual(1, service.allegro.posts)  # type: ignore[attr-defined]


class TemuTests(unittest.TestCase):
    def test_sign_payload_has_stable_uppercase_signature(self) -> None:
        payload = {
            "type": "bg.open.accesstoken.info.get",
            "app_key": "app-123",
            "access_token": "token-456",
            "timestamp": "1785398400",
            "data_type": "JSON",
        }
        self.assertEqual(
            "7B09022E3227829FD2C714DAD7FBDD2D",
            sign_payload(payload, "secret-789"),
        )

    def test_connection_check_sends_signed_open_platform_request(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'{"success":true,"requestId":"request-1"}'

        captured: list[Request] = []

        def open_request(request: Request, timeout: int):
            self.assertEqual(30, timeout)
            captured.append(request)
            return Response()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "\n".join((
                    "TEMU_ENDPOINT=https://openapi-b-eu.temu.com/openapi/router",
                    "TEMU_APP_KEY=app-123",
                    "TEMU_APP_SECRET=secret-789",
                    "TEMU_ACCESS_TOKEN=token-456",
                )),
                encoding="utf-8",
            )
            config = AppConfig.load(root)
            database = Database(root / "state.sqlite")
            client = TemuClient(config, database, clock=lambda: 1785398400)
            with patch("allegro_app.temu.urlopen", side_effect=open_request):
                result = client.check_connection()

        self.assertTrue(result["ok"])
        self.assertEqual("request-1", result["request_id"])
        self.assertEqual(
            "https://openapi-b-eu.temu.com/openapi/router", captured[0].full_url
        )
        body = json.loads(captured[0].data)
        self.assertEqual("bg.open.accesstoken.info.get", body["type"])
        self.assertEqual(1785398400, body["timestamp"])
        self.assertEqual("7B09022E3227829FD2C714DAD7FBDD2D", body["sign"])

    def test_temu_success_code_is_not_treated_as_error(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'{"success":true,"errorCode":1000000,"result":{}}'

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "TEMU_APP_KEY=a\nTEMU_APP_SECRET=b\nTEMU_ACCESS_TOKEN=c\n",
                encoding="utf-8",
            )
            client = TemuClient(AppConfig.load(root), Database(root / "state.sqlite"))
            with patch("allegro_app.temu.urlopen", return_value=Response()):
                self.assertTrue(client.request("example")["success"])

    def test_category_and_template_responses_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "TEMU_APP_KEY=a\nTEMU_APP_SECRET=b\nTEMU_ACCESS_TOKEN=c\n",
                encoding="utf-8",
            )
            client = TemuClient(AppConfig.load(root), Database(root / "state.sqlite"))
            category_response = {
                "result": {"goodsCatsList": [
                    {"catId": 20, "parentId": 10, "catName": "T-Shirts", "level": 3, "leaf": True},
                    {"catId": 19, "parentId": 10, "catName": "Polos", "level": 3, "leaf": True},
                ]}
            }
            template_response = {"result": {
                "inputMaxSpecNum": 0,
                "singleSpecValueNum": 500,
                "templateInfo": {
                    "goodsSpecProperties": [{
                        "pid": 13, "refPid": 63, "templatePid": 259449,
                        "parentSpecId": 1001, "name": "Color", "required": True,
                        "isSale": True, "mainSale": True, "controlType": 1,
                        "values": [{"vid": 32560, "specId": 22028, "value": "Black",
                                    "group": {"name": "Black Color Family"}}],
                    }],
                    "goodsProperties": [{
                        "pid": 1, "refPid": 1920, "templatePid": 988850,
                        "name": "Material", "required": True, "isSale": False,
                        "controlType": 1, "chooseMaxNum": 1,
                        "showType": 0,
                        "values": [{"vid": 56, "value": "Cotton"}],
                    }],
                },
            }}
            with patch.object(client, "request", return_value=category_response):
                categories = client.categories(10)
            self.assertEqual(["Polos", "T-Shirts"], [row["name"] for row in categories["categories"]])
            with patch.object(client, "request", return_value=template_response):
                template = client.category_template(20)
            self.assertEqual("Color", template["sales_properties"][0]["name"])
            self.assertEqual("22028", template["sales_properties"][0]["values"][0]["spec_id"])
            self.assertEqual("Material", template["properties"][0]["name"])
            self.assertEqual(0, template["properties"][0]["show_type"])


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
                'ALLEGRO_ENV="sandbox"\nALLEGRO_CLIENT_SECRET="top-secret"\n'
                'TEMU_APP_KEY="public-app"\nTEMU_APP_SECRET="temu-secret"\n'
                'TEMU_ACCESS_TOKEN="temu-token"\n',
                encoding="utf-8",
            )
            config = AppConfig.load(root)
            public = config.public_values()
            self.assertTrue(public["client_secret_set"])
            self.assertTrue(public["temu_app_secret_set"])
            self.assertTrue(public["temu_access_token_set"])
            self.assertNotIn("top-secret", public.values())
            self.assertNotIn("temu-secret", public.values())
            self.assertNotIn("temu-token", public.values())


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
