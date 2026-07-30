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
        expires = int(payload.get("expires_in", 3600))
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires)).isoformat(timespec="seconds")
        self.database.save_token("app", payload["access_token"], None, expires_at, payload.get("scope"))
        self.database.add_activity("connection", "Az Allegro alkalmazáskapcsolat ellenőrzése sikeres.")
        return {"ok": True, "environment": self.config.environment, "expires_in": expires}

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
