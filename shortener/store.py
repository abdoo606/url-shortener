"""Persistence. A short link is unique per (url) so re-shortening is idempotent."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .urls import generate_code

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    code       TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    created_at TEXT NOT NULL,
    clicks     INTEGER NOT NULL DEFAULT 0,
    owner      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_links_url ON links(url);
CREATE TABLE IF NOT EXISTS visits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL REFERENCES links(code) ON DELETE CASCADE,
    at         TEXT NOT NULL,
    referrer   TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_visits_code ON visits(code);
"""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True, frozen=True)
class Link:
    code: str
    url: str
    created_at: str
    clicks: int
    owner: str | None


class LinkStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create(self, url: str, *, owner: str | None = None, code: str | None = None) -> Link:
        existing = self.get_by_url(url)
        if existing:
            return existing
        for _ in range(10):
            candidate = code or generate_code()
            try:
                self._conn.execute(
                    "INSERT INTO links (code, url, created_at, owner) VALUES (?,?,?,?)",
                    (candidate, url, _now(), owner),
                )
                self._conn.commit()
                return self.get(candidate)  # type: ignore[return-value]
            except sqlite3.IntegrityError:
                if code:
                    raise ValueError(f"code {code!r} is already taken") from None
                continue  # astronomically rare collision: draw again
        raise RuntimeError("could not allocate a unique code")

    def get(self, code: str) -> Link | None:
        row = self._conn.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
        return Link(row["code"], row["url"], row["created_at"], row["clicks"], row["owner"]) if row else None

    def get_by_url(self, url: str) -> Link | None:
        row = self._conn.execute("SELECT * FROM links WHERE url = ?", (url,)).fetchone()
        return Link(row["code"], row["url"], row["created_at"], row["clicks"], row["owner"]) if row else None

    def record_visit(self, code: str, *, referrer: str | None = None, user_agent: str | None = None) -> None:
        with self._conn:
            self._conn.execute("UPDATE links SET clicks = clicks + 1 WHERE code = ?", (code,))
            self._conn.execute(
                "INSERT INTO visits (code, at, referrer, user_agent) VALUES (?,?,?,?)",
                (code, _now(), referrer, user_agent),
            )

    def stats(self, code: str) -> dict[str, object] | None:
        link = self.get(code)
        if link is None:
            return None
        rows = self._conn.execute(
            "SELECT referrer, COUNT(*) AS n FROM visits WHERE code = ? GROUP BY referrer", (code,)
        ).fetchall()
        return {
            "code": link.code,
            "url": link.url,
            "clicks": link.clicks,
            "created_at": link.created_at,
            "referrers": {(r["referrer"] or "direct"): r["n"] for r in rows},
        }

    def top(self, limit: int = 10) -> list[Link]:
        rows = self._conn.execute(
            "SELECT * FROM links ORDER BY clicks DESC, created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Link(r["code"], r["url"], r["created_at"], r["clicks"], r["owner"]) for r in rows]

    def delete(self, code: str) -> bool:
        with self._conn:
            cur = self._conn.execute("DELETE FROM links WHERE code = ?", (code,))
        return cur.rowcount > 0
