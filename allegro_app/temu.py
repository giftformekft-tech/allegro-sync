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
            "timestamp": int(self.clock()),
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
        success_codes = (None, "", 0, "0", 1000000, "1000000", "SUCCESS")
        if success is False or (success is not True and error_code not in success_codes):
            message = (
                result.get("errorMsg")
                or result.get("error_msg")
                or result.get("message")
                or "Ismeretlen Temu API-hiba."
            )
            raise TemuError(f"Temu API-hiba ({error_code or 'ismeretlen'}): {message}")
        return result

    @staticmethod
    def _result(result: dict) -> dict:
        payload = result.get("result")
        if not isinstance(payload, dict):
            raise TemuError("A Temu API válaszából hiányzik a result objektum.")
        return payload

    def categories(self, parent_id: int = 0) -> dict[str, object]:
        result = self._result(
            self.request("bg.local.goods.cats.get", {"parentCatId": parent_id})
        )
        rows = result.get("goodsCatsList")
        if not isinstance(rows, list):
            rows = []
        categories = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            categories.append({
                "id": str(row.get("catId", "")),
                "parent_id": str(row.get("parentId", parent_id)),
                "name": str(row.get("catName", "")),
                "level": int(row.get("level", 0) or 0),
                "leaf": bool(row.get("leaf", False)),
            })
        categories.sort(key=lambda item: str(item["name"]).casefold())
        return {"parent_id": str(parent_id), "categories": categories}

    @staticmethod
    def _property(row: object) -> dict[str, object] | None:
        if not isinstance(row, dict):
            return None
        values = []
        for value in row.get("values") or []:
            if not isinstance(value, dict):
                continue
            group = value.get("group") if isinstance(value.get("group"), dict) else {}
            values.append({
                "vid": str(value.get("vid", "")),
                "spec_id": str(value.get("specId", "")),
                "value": str(value.get("value", "")),
                "group": str(group.get("name", "")),
            })
        units = []
        for unit in row.get("valueUnitList") or []:
            if not isinstance(unit, dict):
                continue
            units.append({
                "id": str(unit.get("valueUnitId", unit.get("id", ""))),
                "name": str(unit.get("valueUnit", unit.get("name", ""))),
            })
        show_condition = row.get("showCondition")
        if not isinstance(show_condition, dict):
            show_condition = {}
        parent_values = row.get("templatePropertyValueParentList")
        if not isinstance(parent_values, list):
            parent_values = []
        return {
            "pid": str(row.get("pid", "")),
            "ref_pid": str(row.get("refPid", "")),
            "template_pid": str(row.get("templatePid", "")),
            "parent_spec_id": str(row.get("parentSpecId", "")),
            "name": str(row.get("name", "")),
            "required": bool(row.get("required", False)),
            "is_sale": bool(row.get("isSale", False)),
            "main_sale": bool(row.get("mainSale", False)),
            "control_type": int(row.get("controlType", 0) or 0),
            "choose_max_num": int(row.get("chooseMaxNum", 0) or 0),
            "show_type": int(row.get("showType", 0) or 0),
            "parent_template_pid": str(row.get("parentTemplatePid", "")),
            "show_condition": show_condition,
            "parent_value_rules": parent_values,
            "value_units": units,
            "min_value": str(row.get("minValue", "")),
            "max_value": str(row.get("maxValue", "")),
            "values": values,
        }

    def category_template(self, category_id: int) -> dict[str, object]:
        result = self._result(
            self.request("bg.local.goods.template.get", {"catId": category_id})
        )
        template = result.get("templateInfo")
        if not isinstance(template, dict):
            template = {}
        sales = [
            property_data
            for row in template.get("goodsSpecProperties") or []
            if (property_data := self._property(row)) is not None
        ]
        properties = [
            property_data
            for row in template.get("goodsProperties") or []
            if (property_data := self._property(row)) is not None
        ]
        return {
            "category_id": str(category_id),
            "input_max_spec_num": int(result.get("inputMaxSpecNum", 0) or 0),
            "single_spec_value_num": int(result.get("singleSpecValueNum", 0) or 0),
            "sales_properties": sales,
            "properties": properties,
        }

    def check_connection(self) -> dict[str, object]:
        result = self.request("bg.open.accesstoken.info.get")
        self.database.add_activity("connection", "A Temu Open Platform kapcsolat sikeresen ellenőrizve.")
        return {
            "ok": True,
            "api_type": "bg.open.accesstoken.info.get",
            "request_id": result.get("requestId") or result.get("request_id") or "",
        }
