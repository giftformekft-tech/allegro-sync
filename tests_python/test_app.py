from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from allegro_app.config import AppConfig
from allegro_app.database import Database
from allegro_app.importer import build_title, parse_csv
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


if __name__ == "__main__":
    unittest.main()
