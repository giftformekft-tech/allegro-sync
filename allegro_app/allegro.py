from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import AppConfig
from .database import Database


class AllegroError(RuntimeError):
    pass


class AllegroApiError(AllegroError):
    def __init__(self, status: int, message: str, details: object = None):
        super().__init__(message)
        self.status = status
        self.details = details


class AllegroAuth:
    DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

    def __init__(self, config: AppConfig, database: Database):
        self.config = config
        self.database = database

    def _post_form(self, path: str, values: dict[str, str]) -> dict:
        client_id = self.config.values.get("ALLEGRO_CLIENT_ID", "")
        client_secret = self.config.values.get("ALLEGRO_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise AllegroError("Előbb add meg az Allegro Client ID-t és Client Secretet.")
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        request = Request(
            self.config.auth_base + path,
            data=urlencode(values).encode(),
            headers={
                "Authorization": "Basic " + credentials,
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.config.values.get("ALLEGRO_USER_AGENT", "allegro-sync/0.1"),
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                details = json.loads(body)
                message = details.get("error_description") or details.get("error") or body
            except json.JSONDecodeError:
                message = body[:300]
            raise AllegroError(f"Allegro OAuth hiba (HTTP {exc.code}): {message}") from exc
        except URLError as exc:
            raise AllegroError(f"Nem érhető el az Allegro: {exc.reason}") from exc

    def check_application(self) -> dict:
        payload = self._post_form("/token", {"grant_type": "client_credentials"})
        self._save_token("app", payload)
        self.database.add_activity("connection", "Az Allegro alkalmazáskapcsolat ellenőrzése sikeres.")
        return {"ok": True, "environment": self.config.environment, "expires_in": int(payload.get("expires_in", 3600))}

    def _save_token(self, token_type: str, payload: dict) -> str:
        expires = int(payload.get("expires_in", 3600))
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires)).isoformat(timespec="seconds")
        current = self.database.get_token(token_type)
        refresh = payload.get("refresh_token") or (current or {}).get("refresh_token")
        self.database.save_token(token_type, payload["access_token"], refresh, expires_at, payload.get("scope"))
        return str(payload["access_token"])

    @staticmethod
    def _usable(token: dict | None) -> bool:
        if not token:
            return False
        try:
            expiry = datetime.fromisoformat(str(token["expires_at"]))
            return expiry > datetime.now(timezone.utc) + timedelta(seconds=60)
        except (KeyError, TypeError, ValueError):
            return False

    def app_token(self) -> str:
        token = self.database.get_token("app")
        if self._usable(token):
            return str(token["access_token"])
        payload = self._post_form("/token", {"grant_type": "client_credentials"})
        return self._save_token("app", payload)

    def user_token(self) -> str:
        token = self.database.get_token("user")
        if self._usable(token):
            return str(token["access_token"])
        if not token or not token.get("refresh_token"):
            raise AllegroError("Az eladói fiók még nincs csatlakoztatva. Nyisd meg a Kapcsolatok oldalt.")
        try:
            payload = self._post_form("/token", {
                "grant_type": "refresh_token",
                "refresh_token": str(token["refresh_token"]),
            })
        except AllegroError as exc:
            raise AllegroError("Az Allegro bejelentkezés lejárt. Csatlakoztasd újra az eladói fiókot.") from exc
        return self._save_token("user", payload)

    def start_device_flow(self) -> dict:
        client_id = self.config.values.get("ALLEGRO_CLIENT_ID", "")
        payload = self._post_form("/device", {"client_id": client_id})
        required = ("device_code", "user_code", "verification_uri")
        if any(key not in payload for key in required):
            raise AllegroError("Hiányos választ adott az Allegro a bejelentkezés indításakor.")
        return {
            "device_code": payload["device_code"],
            "user_code": payload["user_code"],
            "verification_uri": payload["verification_uri"],
            "verification_uri_complete": payload.get("verification_uri_complete"),
            "interval": int(payload.get("interval", 5)),
            "expires_in": int(payload.get("expires_in", 600)),
        }

    def poll_device_flow(self, device_code: str) -> dict:
        try:
            payload = self._post_form("/token", {"grant_type": self.DEVICE_GRANT, "device_code": device_code})
        except AllegroError as exc:
            if "authorization_pending" in str(exc) or "slow_down" in str(exc):
                return {"status": "pending"}
            raise
        expires = int(payload.get("expires_in", 43200))
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires)).isoformat(timespec="seconds")
        self.database.save_token(
            "user", payload["access_token"], payload.get("refresh_token"), expires_at, payload.get("scope")
        )
        self.database.add_activity("connection", "Az Allegro eladói fiók csatlakoztatva.")
        return {"status": "authorized"}


