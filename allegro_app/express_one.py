from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import AppConfig


class ExpressOneError(RuntimeError):
    pass


class ExpressOneClient:
    """Small JSON client for Express One Web API 2.x."""

    def __init__(self, config: AppConfig):
        self.config = config

    def _auth(self) -> dict[str, str]:
        problems = self.config.express_one_validation()
        if problems:
            raise ExpressOneError(" ".join(problems))
        return {
            "company_id": self.config.values["EXPRESS_ONE_COMPANY_ID"],
            "user_name": self.config.values["EXPRESS_ONE_USER_NAME"],
            "password": self.config.values["EXPRESS_ONE_PASSWORD"],
        }

    def request(self, group: str, method: str, payload: dict[str, Any] | None = None) -> dict:
        endpoint = self.config.values.get(
            "EXPRESS_ONE_ENDPOINT", "https://webservice.expressone.hu"
        ).rstrip("/")
        url = f"{endpoint}/{group}/{method}/response_format/json"
        body = {"auth": self._auth(), **(payload or {})}
        request = Request(
            url,
            data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise ExpressOneError(f"Az Express One API HTTP {exc.code} hibát adott: {details[:500]}") from exc
        except URLError as exc:
            raise ExpressOneError(f"Az Express One API nem érhető el: {exc.reason}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExpressOneError("Az Express One API nem értelmezhető választ adott.") from exc
        if not isinstance(result, dict):
            raise ExpressOneError("Az Express One API válasza nem JSON objektum.")
        if result.get("successfull") is False or result.get("successful") is False:
            message = result.get("error_messages") or result.get("error_message") or result.get("error")
            if isinstance(message, list):
                message = "; ".join(str(item) for item in message)
            raise ExpressOneError(f"Express One API-hiba: {message or 'ismeretlen hiba'}")
        return result

    def check_connection(self) -> dict[str, Any]:
        return self.request("ping", "get_request")

    def create_labels(self, deliveries: list[dict[str, Any]]) -> dict[str, Any]:
        return self.request("parcel", "create_labels", {
            "deliveries": deliveries,
            "labels": {
                "data_type": "PDF",
                "size": "A4",
                "dpi": "300",
                "pdf_etiket_position": "0",
            },
        })

    def parcel_status(self, parcel_number: str) -> dict[str, Any]:
        return self.request("tracking", "get_parcel_status", {
            "parcel_number": parcel_number,
        })
