from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import threading
import urllib.parse
import webbrowser

from . import __version__
from .allegro import AllegroApiError, AllegroAuth, AllegroCatalog, AllegroClient, AllegroError
from .config import AppConfig
from .database import Database
from .importer import parse_csv
from .invoices import InvoiceError, InvoiceService
from .offers import OfferService, suggested_parameter_source, suggested_parameter_value
from .temu import TemuClient, TemuError
from .temu_products import TemuProductService
from .temu_invoices import TemuInvoiceService
from .express_one import ExpressOneError
from .temu_shipping import TemuShippingError, TemuShippingService


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"


class Application:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.config = AppConfig.load(root)
        self.database = Database(self.config.state_path)

    def reload_config(self) -> None:
        old_path = self.config.state_path
        self.config = AppConfig.load(self.root)
        if self.config.state_path != old_path:
            self.database = Database(self.config.state_path)

    @property
    def auth(self) -> AllegroAuth:
        return AllegroAuth(self.config, self.database)

    @property
    def client(self) -> AllegroClient:
        return AllegroClient(self.config, self.database)

    @property
    def catalog(self) -> AllegroCatalog:
        return AllegroCatalog(self.client)

    @property
    def offers(self) -> OfferService:
        return OfferService(self.config, self.database, self.client)

    @property
    def invoices(self) -> InvoiceService:
        return InvoiceService(self.config, self.database, self.client)

    @property
    def temu(self) -> TemuClient:
        return TemuClient(self.config, self.database)

    @property
    def temu_products(self) -> TemuProductService:
        return TemuProductService(self.database, self.temu)

    @property
    def temu_invoices(self) -> TemuInvoiceService:
        return TemuInvoiceService(self.config, self.database, self.temu)

    @property
    def temu_shipping(self) -> TemuShippingService:
        return TemuShippingService(self.config, self.database, self.temu)


