from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


ENV_KEYS = (
    "ALLEGRO_ENV",
    "ALLEGRO_CLIENT_ID",
    "ALLEGRO_CLIENT_SECRET",
    "ALLEGRO_USER_AGENT",
    "ALLEGRO_LANGUAGE",
    "ALLEGRO_RATE_LIMIT_PER_MINUTE",
    "INVOICE_DRIVER",
    "SZAMLAZZ_AGENT_KEY",
    "SZAMLAZZ_INVOICE_PREFIX",
    "SZAMLAZZ_SEND_EMAIL",
)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


@dataclass(slots=True)
class AppConfig:
    root: Path
    values: dict[str, str]

    @classmethod
    def load(cls, root: Path) -> "AppConfig":
        values = {
            "ALLEGRO_ENV": "sandbox",
            "ALLEGRO_LANGUAGE": "hu-HU",
            "ALLEGRO_RATE_LIMIT_PER_MINUTE": "4000",
            "INVOICE_DRIVER": "none",
            "SZAMLAZZ_SEND_EMAIL": "false",
        }
        source = root / ".env"
        if not source.exists():
            source = root / ".env.example"
        if source.exists():
            for raw_line in source.read_text(encoding="utf-8-sig").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key in ENV_KEYS:
                    values[key] = _unquote(value)
        return cls(root=root, values=values)

    @property
    def environment(self) -> str:
        return self.values.get("ALLEGRO_ENV", "sandbox")

    @property
    def api_base(self) -> str:
        if self.environment == "production":
            return "https://api.allegro.pl"
        return "https://api.allegro.pl.allegrosandbox.pl"

    @property
    def auth_base(self) -> str:
        if self.environment == "production":
            return "https://allegro.pl/auth/oauth"
        return "https://allegro.pl.allegrosandbox.pl/auth/oauth"

    @property
    def state_path(self) -> Path:
        return self.root / "var" / f"app-state-{self.environment}.sqlite"

    def public_values(self) -> dict[str, str | bool]:
        return {
            "environment": self.environment,
            "client_id": self.values.get("ALLEGRO_CLIENT_ID", ""),
            "client_secret_set": bool(self.values.get("ALLEGRO_CLIENT_SECRET", "")),
            "user_agent": self.values.get("ALLEGRO_USER_AGENT", ""),
            "language": self.values.get("ALLEGRO_LANGUAGE", "hu-HU"),
            "invoice_driver": self.values.get("INVOICE_DRIVER", "none"),
            "szamlazz_agent_key_set": bool(self.values.get("SZAMLAZZ_AGENT_KEY", "")),
            "invoice_prefix": self.values.get("SZAMLAZZ_INVOICE_PREFIX", ""),
            "invoice_email_fallback": self.values.get("SZAMLAZZ_SEND_EMAIL", "false").lower() == "true",
            "invoice_ready": (
                self.values.get("INVOICE_DRIVER") == "szamlazz"
                and bool(self.values.get("SZAMLAZZ_AGENT_KEY", ""))
            ),
        }

    def validation(self) -> list[str]:
        problems: list[str] = []
        if self.environment not in {"sandbox", "production"}:
            problems.append("Az Allegro környezet csak sandbox vagy production lehet.")
        if not self.values.get("ALLEGRO_CLIENT_ID"):
            problems.append("Hiányzik az Allegro Client ID.")
        if not self.values.get("ALLEGRO_CLIENT_SECRET"):
            problems.append("Hiányzik az Allegro Client Secret.")
        user_agent = self.values.get("ALLEGRO_USER_AGENT", "")
        if not re.match(r"^\S+/\S+ \(\+https://[^)]+\)$", user_agent):
            problems.append("A User-Agent formátuma: Nev/Verzio (+https://elerheto-url)")
        return problems

    def save(self, updates: dict[str, str]) -> None:
        env_path = self.root / ".env"
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        existing: dict[str, int] = {}
        for index, line in enumerate(lines):
            if "=" in line and not line.lstrip().startswith("#"):
                existing[line.split("=", 1)[0].strip()] = index

        for key, value in updates.items():
            if key not in ENV_KEYS:
                continue
            value = str(value).replace("\r", "").replace("\n", "").strip()
            rendered = f'{key}="{value.replace(chr(34), chr(92) + chr(34))}"'
            if key in existing:
                lines[existing[key]] = rendered
            else:
                lines.append(rendered)

        env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        self.values.update(updates)
