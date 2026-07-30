from __future__ import annotations

import base64
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid
import xml.etree.ElementTree as ET

from .allegro import AllegroClient, AllegroError
from .config import AppConfig
from .database import Database


SZAMLAZZ_URL = "https://www.szamlazz.hu/szamla/"
XML_NAMESPACE = "http://www.szamlazz.hu/xmlszamla"
RESPONSE_NAMESPACE = "http://www.szamlazz.hu/xmlszamlavalasz"
VAT_RATE = Decimal("27")
VAT_MULTIPLIER = Decimal("1.27")


class InvoiceError(RuntimeError):
    pass


def _decimal(value: object, label: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvoiceError(f"Érvénytelen {label}: {value}") from exc


def _amount(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _text(parent: ET.Element, name: str, value: object = "") -> ET.Element:
    child = ET.SubElement(parent, name)
    child.text = str(value) if value is not None else ""
    return child


def _person_name(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    return " ".join(
        part.strip() for part in (str(value.get("firstName", "")), str(value.get("lastName", "")))
        if part.strip()
    )


def _billing_details(order: dict) -> dict[str, str]:
    invoice = order.get("invoice") if isinstance(order.get("invoice"), dict) else {}
    invoice_address = invoice.get("address") if isinstance(invoice.get("address"), dict) else {}
    delivery = order.get("delivery") if isinstance(order.get("delivery"), dict) else {}
    delivery_address = delivery.get("address") if isinstance(delivery.get("address"), dict) else {}
    buyer = order.get("buyer") if isinstance(order.get("buyer"), dict) else {}

    address = invoice_address or delivery_address
    company = address.get("company") if isinstance(address.get("company"), dict) else {}
    natural_person = address.get("naturalPerson") if isinstance(address.get("naturalPerson"), dict) else {}
    name = str(company.get("name", "")).strip() or _person_name(natural_person)
    name = name or str(address.get("companyName", "")).strip() or _person_name(address)
    name = name or str(buyer.get("companyName", "")).strip() or _person_name(buyer)
    name = name or str(buyer.get("login", "")).strip()
    tax_id = str(company.get("taxId", "") or address.get("taxId", "")).strip()

    return {
        "name": name,
        "country": str(address.get("countryCode", "HU") or "HU"),
        "zip": str(address.get("zipCode", "") or address.get("postCode", "")),
        "city": str(address.get("city", "")),
        "street": str(address.get("street", "")),
        "tax_id": tax_id,
        "email": str(buyer.get("email", "")).strip(),
        "delivery_name": (
            str(delivery_address.get("companyName", "")).strip()
            or _person_name(delivery_address)
            or name
        ),
        "delivery_country": str(delivery_address.get("countryCode", "") or ""),
        "delivery_zip": str(
            delivery_address.get("zipCode", "") or delivery_address.get("postCode", "")
        ),
        "delivery_city": str(delivery_address.get("city", "")),
        "delivery_street": str(delivery_address.get("street", "")),
    }


def _invoice_items(order: dict) -> tuple[list[dict[str, object]], str]:
    summary = order.get("summary") if isinstance(order.get("summary"), dict) else {}
    total_to_pay = summary.get("totalToPay") if isinstance(summary.get("totalToPay"), dict) else {}
    currency = str(total_to_pay.get("currency", "HUF"))
    if currency != "HUF":
        raise InvoiceError("Ez a számlázási modul jelenleg csak HUF rendelést kezel.")

    result: list[dict[str, object]] = []
    gross_sum = Decimal("0")
    line_items = order.get("lineItems") if isinstance(order.get("lineItems"), list) else []
    for line in line_items:
        if not isinstance(line, dict):
            continue
        offer = line.get("offer") if isinstance(line.get("offer"), dict) else {}
        price = line.get("price") if isinstance(line.get("price"), dict) else {}
        if not price:
            price = line.get("originalPrice") if isinstance(line.get("originalPrice"), dict) else {}
        quantity = int(line.get("quantity", 0) or 0)
        if quantity <= 0:
            raise InvoiceError("A rendelés egyik tételének mennyisége hibás.")
        unit_gross = _decimal(price.get("amount"), "tételár")
        line_gross = unit_gross * quantity
        result.append({
            "name": str(offer.get("name", "Allegro termék")),
            "quantity": quantity,
            "unit_gross": unit_gross,
            "gross": line_gross,
        })
        gross_sum += line_gross

    delivery = order.get("delivery") if isinstance(order.get("delivery"), dict) else {}
    delivery_cost = delivery.get("cost") if isinstance(delivery.get("cost"), dict) else {}
    delivery_gross = _decimal(delivery_cost.get("amount", "0"), "szállítási díj")
    if delivery_gross:
        result.append({
            "name": "Szállítási díj",
            "quantity": 1,
            "unit_gross": delivery_gross,
            "gross": delivery_gross,
        })
        gross_sum += delivery_gross

    if not result:
        raise InvoiceError("A rendelés nem tartalmaz számlázható tételt.")
    expected = _decimal(total_to_pay.get("amount"), "rendelési végösszeg")
    if gross_sum.quantize(Decimal("0.01")) != expected.quantize(Decimal("0.01")):
        raise InvoiceError(
            "A tételek és a szállítás összege nem egyezik az Allegro végösszegével; "
            "a hibás számla elkerülése érdekében a művelet leállt."
        )
    return result, currency


def build_invoice_xml(
    order: dict,
    agent_key: str,
    prefix: str = "",
    send_email: bool = False,
) -> bytes:
    if not agent_key.strip():
        raise InvoiceError("Hiányzik a Számlázz.hu Agent kulcs.")
    order_id = str(order.get("id", "")).strip()
    if not order_id:
        raise InvoiceError("Hiányzik az Allegro rendelésazonosító.")
    status = str(order.get("status", ""))
    if status != "READY_FOR_PROCESSING":
        raise InvoiceError("Csak feldolgozásra kész Allegro-rendelés számlázható.")

    billing = _billing_details(order)
    missing = [label for key, label in (
        ("name", "vevő neve"), ("zip", "irányítószám"),
        ("city", "település"), ("street", "cím"), ("email", "vevő e-mail-címe"),
    ) if not billing[key]]
    if missing:
        raise InvoiceError("Hiányos számlázási adatok: " + ", ".join(missing) + ".")
    items, currency = _invoice_items(order)

    payment = order.get("payment") if isinstance(order.get("payment"), dict) else {}
    payment_type = str(payment.get("type", "ONLINE"))
    payment_names = {"ONLINE": "Online fizetés", "CASH_ON_DELIVERY": "Utánvét", "SPLIT_PAYMENT": "Online fizetés"}
    invoice_date = str(payment.get("finishedAt") or order.get("updatedAt") or date.today().isoformat())[:10]

    ET.register_namespace("", XML_NAMESPACE)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root = ET.Element(
        f"{{{XML_NAMESPACE}}}xmlszamla",
        {f"{{http://www.w3.org/2001/XMLSchema-instance}}schemaLocation": (
            f"{XML_NAMESPACE} https://www.szamlazz.hu/szamla/docs/xsds/agent/xmlszamla.xsd"
        )},
    )
    settings = ET.SubElement(root, "beallitasok")
    _text(settings, "szamlaagentkulcs", agent_key.strip())
    _text(settings, "eszamla", "true")
    _text(settings, "szamlaLetoltes", "true")
    _text(settings, "valaszVerzio", "2")
    _text(settings, "aggregator")
    _text(settings, "szamlaKulsoAzon", order_id)

    header = ET.SubElement(root, "fejlec")
    _text(header, "keltDatum", invoice_date)
    _text(header, "teljesitesDatum", invoice_date)
    _text(header, "fizetesiHataridoDatum", invoice_date)
    _text(header, "fizmod", payment_names.get(payment_type, "Online fizetés"))
    _text(header, "penznem", currency)
    _text(header, "szamlaNyelve", "hu")
    _text(header, "megjegyzes", f"Allegro rendelés: {order_id}")
    _text(header, "arfolyamBank", "MNB")
    _text(header, "arfolyam", "0.0")
    _text(header, "rendelesSzam", order_id)
    _text(header, "dijbekeroSzamlaszam")
    _text(header, "elolegszamla", "false")
    _text(header, "vegszamla", "false")
    _text(header, "helyesbitoszamla", "false")
    _text(header, "helyesbitettSzamlaszam")
    _text(header, "dijbekero", "false")
    _text(header, "szamlaszamElotag", prefix.strip())

    seller = ET.SubElement(root, "elado")
    _text(seller, "bank")
    _text(seller, "bankszamlaszam")
    _text(seller, "emailReplyto")
    _text(seller, "emailTargy", "Allegro rendelés számlája")
    _text(seller, "emailSzoveg", "Köszönjük a vásárlást! A számlát mellékeltük.")

    buyer = ET.SubElement(root, "vevo")
    _text(buyer, "nev", billing["name"])
    _text(buyer, "orszag", billing["country"])
    _text(buyer, "irsz", billing["zip"])
    _text(buyer, "telepules", billing["city"])
    _text(buyer, "cim", billing["street"])
    _text(buyer, "email", billing["email"])
    _text(buyer, "sendEmail", str(send_email).lower())
    _text(buyer, "adoalany", "1" if billing["tax_id"] else "-1")
    _text(buyer, "adoszam", billing["tax_id"])
    _text(buyer, "postazasiNev", billing["delivery_name"])
    _text(buyer, "postazasiOrszag", billing["delivery_country"])
    _text(buyer, "postazasiIrsz", billing["delivery_zip"])
    _text(buyer, "postazasiTelepules", billing["delivery_city"])
    _text(buyer, "postazasiCim", billing["delivery_street"])

    waybill = ET.SubElement(root, "fuvarlevel")
    _text(waybill, "uticel")
    _text(waybill, "futarSzolgalat")

    invoice_items = ET.SubElement(root, "tetelek")
    for item in items:
        quantity = Decimal(str(item["quantity"]))
        gross = Decimal(str(item["gross"]))
        unit_gross = Decimal(str(item["unit_gross"]))
        unit_net = (unit_gross / VAT_MULTIPLIER).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        net = unit_net * quantity
        vat = gross - net
        node = ET.SubElement(invoice_items, "tetel")
        _text(node, "megnevezes", item["name"])
        _text(node, "mennyiseg", item["quantity"])
        _text(node, "mennyisegiEgyseg", "db")
        _text(node, "nettoEgysegar", format(unit_net, "f"))
        _text(node, "afakulcs", format(VAT_RATE, "f"))
        _text(node, "nettoErtek", format(net, "f"))
        _text(node, "afaErtek", format(vat, "f"))
        _text(node, "bruttoErtek", _amount(gross))
        _text(node, "megjegyzes")

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class SzamlazzClient:
    def __init__(self, config: AppConfig):
        self.config = config

    def create_invoice(self, order: dict) -> tuple[str, bytes, str]:
        send_email = self.config.values.get("SZAMLAZZ_SEND_EMAIL", "false").lower() == "true"
        xml = build_invoice_xml(
            order,
            self.config.values.get("SZAMLAZZ_AGENT_KEY", ""),
            self.config.values.get("SZAMLAZZ_INVOICE_PREFIX", ""),
            send_email,
        )
        boundary = "----AllegroSync" + uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="action-xmlagentxmlfile"; filename="invoice.xml"\r\n'
            "Content-Type: application/xml\r\n\r\n"
        ).encode() + xml + f"\r\n--{boundary}--\r\n".encode()
        request = Request(
            SZAMLAZZ_URL,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": self.config.values.get("ALLEGRO_USER_AGENT", "allegro-sync/0.1"),
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                raw = response.read()
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")[:500]
            raise InvoiceError(f"Számlázz.hu HTTP hiba ({exc.code}): {message}") from exc
        except URLError as exc:
            raise InvoiceError(f"Nem érhető el a Számlázz.hu: {exc.reason}") from exc

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise InvoiceError("A Számlázz.hu érvénytelen választ adott.") from exc
        namespace = {"s": RESPONSE_NAMESPACE}
        successful = root.findtext("s:sikeres", default="false", namespaces=namespace) == "true"
        if not successful:
            code = root.findtext("s:hibakod", default="", namespaces=namespace)
            message = root.findtext("s:hibauzenet", default="Ismeretlen számlázási hiba.", namespaces=namespace)
            raise InvoiceError(f"Számlázz.hu hiba{f' ({code})' if code else ''}: {message}")
        invoice_number = root.findtext("s:szamlaszam", default="", namespaces=namespace).strip()
        encoded_pdf = "".join(
            root.findtext("s:pdf", default="", namespaces=namespace).split()
        )
        if not invoice_number or not encoded_pdf:
            raise InvoiceError("A Számlázz.hu válaszából hiányzik a számlaszám vagy a PDF.")
        try:
            pdf = base64.b64decode(encoded_pdf, validate=True)
        except ValueError as exc:
            raise InvoiceError("A Számlázz.hu hibás PDF-adatot adott vissza.") from exc
        if not pdf.startswith(b"%PDF"):
            raise InvoiceError("A Számlázz.hu válasza nem érvényes PDF.")
        if len(pdf) > 3_000_000:
            raise InvoiceError("A számla PDF nagyobb az Allegro 3 MB-os korlátjánál.")
        return invoice_number, pdf, _billing_details(order)["email"]


class InvoiceService:
    def __init__(self, config: AppConfig, database: Database, allegro: AllegroClient):
        self.config = config
        self.database = database
        self.allegro = allegro
        self.szamlazz = SzamlazzClient(config)

    def list_orders(self) -> list[dict]:
        response = self.allegro.request(
            "GET", "/order/checkout-forms", query={"limit": "100"}
        )["body"]
        orders = response.get("checkoutForms", []) if isinstance(response, dict) else []
        local = self.database.list_order_invoices()
        return [self._summary(order, local.get(str(order.get("id", "")))) for order in orders if isinstance(order, dict)]

    @staticmethod
    def _summary(order: dict, invoice: dict | None) -> dict:
        buyer = order.get("buyer") if isinstance(order.get("buyer"), dict) else {}
        summary = order.get("summary") if isinstance(order.get("summary"), dict) else {}
        total = summary.get("totalToPay") if isinstance(summary.get("totalToPay"), dict) else {}
        name = str(buyer.get("companyName", "")).strip() or _person_name(buyer) or str(buyer.get("login", ""))
        lines = order.get("lineItems") if isinstance(order.get("lineItems"), list) else []
        return {
            "id": str(order.get("id", "")),
            "status": str(order.get("status", "")),
            "buyer_name": name,
            "buyer_email": str(buyer.get("email", "")),
            "total_amount": str(total.get("amount", "")),
            "currency": str(total.get("currency", "")),
            "updated_at": order.get("updatedAt"),
            "item_count": sum(int(line.get("quantity", 0) or 0) for line in lines if isinstance(line, dict)),
            "invoice_required": bool((order.get("invoice") or {}).get("required")) if isinstance(order.get("invoice"), dict) else False,
            "invoice_status": str(invoice.get("status", "none")) if invoice else "none",
            "invoice_number": str(invoice.get("invoice_number", "") or "") if invoice else "",
            "invoice_error": str(invoice.get("error", "") or "") if invoice else "",
        }

    def create_and_upload(self, order_id: str) -> dict:
        order_id = order_id.strip()
        if not re.fullmatch(r"[A-Za-z0-9-]{8,80}", order_id):
            raise InvoiceError("Érvénytelen Allegro rendelésazonosító.")
        if self.config.values.get("INVOICE_DRIVER") != "szamlazz":
            raise InvoiceError("Kapcsold be a Számla Agent modult a Beállításokban.")
        if not self.config.values.get("SZAMLAZZ_AGENT_KEY", ""):
            raise InvoiceError("Add meg a Számlázz.hu Agent kulcsot a Beállításokban.")

        current = self.database.get_order_invoice(order_id)
        if current and current.get("status") == "uploaded":
            raise InvoiceError("Ehhez a rendeléshez már feltöltöttük a számlát az Allegróra.")
        order = self.allegro.request("GET", f"/order/checkout-forms/{quote(order_id)}")["body"]
        if not isinstance(order, dict):
            raise InvoiceError("Az Allegro nem adott vissza rendelési adatokat.")

        send_email = self.config.values.get("SZAMLAZZ_SEND_EMAIL", "false").lower() == "true"
        pdf_path = Path(str(current.get("pdf_path", ""))) if current and current.get("pdf_path") else None
        if current and current.get("invoice_number") and pdf_path and pdf_path.is_file():
            invoice_number = str(current["invoice_number"])
            pdf = pdf_path.read_bytes()
            buyer_email = str(current.get("buyer_email", ""))
        else:
            invoice_number, pdf, buyer_email = self.szamlazz.create_invoice(order)
            invoice_dir = self.config.root / "var" / "invoices" / self.config.environment
            invoice_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = invoice_dir / f"{order_id}.pdf"
            pdf_path.write_bytes(pdf)
            current = self.database.save_order_invoice(
                order_id,
                status="created",
                buyer_email=buyer_email,
                invoice_number=invoice_number,
                pdf_path=str(pdf_path),
                email_fallback=send_email,
            )

        allegro_invoice_id = str((current or {}).get("allegro_invoice_id", "") or "")
        try:
            if not allegro_invoice_id:
                safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", invoice_number).strip("-")
                created = self.allegro.request(
                    "POST",
                    f"/order/checkout-forms/{quote(order_id)}/invoices",
                    body={
                        "file": {"name": f"{safe_filename or 'szamla'}.pdf"},
                        "invoiceNumber": invoice_number,
                    },
                )["body"]
                allegro_invoice_id = str(created.get("id", "")) if isinstance(created, dict) else ""
                if not allegro_invoice_id:
                    raise AllegroError("Az Allegro nem adott számlaazonosítót.")
                self.database.save_order_invoice(
                    order_id,
                    status="uploading",
                    buyer_email=buyer_email,
                    invoice_number=invoice_number,
                    allegro_invoice_id=allegro_invoice_id,
                    pdf_path=str(pdf_path),
                    email_fallback=send_email,
                )
            result = self.allegro.upload_pdf(
                f"/order/checkout-forms/{quote(order_id)}/invoices/{quote(allegro_invoice_id)}/file",
                pdf,
            )
        except Exception as exc:
            self.database.save_order_invoice(
                order_id,
                status="upload_failed",
                buyer_email=buyer_email,
                invoice_number=invoice_number,
                allegro_invoice_id=allegro_invoice_id or None,
                pdf_path=str(pdf_path),
                email_fallback=send_email,
                error=str(exc),
            )
            raise

        self.database.save_order_invoice(
            order_id,
            status="uploaded",
            buyer_email=buyer_email,
            invoice_number=invoice_number,
            allegro_invoice_id=allegro_invoice_id,
            pdf_path=str(pdf_path),
            email_fallback=send_email,
        )
        self.database.add_activity(
            "invoice", f"{invoice_number} számla feltöltve az Allegro rendeléshez."
        )
        return {
            "ok": True,
            "order_id": order_id,
            "invoice_number": invoice_number,
            "allegro_invoice_id": allegro_invoice_id,
            "allegro_status": result["status"],
            "email": buyer_email,
            "email_fallback": send_email,
        }
