"""Durable request journal; contains no authoritative inventory balances."""
import json
import sqlite3
from contextlib import contextmanager

from .sheets import Problem


class Journal:
    def __init__(self, path, identity):
        self.path = path
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS config (identity TEXT NOT NULL)")
            old = db.execute("SELECT identity FROM config").fetchone()
            if old and old[0] != identity:
                raise Problem("State directory belongs to another workbook. Resolve its pending work before using a separate directory.", 503)
            if not old:
                db.execute("INSERT INTO config VALUES (?)", (identity,))
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
                evidence TEXT NOT NULL, receipt TEXT, created INTEGER NOT NULL)""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, rid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
            return dict(row) if row else None

    def intent(self, rid, payload, evidence):
        with self.connect() as db:
            db.execute("""INSERT INTO requests VALUES (?, ?, 'sending', ?, NULL, unixepoch())
                ON CONFLICT(id) DO UPDATE SET state='sending', evidence=excluded.evidence""",
                (rid, payload, json.dumps(evidence)))

    def state(self, rid, state, receipt=None):
        with self.connect() as db:
            db.execute("UPDATE requests SET state=?, receipt=? WHERE id=?",
                       (state, json.dumps(receipt) if receipt else None, rid))

    def unresolved(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM requests WHERE state IN ('sending','pending','saved_unverified') ORDER BY created")]

    def recent(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT receipt FROM requests WHERE state='verified' ORDER BY created DESC, rowid DESC LIMIT 10")]