class AllegroClient:
    VENDOR = "application/vnd.allegro.public.v1+json"

    def __init__(self, config: AppConfig, database: Database):
        self.config = config
        self.database = database
        self.auth = AllegroAuth(config, database)

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict | None = None,
        token_type: str = "user",
    ) -> dict:
        url = self.config.api_base + "/" + path.lstrip("/")
        if query:
            url += "?" + urlencode(query)
        token = self.auth.user_token() if token_type == "user" else self.auth.app_token()
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": self.VENDOR,
            "Accept-Language": self.config.values.get("ALLEGRO_LANGUAGE", "hu-HU"),
            "User-Agent": self.config.values.get("ALLEGRO_USER_AGENT", "allegro-sync/0.1"),
        }
        if payload is not None:
            headers["Content-Type"] = self.VENDOR
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
                return {
                    "status": response.status,
                    "body": json.loads(raw) if raw else {},
                    "headers": {key.lower(): value for key, value in response.headers.items()},
                }
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                details: object = json.loads(raw)
            except json.JSONDecodeError:
                details = raw[:1000]
            message = self._error_message(details) or f"Allegro API hiba (HTTP {exc.code})."
            raise AllegroApiError(exc.code, message, details) from exc
        except URLError as exc:
            raise AllegroError(f"Nem érhető el az Allegro API: {exc.reason}") from exc

    def upload_pdf(self, path: str, content: bytes) -> dict:
        if not content.startswith(b"%PDF"):
            raise ValueError("Az Allegrohoz csak érvényes PDF számla tölthető fel.")
        url = self.config.api_base + "/" + path.lstrip("/")
        headers = {
            "Authorization": "Bearer " + self.auth.user_token(),
            "Accept": self.VENDOR,
            "Accept-Language": self.config.values.get("ALLEGRO_LANGUAGE", "hu-HU"),
            "Content-Type": "application/pdf",
            "User-Agent": self.config.values.get("ALLEGRO_USER_AGENT", "allegro-sync/0.1"),
        }
        request = Request(url, data=content, headers=headers, method="PUT")
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return {"status": response.status, "body": raw}
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                details: object = json.loads(raw)
            except json.JSONDecodeError:
                details = raw[:1000]
            message = self._error_message(details) or f"Allegro API hiba (HTTP {exc.code})."
            raise AllegroApiError(exc.code, message, details) from exc
        except URLError as exc:
            raise AllegroError(f"Nem érhető el az Allegro API: {exc.reason}") from exc

    @staticmethod
    def _error_message(details: object) -> str:
        if not isinstance(details, dict):
            return str(details)
        errors = details.get("errors")
        if isinstance(errors, list):
            messages = []
            for error in errors:
                if isinstance(error, dict):
                    message = error.get("userMessage") or error.get("message") or error.get("code")
                    if message:
                        messages.append(str(message))
            if messages:
                return " ".join(messages)
        return str(details.get("error_description") or details.get("message") or details.get("error") or "")


class AllegroCatalog:
    def __init__(self, client: AllegroClient):
        self.client = client

    def suggest(self, phrase: str) -> list[dict]:
        phrase = phrase.strip()
        if len(phrase) < 3:
            raise ValueError("Adj meg legalább három karakteres keresőkifejezést.")
        response = self.client.request(
            "GET", "/sale/matching-categories", query={"name": phrase}, token_type="app"
        )
        return [item for item in response["body"].get("matchingCategories", []) if isinstance(item, dict)]

    def inspect(self, category_id: str) -> dict:
        category_id = category_id.strip()
        if not category_id:
            raise ValueError("Hiányzik a kategóriaazonosító.")
        category = self.client.request(
            "GET", f"/sale/categories/{category_id}", token_type="app"
        )["body"]
        parameters = self.client.request(
            "GET", f"/sale/categories/{category_id}/parameters", token_type="app"
        )["body"].get("parameters", [])
        path = self._path(category)
        normalized = [self._parameter(item) for item in parameters if isinstance(item, dict)]
        gtin = [item for item in normalized if item["is_gtin"]]
        # For a newly described catalog product Allegro explicitly defines the
        # GTIN requirement through requiredForProduct. The generic `required`
        # flag alone must not turn an optional product GTIN into a blocker.
        gtin_required = any(
            item["required_for_product"] and not item.get("required_if") for item in gtin
        )
        gtin_conditional = any(
            item["required_for_product"] and bool(item.get("required_if")) for item in gtin
        )
        options = category.get("options") if isinstance(category.get("options"), dict) else {}
        leaf = bool(category.get("leaf"))
        product_creation = bool(options.get("productCreationEnabled"))
        offer_creation = bool(options.get("offersWithProductPublicationEnabled"))
        return {
            "id": str(category.get("id", category_id)),
            "name": str(category.get("name", category_id)),
            "path": path,
            "leaf": leaf,
            "product_creation_enabled": product_creation,
            "offer_creation_enabled": offer_creation,
            "gtin_present": bool(gtin),
            "gtin_required": gtin_required,
            "gtin_conditional": gtin_conditional,
            "gtin_offer_required": any(item["required"] for item in gtin),
            "can_create_without_gtin": leaf and product_creation and offer_creation and not gtin_required,
            "parameters": normalized,
        }

    def _path(self, category: dict) -> list[dict]:
        path = [{"id": str(category.get("id", "")), "name": str(category.get("name", ""))}]
        parent = category.get("parent")
        guard = 0
        while isinstance(parent, dict) and parent.get("id") and guard < 10:
            guard += 1
            current = self.client.request(
                "GET", f"/sale/categories/{parent['id']}", token_type="app"
            )["body"]
            path.insert(0, {"id": str(current.get("id", "")), "name": str(current.get("name", ""))})
            parent = current.get("parent")
        return path

    @staticmethod
    def _parameter(item: dict) -> dict:
        options = item.get("options") if isinstance(item.get("options"), dict) else {}
        name = str(item.get("name", ""))
        return {
            "id": str(item.get("id", "")),
            "name": name,
            "type": str(item.get("type", "string")),
            "required": bool(item.get("required")),
            "required_for_product": bool(item.get("requiredForProduct")),
            "describes_product": bool(options.get("describesProduct")),
            "is_gtin": bool(options.get("isGTIN")) or "GTIN" in name.upper() or "EAN" in name.upper(),
            "unit": item.get("unit"),
            "dictionary": item.get("dictionary") if isinstance(item.get("dictionary"), list) else [],
            "restrictions": item.get("restrictions") if isinstance(item.get("restrictions"), dict) else {},
            "required_if": item.get("requiredIf") if isinstance(item.get("requiredIf"), dict) else None,
            "displayed_if": item.get("displayedIf") if isinstance(item.get("displayedIf"), dict) else None,
            "options": options,
        }
