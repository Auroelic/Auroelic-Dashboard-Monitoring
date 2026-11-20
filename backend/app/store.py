import json
import sqlite3
import threading
import time

from .schemas import Thresholds

RANGES = {"5m": 300, "1h": 3600, "6h": 21600, "24h": 86400}


class Store:
    def __init__(self, path, retention_hours):
        self.retention = retention_hours * 3600
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS samples(ts REAL PRIMARY KEY, cpu REAL, mem REAL, disk REAL, rx REAL, tx REAL);
                CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, metric TEXT,
                    severity TEXT, value REAL, threshold REAL, message TEXT, cause TEXT, resolved_ts REAL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
                """
            )

    def _q(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()]
            self.db.commit()
            return rows, cur.lastrowid

    def add_sample(self, ts, cpu, mem, disk, rx, tx):
        self._q("INSERT OR REPLACE INTO samples VALUES(?,?,?,?,?,?)", (ts, cpu, mem, disk, rx, tx))

    def prune(self):
        self._q("DELETE FROM samples WHERE ts<?", (time.time() - self.retention,))

    def history(self, seconds, points=240):
        bucket = max(1, seconds // points)
        rows, _ = self._q(
            "SELECT (CAST(ts AS INTEGER)/?)*? AS t, AVG(cpu) cpu, AVG(mem) mem, AVG(disk) disk, AVG(rx) rx, AVG(tx) tx "
            "FROM samples WHERE ts>=? GROUP BY t ORDER BY t",
            (bucket, bucket, time.time() - seconds),
        )
        return [{k: (round(v, 2) if k != "t" else v) for k, v in r.items()} for r in rows]

    def get_thresholds(self):
        rows, _ = self._q("SELECT value FROM settings WHERE key='thresholds'")
        data = json.loads(rows[0]["value"]) if rows else {}
        return Thresholds(**data).model_dump()

    def set_thresholds(self, t: Thresholds):
        self._q("INSERT OR REPLACE INTO settings VALUES('thresholds',?)", (json.dumps(t.model_dump()),))

    def add_alert(self, ts, metric, severity, value, threshold, message, cause):
        _, rid = self._q(
            "INSERT INTO alerts(ts,metric,severity,value,threshold,message,cause) VALUES(?,?,?,?,?,?,?)",
            (ts, metric, severity, value, threshold, message, cause),
        )
        return {"id": rid, "ts": ts, "metric": metric, "severity": severity, "value": value,
                "threshold": threshold, "message": message, "cause": cause, "resolved_ts": None}

    def resolve_alert(self, aid, ts):
        self._q("UPDATE alerts SET resolved_ts=? WHERE id=?", (ts, aid))

    def alerts(self, status="all", limit=30):
        where = {"open": "WHERE resolved_ts IS NULL", "resolved": "WHERE resolved_ts IS NOT NULL"}.get(status, "")
        rows, _ = self._q(f"SELECT * FROM alerts {where} ORDER BY ts DESC LIMIT ?", (limit,))
        return rows
