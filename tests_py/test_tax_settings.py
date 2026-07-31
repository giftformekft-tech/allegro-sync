from __future__ import annotations

import unittest

from allegro_app.offers import OfferService, resolve_dependent_dictionary_selections


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


class DependentParametersTest(unittest.TestCase):
    CATEGORY = {
        "parameters": [{
            "id": "216925",
            "type": "dictionary",
            "options": {"dependsOnParameterId": "54"},
            "dictionary": [
                {
                    "id": "216925_1191143",
                    "value": "klasszikus",
                    "dependsOnValueIds": ["54_4"],
                },
                {
                    "id": "216925_275825",
                    "value": "plus size (nagy méretek)",
                    "dependsOnValueIds": ["54_8"],
                },
            ],
        }],
    }

    def test_3xl_changes_classic_family_to_the_only_allowed_plus_size_value(self) -> None:
        resolved = resolve_dependent_dictionary_selections(self.CATEGORY, {
            "54": "54_8",
            "216925": "216925_1191143",
        })

        self.assertEqual("216925_275825", resolved["216925"])

    def test_regular_size_keeps_the_template_family(self) -> None:
        resolved = resolve_dependent_dictionary_selections(self.CATEGORY, {
            "54": "54_4",
            "216925": "216925_1191143",
        })

        self.assertEqual("216925_1191143", resolved["216925"])


if __name__ == "__main__":
    unittest.main()
