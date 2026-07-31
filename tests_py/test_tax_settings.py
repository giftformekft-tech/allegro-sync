from __future__ import annotations

import unittest

from allegro_app.offers import OfferService


class FakeClient:
    def __init__(self, body: dict):
        self.body = body

    def request(self, method: str, path: str, **kwargs: object) -> dict:
        self.request_data = (method, path, kwargs)
        return {"body": self.body}


class TaxSettingsTest(unittest.TestCase):
    def test_current_allegro_response_resolves_hungarian_27_percent_goods(self) -> None:
        client = FakeClient({
            "subjects": [
                {"label": "Áru", "value": "GOODS"},
                {"label": "Kiválasztás", "value": None},
            ],
            "rates": [{
                "countryCode": "HU",
                "values": [
                    {
                        "label": "27%",
                        "value": "27.00",
                        "exemptionRequired": False,
                    },
                    {"label": "Kiválasztás", "value": None},
                ],
            }],
            "exemptions": [{"label": "Kiválasztás", "value": None}],
        })
        service = OfferService(None, None, client)  # type: ignore[arg-type]

        settings = service.tax_settings("87913", "HU")

        self.assertEqual(1, len(settings))
        self.assertEqual("HU|27.00|GOODS|", settings[0]["id"])
        self.assertEqual("HU|27.00|GOODS|", service.default_tax_setting_id(settings))
        self.assertEqual("", settings[0]["exemption"])

    def test_legacy_setting_response_remains_supported(self) -> None:
        service = OfferService(None, None, FakeClient({
            "settings": [{
                "id": "legacy-id",
                "countryCode": "HU",
                "rate": {"id": "27.00"},
                "subject": {"id": "GOODS"},
                "exemption": {"id": ""},
            }],
        }))  # type: ignore[arg-type]

        settings = service.tax_settings("87913", "HU")

        self.assertEqual("legacy-id", service.default_tax_setting_id(settings))


if __name__ == "__main__":
    unittest.main()
