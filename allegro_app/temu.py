from __future__ import annotations

import hashlib
import json
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import AppConfig
from .database import Database


class TemuError(RuntimeError):
    pass


def _sign_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def sign_payload(payload: dict[str, object], app_secret: str) -> str:
    """Create the uppercase MD5 signature expected by the Temu Open Platform."""
    if not app_secret:
        raise TemuError("Hiányzik a Temu App Secret.")
    parts = [
        f"{key}{_sign_value(value)}"
        for key, value in sorted(payload.items())
        if key != "sign" and value is not None
    ]
    source = app_secret + "".join(parts) + app_secret
    return hashlib.md5(source.encode("utf-8")).hexdigest().upper()


class TemuClient:
    def __init__(
        self,
        config: AppConfig,
        database: Database,
        *,
        clock: Callable[[], float] = time.time,
    ):
        self.config = config
        self.database = database
        self.clock = clock

    def request(self, api_type: str, parameters: dict[str, object] | None = None) -> dict:
        problems = self.config.temu_validation()
        if problems:
            raise TemuError(" ".join(problems))

        payload: dict[str, object] = {
            "type": api_type,
            "app_key": self.config.values["TEMU_APP_KEY"],
            "access_token": self.config.values["TEMU_ACCESS_TOKEN"],
            "timestamp": str(int(self.clock())),
            "data_type": "JSON",
        }
        if parameters:
            payload.update(parameters)
        payload["sign"] = sign_payload(payload, self.config.values["TEMU_APP_SECRET"])

        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.config.values["TEMU_ENDPOINT"],
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise TemuError(f"A Temu API HTTP {exc.code} hibát adott: {details[:500]}") from exc
        except URLError as exc:
            raise TemuError(f"A Temu API nem érhető el: {exc.reason}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TemuError("A Temu API nem értelmezhető választ adott.") from exc

        if not isinstance(result, dict):
            raise TemuError("A Temu API válasza nem JSON objektum.")
        success = result.get("success")
        error_code = result.get("errorCode") or result.get("error_code") or result.get("code")
        if success is False or (error_code not in (None, "", 0, "0", "SUCCESS")):
            message = (
                result.get("errorMsg")
                or result.get("error_msg")
                or result.get("message")
                or "Ismeretlen Temu API-hiba."
            )
            raise TemuError(f"Temu API-hiba ({error_code or 'ismeretlen'}): {message}")
        return result

    def check_connection(self) -> dict[str, object]:
        result = self.request("bg.open.accesstoken.info.get")
        self.database.add_activity("connection", "A Temu Open Platform kapcsolat sikeresen ellenőrizve.")
        return {
            "ok": True,
            "api_type": "bg.open.accesstoken.info.get",
            "request_id": result.get("requestId") or result.get("request_id") or "",
        }
