from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back like sqlite3.Connection, then release the file."""

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL UNIQUE,
                    parent_sku TEXT NOT NULL,
                    name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    color TEXT NOT NULL,
                    size TEXT NOT NULL,
                    price_huf TEXT NOT NULL,
                    stock INTEGER NOT NULL,
                    image_url TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    brand TEXT NOT NULL DEFAULT '',
                    material TEXT NOT NULL DEFAULT '',
                    ai_content INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'draft',
                    category_id TEXT,
                    allegro_offer_id TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS import_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    total_rows INTEGER NOT NULL,
                    valid_rows INTEGER NOT NULL,
                    error_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS import_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
                    line_number INTEGER NOT NULL,
                    sku TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    valid INTEGER NOT NULL,
                    problems TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    token_type TEXT PRIMARY KEY,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    expires_at TEXT NOT NULL,
                    scope TEXT
                );
                """
            )
            self._ensure_columns(db, "products", {
                "description": "TEXT NOT NULL DEFAULT ''",
                "brand": "TEXT NOT NULL DEFAULT ''",
                "material": "TEXT NOT NULL DEFAULT ''",
                "ai_content": "INTEGER NOT NULL DEFAULT 0",
                "category_id": "TEXT",
                "allegro_offer_id": "TEXT",
            })

    @staticmethod
    def _ensure_columns(db: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def add_activity(self, kind: str, message: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO activity(kind, message, created_at) VALUES (?, ?, ?)",
                (kind, message, now_iso()),
            )

    def dashboard(self) -> dict[str, Any]:
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            ready = db.execute("SELECT COUNT(*) FROM products WHERE status = 'ready'").fetchone()[0]
            drafts = db.execute("SELECT COUNT(*) FROM products WHERE status = 'draft'").fetchone()[0]
            stock = db.execute("SELECT COALESCE(SUM(stock), 0) FROM products").fetchone()[0]
            last_import = db.execute(
                "SELECT * FROM import_batches ORDER BY id DESC LIMIT 1"
            ).fetchone()
            activity = db.execute(
                "SELECT kind, message, created_at FROM activity ORDER BY id DESC LIMIT 7"
            ).fetchall()
        return {
            "stats": {"products": total, "ready": ready, "drafts": drafts, "stock": stock, "orders": 0},
            "last_import": dict(last_import) if last_import else None,
            "activity": [dict(row) for row in activity],
        }

    def create_preview(self, filename: str, rows: list[dict[str, Any]]) -> int:
        valid = sum(1 for row in rows if not row["problems"])
        errors = sum(len(row["problems"]) for row in rows)
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO import_batches
                (filename, total_rows, valid_rows, error_count, status, created_at)
                VALUES (?, ?, ?, ?, 'preview', ?)""",
                (filename, len(rows), valid, errors, now_iso()),
            )
            import_id = int(cursor.lastrowid)
            db.executemany(
                """INSERT INTO import_rows
                (import_id, line_number, sku, payload, valid, problems)
                VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        import_id,
                        row["line"],
                        row["sku"],
                        json.dumps(row, ensure_ascii=False),
                        0 if row["problems"] else 1,
                        json.dumps(row["problems"], ensure_ascii=False),
                    )
                    for row in rows
                ],
            )
        return import_id

    def commit_import(self, import_id: int) -> int:
        with self.connect() as db:
            batch = db.execute(
                "SELECT * FROM import_batches WHERE id = ?", (import_id,)
            ).fetchone()
            if batch is None:
                raise ValueError("Az import-előnézet nem található.")
            if batch["status"] == "committed":
                return int(batch["valid_rows"])
            rows = db.execute(
                "SELECT payload FROM import_rows WHERE import_id = ? AND valid = 1", (import_id,)
            ).fetchall()
            for record in rows:
                row = json.loads(record["payload"])
                db.execute(
                    """INSERT INTO products
                    (sku, parent_sku, name, title, type, color, size, price_huf, stock, image_url,
                     description, brand, material, ai_content, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
                    ON CONFLICT(sku) DO UPDATE SET
                      parent_sku=excluded.parent_sku, name=excluded.name, title=excluded.title,
                      type=excluded.type, color=excluded.color, size=excluded.size,
                      price_huf=excluded.price_huf, stock=excluded.stock,
                      image_url=excluded.image_url, description=excluded.description,
                      brand=excluded.brand, material=excluded.material, ai_content=excluded.ai_content,
                      updated_at=excluded.updated_at""",
                    (
                        row["sku"], row["parent_sku"], row["name"], row["title"], row["type"],
                        row["color"], row["size"], row["price_huf"], row["stock"],
                        row["image_url"], row.get("description", ""), row.get("brand", ""),
                        row.get("material", ""), 1 if row.get("ai_content") else 0, now_iso(),
                    ),
                )
            db.execute("UPDATE import_batches SET status = 'committed' WHERE id = ?", (import_id,))
            count = len(rows)
        self.add_activity("import", f"{count} termékváltozat importálva: {batch['filename']}")
        return count

    def list_products(self, search: str = "") -> list[dict[str, Any]]:
        with self.connect() as db:
            if search:
                needle = f"%{search}%"
                rows = db.execute(
                    """SELECT * FROM products WHERE sku LIKE ? OR name LIKE ? OR title LIKE ?
                    ORDER BY updated_at DESC LIMIT 250""",
                    (needle, needle, needle),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM products ORDER BY updated_at DESC LIMIT 250").fetchall()
        return [dict(row) for row in rows]

    def get_product(self, product_id: int) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            raise ValueError("A kiválasztott termék nem található.")
        return dict(row)

    def mark_offer_created(self, product_id: int, category_id: str, offer_id: str | None) -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE products SET status = 'inactive', category_id = ?, allegro_offer_id = ?,
                updated_at = ? WHERE id = ?""",
                (category_id, offer_id, now_iso(), product_id),
            )
        label = offer_id or "feldolgozás alatt"
        self.add_activity("upload", f"Inaktív Allegro tesztajánlat létrehozva: {label}")

    def save_token(self, token_type: str, access: str, refresh: str | None, expires_at: str, scope: str | None) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO oauth_tokens(token_type, access_token, refresh_token, expires_at, scope)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(token_type) DO UPDATE SET access_token=excluded.access_token,
                refresh_token=excluded.refresh_token, expires_at=excluded.expires_at, scope=excluded.scope""",
                (token_type, access, refresh, expires_at, scope),
            )

    def get_token(self, token_type: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM oauth_tokens WHERE token_type = ?", (token_type,)).fetchone()
        return dict(row) if row else None

    def has_user_token(self) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM oauth_tokens WHERE token_type = 'user'").fetchone() is not None