class Handler(BaseHTTPRequestHandler):
    server_version = f"AllegroSync/{__version__}"

    @property
    def app(self) -> Application:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        if self.path != "/api/health":
            super().log_message(format, *args)

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 12_000_000:
                raise ValueError("A kérés túl nagy (maximum 12 MB).")
            data = json.loads(self.rfile.read(size).decode("utf-8")) if size else {}
            if not isinstance(data, dict):
                raise ValueError("A kérésnek JSON objektumnak kell lennie.")
            return data
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Érvénytelen JSON kérés.") from exc

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._json({"ok": True, "version": __version__})
            elif parsed.path == "/api/dashboard":
                data = self.app.database.dashboard()
                config_problems = self.app.config.validation()
                data["connection"] = {
                    "configured": not config_problems,
                    "problems": config_problems,
                    "environment": self.app.config.environment,
                    "user_connected": self.app.database.has_user_token(),
                }
                self._json(data)
            elif parsed.path == "/api/products":
                query = urllib.parse.parse_qs(parsed.query)
                self._json({"products": self.app.database.list_products(
                    query.get("q", [""])[0], query.get("marketplace", [""])[0]
                )})
            elif parsed.path == "/api/templates":
                self._json({"templates": self.app.database.list_offer_templates()})
            elif parsed.path == "/api/categories/suggest":
                query = urllib.parse.parse_qs(parsed.query)
                self._json({"categories": self.app.catalog.suggest(query.get("q", [""])[0])})
            elif parsed.path.startswith("/api/categories/"):
                category_id = urllib.parse.unquote(parsed.path.removeprefix("/api/categories/"))
                category = self.app.catalog.inspect(category_id)
                query = urllib.parse.parse_qs(parsed.query)
                product_id = int(query.get("product_id", ["0"])[0] or 0)
                product = self.app.database.get_product(product_id) if product_id else None
                for parameter in category["parameters"]:
                    parameter["suggested_source"] = suggested_parameter_source(parameter)
                    if product:
                        parameter["suggested_value"] = suggested_parameter_value(parameter, product)
                self._json({"category": category})
            elif parsed.path == "/api/settings":
                self._json(self.app.config.public_values())
            elif parsed.path == "/api/temu/categories":
                query = urllib.parse.parse_qs(parsed.query)
                parent_id = int(query.get("parent_id", ["0"])[0] or 0)
                self._json(self.app.temu.categories(parent_id))
            elif parsed.path.startswith("/api/temu/categories/") and parsed.path.endswith("/template"):
                category_id = int(
                    parsed.path.removeprefix("/api/temu/categories/")
                    .removesuffix("/template").strip("/")
                )
                self._json({"template": self.app.temu.category_template(category_id)})
            elif parsed.path == "/api/temu/uploads":
                self._json({"uploads": self.app.database.list_temu_uploads()})
            elif parsed.path == "/api/temu/orders":
                self._json({"orders": self.app.temu_invoices.list_orders()})
            elif parsed.path.startswith("/api/temu/orders/") and parsed.path.endswith("/invoice-preview"):
                order_id = urllib.parse.unquote(
                    parsed.path.removeprefix("/api/temu/orders/").removesuffix("/invoice-preview").strip("/")
                )
                self._json(self.app.temu_invoices.preview(order_id))
            elif parsed.path.startswith("/api/temu/invoice-files/") and parsed.path.endswith(".pdf"):
                token = urllib.parse.unquote(
                    parsed.path.removeprefix("/api/temu/invoice-files/").removesuffix(".pdf")
                )
                self._temu_invoice_file(token)
            elif parsed.path.startswith("/api/temu/orders/") and parsed.path.endswith("/shipment-preview"):
                order_id = urllib.parse.unquote(
                    parsed.path.removeprefix("/api/temu/orders/").removesuffix("/shipment-preview").strip("/")
                )
                query = urllib.parse.parse_qs(parsed.query)
                self._json(self.app.temu_shipping.preview(order_id, query.get("weight_kg", [None])[0]))
            elif parsed.path.startswith("/api/temu/orders/") and parsed.path.endswith("/label.pdf"):
                order_id = urllib.parse.unquote(
                    parsed.path.removeprefix("/api/temu/orders/").removesuffix("/label.pdf").strip("/")
                )
                self._temu_label_file(order_id)
            elif parsed.path == "/api/marketplace":
                self._json({"marketplace": self.app.offers.marketplace()})
            elif parsed.path == "/api/offer-options":
                self._json(self.app.offers.upload_options())
            elif parsed.path == "/api/orders":
                self._json({"orders": self.app.invoices.list_orders()})
            elif parsed.path.startswith("/api/"):
                self._json({"error": "Ismeretlen API végpont."}, HTTPStatus.NOT_FOUND)
            else:
                self._static(parsed.path)
        except AllegroApiError as exc:
            self._json({"error": str(exc), "details": exc.details}, exc.status)
        except (ValueError, AllegroError, InvoiceError, TemuError, ExpressOneError, TemuShippingError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": f"Váratlan hiba: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            body = self._body()
            if self.path == "/api/import/preview":
                content = str(body.get("content", ""))
                if len(content.encode("utf-8")) > 10_000_000:
                    raise ValueError("A CSV legfeljebb 10 MB lehet.")
                rows = parse_csv(content)
                import_id = self.app.database.create_preview(str(body.get("filename", "import.csv")), rows)
                self._json({
                    "import_id": import_id,
                    "rows": rows[:200],
                    "summary": {
                        "total": len(rows),
                        "valid": sum(1 for row in rows if not row["problems"]),
                        "invalid": sum(1 for row in rows if row["problems"]),
                        "errors": sum(len(row["problems"]) for row in rows),
                    },
                })
            elif self.path == "/api/import/commit":
                count = self.app.database.commit_import(int(body.get("import_id", 0)))
                self._json({"ok": True, "imported": count})
            elif self.path == "/api/templates":
                rules = body.get("rules") if isinstance(body.get("rules"), list) else []
                template = self.app.database.save_offer_template(
                    str(body.get("name", "")),
                    str(body.get("category_id", "")),
                    str(body.get("category_name", "")),
                    rules,
                )
                self._json({"ok": True, "template": template}, HTTPStatus.CREATED)
            elif self.path == "/api/auth/check":
                self._json(self.app.auth.check_application())
            elif self.path == "/api/temu/check":
                self._json(self.app.temu.check_connection())
            elif self.path == "/api/express-one/check":
                self._json(self.app.temu_shipping.check_connection())
            elif self.path == "/api/temu/products/preview":
                product_ids = body.get("product_ids") if isinstance(body.get("product_ids"), list) else []
                options = body.get("options") if isinstance(body.get("options"), dict) else {}
                self._json(self.app.temu_products.preview([int(value) for value in product_ids], options))
            elif self.path == "/api/temu/products/create":
                product_ids = body.get("product_ids") if isinstance(body.get("product_ids"), list) else []
                options = body.get("options") if isinstance(body.get("options"), dict) else {}
                result = self.app.temu_products.create(
                    [int(value) for value in product_ids], options, str(body.get("confirmation", ""))
                )
                self._json(result, HTTPStatus.CREATED)
            elif self.path.startswith("/api/temu/uploads/") and self.path.endswith("/refresh"):
                upload_id = int(
                    self.path.removeprefix("/api/temu/uploads/").removesuffix("/refresh").strip("/")
                )
                self._json(self.app.temu_products.refresh_status(upload_id))
            elif self.path.startswith("/api/temu/orders/") and self.path.endswith("/invoices"):
                order_id = urllib.parse.unquote(
                    self.path.removeprefix("/api/temu/orders/").removesuffix("/invoices").strip("/")
                )
                self._json(self.app.temu_invoices.create_and_upload(order_id), HTTPStatus.CREATED)
            elif self.path.startswith("/api/temu/orders/") and self.path.endswith("/platform-address/approve"):
                order_id = urllib.parse.unquote(
                    self.path.removeprefix("/api/temu/orders/").removesuffix("/platform-address/approve").strip("/")
                )
                self._json(self.app.temu_invoices.approve_platform_address(order_id))
            elif self.path.startswith("/api/temu/orders/") and self.path.endswith("/shipment"):
                order_id = urllib.parse.unquote(
                    self.path.removeprefix("/api/temu/orders/").removesuffix("/shipment").strip("/")
                )
                self._json(self.app.temu_shipping.create(
                    order_id, body.get("weight_kg"), str(body.get("confirmation", ""))
                ), HTTPStatus.CREATED)
            elif self.path.startswith("/api/temu/orders/") and self.path.endswith("/tracking"):
                order_id = urllib.parse.unquote(
                    self.path.removeprefix("/api/temu/orders/").removesuffix("/tracking").strip("/")
                )
                self._json(self.app.temu_shipping.refresh_tracking(order_id))
            elif self.path == "/api/auth/device/start":
                self._json(self.app.auth.start_device_flow())
            elif self.path == "/api/auth/device/poll":
                self._json(self.app.auth.poll_device_flow(str(body.get("device_code", ""))))
            elif self.path == "/api/offers/preview":
                category = self.app.catalog.inspect(str(body.get("category_id", "")))
                selections = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
                preview = self.app.offers.preview(
                    int(body.get("product_id", 0)), category, selections,
                    str(body.get("price_amount", "")), str(body.get("stock_available", "")),
                    str(body.get("shipping_rate_id", "")), str(body.get("handling_time", "PT24H")),
                    str(body.get("shipment_date", "")), str(body.get("responsible_producer_id", "")),
                    str(body.get("responsible_person_id", "")), str(body.get("safety_information", "")),
                )
                self._json({**preview, "environment": self.app.config.environment})
            elif self.path == "/api/offers/create":
                category = self.app.catalog.inspect(str(body.get("category_id", "")))
                selections = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
                result = self.app.offers.create(
                    int(body.get("product_id", 0)), category, selections,
                    str(body.get("confirmation", "")), str(body.get("price_amount", "")),
                    str(body.get("stock_available", "")), str(body.get("shipping_rate_id", "")),
                    str(body.get("handling_time", "PT24H")), str(body.get("shipment_date", "")),
                    str(body.get("responsible_producer_id", "")),
                    str(body.get("responsible_person_id", "")), str(body.get("safety_information", "")),
                )
                self._json(result)
            elif self.path.startswith("/api/orders/") and self.path.endswith("/invoice"):
                order_id = urllib.parse.unquote(
                    self.path.removeprefix("/api/orders/").removesuffix("/invoice").strip("/")
                )
                self._json(self.app.invoices.create_and_upload(order_id))
            else:
                self._json({"error": "Ismeretlen API végpont."}, HTTPStatus.NOT_FOUND)
        except AllegroApiError as exc:
            self._json({"error": str(exc), "details": exc.details}, exc.status)
        except (ValueError, AllegroError, InvoiceError, TemuError, ExpressOneError, TemuShippingError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": f"Váratlan hiba: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            if not parsed.path.startswith("/api/templates/"):
                self._json({"error": "Ismeretlen API végpont."}, HTTPStatus.NOT_FOUND)
                return
            template_id = int(parsed.path.removeprefix("/api/templates/"))
            self.app.database.delete_offer_template(template_id)
            self._json({"ok": True})
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": f"Váratlan hiba: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_PUT(self) -> None:
        try:
            if self.path != "/api/settings":
                self._json({"error": "Ismeretlen API végpont."}, HTTPStatus.NOT_FOUND)
                return
            body = self._body()
            mapping = {
                "environment": "ALLEGRO_ENV",
                "client_id": "ALLEGRO_CLIENT_ID",
                "client_secret": "ALLEGRO_CLIENT_SECRET",
                "user_agent": "ALLEGRO_USER_AGENT",
                "language": "ALLEGRO_LANGUAGE",
                "temu_endpoint": "TEMU_ENDPOINT",
                "temu_app_key": "TEMU_APP_KEY",
                "temu_app_secret": "TEMU_APP_SECRET",
                "temu_access_token": "TEMU_ACCESS_TOKEN",
                "invoice_driver": "INVOICE_DRIVER",
                "szamlazz_agent_key": "SZAMLAZZ_AGENT_KEY",
                "invoice_prefix": "SZAMLAZZ_INVOICE_PREFIX",
                "temu_invoice_prefix": "SZAMLAZZ_TEMU_INVOICE_PREFIX",
                "invoice_email_fallback": "SZAMLAZZ_SEND_EMAIL",
                "temu_invoice_public_base_url": "TEMU_INVOICE_PUBLIC_BASE_URL",
                "temu_platform_name": "TEMU_PLATFORM_NAME",
                "temu_platform_country": "TEMU_PLATFORM_COUNTRY",
                "temu_platform_zip": "TEMU_PLATFORM_ZIP",
                "temu_platform_city": "TEMU_PLATFORM_CITY",
                "temu_platform_street": "TEMU_PLATFORM_STREET",
                "temu_platform_tax_id": "TEMU_PLATFORM_TAX_ID",
                "temu_platform_email": "TEMU_PLATFORM_EMAIL",
                "express_one_endpoint": "EXPRESS_ONE_ENDPOINT",
                "express_one_company_id": "EXPRESS_ONE_COMPANY_ID",
                "express_one_user_name": "EXPRESS_ONE_USER_NAME",
                "express_one_password": "EXPRESS_ONE_PASSWORD",
                "express_one_default_weight_kg": "EXPRESS_ONE_DEFAULT_WEIGHT_KG",
                "temu_express_one_carrier_id": "TEMU_EXPRESS_ONE_CARRIER_ID",
            }
            updates = {
                env_key: str(body[key])
                for key, env_key in mapping.items()
                if key in body and (
                    str(body[key]).strip() != "" or env_key == "TEMU_EXPRESS_ONE_CARRIER_ID"
                )
            }
            environment = updates.get("ALLEGRO_ENV", self.app.config.environment)
            if environment not in {"sandbox", "production"}:
                raise ValueError("Érvénytelen környezet.")
            self.app.config.save(updates)
            self.app.reload_config()
            self.app.database.add_activity("settings", "A kapcsolati beállítások frissítve.")
            self._json({"ok": True, "settings": self.app.config.public_values()})
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            target = WEB_ROOT / "index.html"
        body = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _temu_invoice_file(self, token: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", token):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        record = self.app.database.find_temu_invoice_file(token)
        target = Path(str(record.get("pdf_path", ""))) if record else None
        if not target or not target.is_file() or not target.resolve().is_relative_to((self.app.root / "var" / "invoices").resolve()):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", 'inline; filename="invoice.pdf"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def _temu_label_file(self, order_id: str) -> None:
        if not re.fullmatch(r"PO-[A-Za-z0-9-]{3,80}", order_id):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        record = self.app.database.get_temu_shipment(order_id)
        target = Path(str(record.get("label_path", ""))) if record else None
        labels_root = (self.app.root / "var" / "labels" / "temu").resolve()
        if not target or not target.is_file() or not target.resolve().is_relative_to(labels_root):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'inline; filename="express-one-{order_id}.pdf"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(body)


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: Application):
        super().__init__(address, Handler)
        self.app = app


def main() -> None:
    parser = argparse.ArgumentParser(description="Allegro Sync helyi kezelőfelület")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    app = Application()
    server = AppServer((args.host, args.port), app)
    url = f"http://{args.host}:{args.port}"
    print(f"Allegro Sync elindult: {url}")
    print("Leállítás: Ctrl+C")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAllegro Sync leállítva.")
    finally:
        server.server_close()
