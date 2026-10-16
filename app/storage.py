"""SQLite persistence; raw HTML, cookies and browser storage are not persisted."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from app.models import CampaignRecord

CAMPAIGN_COLUMNS = (
    "id", "source_id", "bank_name", "title", "description", "url",
    "start_date", "end_date", "scraped_at", "content_hash",
)


class Storage:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    bank_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    start_date TEXT NOT NULL DEFAULT '',
                    end_date TEXT NOT NULL DEFAULT '',
                    scraped_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    UNIQUE(source_id, content_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_campaigns_scraped_at
                    ON campaigns(scraped_at DESC);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    sources_total INTEGER NOT NULL DEFAULT 0,
                    sources_ok INTEGER NOT NULL DEFAULT 0,
                    campaigns_found INTEGER NOT NULL DEFAULT 0,
                    campaigns_saved INTEGER NOT NULL DEFAULT 0,
                    details_json TEXT NOT NULL DEFAULT '[]'
                );
            """)

    def create_run(self, run_id: str, sources_total: int) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO runs(id, started_at, status, sources_total) VALUES(?,?,?,?)",
                (run_id, datetime.now(timezone.utc).isoformat(), "running", sources_total),
            )

    def finish_run(self, run_id: str, status: str, details: list[dict[str, Any]]) -> None:
        found = sum(int(item.get("found", 0)) for item in details)
        saved = sum(int(item.get("saved", 0)) for item in details)
        ok = sum(1 for item in details if item.get("status") == "success")
        with self.connection() as conn:
            conn.execute(
                """UPDATE runs SET finished_at=?, status=?, sources_ok=?,
                   campaigns_found=?, campaigns_saved=?, details_json=? WHERE id=?""",
                (datetime.now(timezone.utc).isoformat(), status, ok, found, saved,
                 json.dumps(details, ensure_ascii=False), run_id),
            )

    def save_campaigns(self, items: Iterable[CampaignRecord]) -> int:
        """Upsert current facts but return only the count of brand-new keys."""
        inserted = 0
        with self.connection() as conn:
            for item in items:
                existing = conn.execute(
                    "SELECT 1 FROM campaigns WHERE source_id=? AND content_hash=?",
                    (item.source_id, item.content_hash),
                ).fetchone()
                conn.execute(
                    """INSERT INTO campaigns
                    (id, source_id, bank_name, title, description, url, start_date,
                     end_date, scraped_at, content_hash)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_id, content_hash) DO UPDATE SET
                      bank_name=excluded.bank_name,
                      title=excluded.title,
                      description=excluded.description,
                      url=excluded.url,
                      start_date=excluded.start_date,
                      end_date=excluded.end_date,
                      scraped_at=excluded.scraped_at""",
                    tuple(getattr(item, column) for column in CAMPAIGN_COLUMNS),
                )
                if existing is None:
                    inserted += 1
        return inserted

    def campaigns(self, limit: int = 500, source_id: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(2000, limit))
        with self.connection() as conn:
            if source_id:
                rows = conn.execute(
                    "SELECT * FROM campaigns WHERE source_id=? ORDER BY scraped_at DESC LIMIT ?",
                    (source_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM campaigns ORDER BY scraped_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    def runs(self, limit: int = 30) -> list[dict[str, Any]]:
        limit = max(1, min(200, limit))
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json"))
            except (TypeError, json.JSONDecodeError):
                item["details"] = []
                item.pop("details_json", None)
            result.append(item)
        return result

    def stats(self) -> dict[str, int]:
        with self.connection() as conn:
            campaign_count = conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
            run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        return {"campaigns": campaign_count, "runs": run_count}

    def export_json(self) -> str:
        return json.dumps(self.campaigns(limit=2000), ensure_ascii=False, indent=2)

    def export_csv(self) -> str:
        out = io.StringIO(newline="")
        writer = csv.DictWriter(out, fieldnames=list(CAMPAIGN_COLUMNS))
        writer.writeheader()
        writer.writerows(self.campaigns(limit=2000))
        return out.getvalue()


def campaign_hash(source_id: str, title: str, url: str) -> str:
    basis = f"{source_id.strip().lower()}|{url.strip().lower() or title.strip().lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def make_campaign_id(content_hash: str) -> str:
    return content_hash[:24]
