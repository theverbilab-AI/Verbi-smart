"""
CARE Database Layer — PostgreSQL-first, SQLite-compatible
=========================================================

Use this as: care-backend/database.py

Fixes included:
- Railway uses PostgreSQL automatically when DATABASE_URL exists.
- SQLite is only a local fallback.
- psycopg2 connection works with the same conn.execute(...) style used by the app.
- JSON/list/dict values are safely serialized before DB writes.
- Boolean fields work in both PostgreSQL and SQLite.
- Missing columns are auto-migrated.
- Adds PRD fields: disposition, dispositions, AI detection/suggestion, risk level, loan/agent analytics fields.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

try:
    import bcrypt
except Exception:  # local dev fallback
    bcrypt = None

try:
    import psycopg2
    import psycopg2.extras
except Exception:  # local SQLite-only fallback
    psycopg2 = None

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "care.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_TYPE = "postgres" if DATABASE_URL else os.getenv("DB_TYPE", "sqlite").strip().lower()

JSON_FIELDS = {
    "scores_breakdown",
    "compliance_flags",
    "key_issues",
    "strengths",
    "ai_detection",
    "risk_flags",
    "analysis",
    "dispositions",
    "sentiment_timeline",
}

BOOL_FIELDS = {
    "ptp_detected",
    "critical_fail",
    "is_active",
    "auto_sync",
}

CALL_COLUMNS = [
    "id", "org_id", "filename", "file_path", "file_size", "agent_id", "agent_name",
    "campaign_id", "loan_id", "customer_id", "source", "source_uri", "status",
    "score", "score_pct", "confidence_pct", "confidence", "scores_breakdown",
    "compliance_flags", "ptp_detected", "ptp_amount", "ptp_date", "ptp_mode",
    "agent_sentiment", "sentiment_notes", "summary", "key_issues", "strengths",
    "coaching_tip", "transcript", "agent_transcript", "customer_transcript",
    "analysis", "grade", "sentiment", "risk_flags", "critical_fail",
    "critical_reason", "final_status", "disposition", "dispositions", "risk_level",
    "ai_detection", "ai_suggestion", "error", "uploaded_at", "processed_at",
]


class PgConn:
    """Tiny psycopg2 wrapper so existing conn.execute(...) code keeps working."""

    def __init__(self, raw):
        self.raw = raw

    def _convert_query(self, query: str, params: Any = None) -> str:
        # Convert named SQLite style :name to psycopg2 %(name)s
        if isinstance(params, dict):
            query = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", query)
        else:
            query = query.replace("?", "%s")
        # SQLite-specific insert syntax to Postgres syntax.
        query = query.replace("INSERT OR IGNORE", "INSERT")
        query = query.replace("INSERT OR REPLACE", "INSERT")
        return query

    def execute(self, query: str, params: Any = None):
        cur = self.raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        q = self._convert_query(query, params)
        cur.execute(q, params)
        return cur

    def executemany(self, query: str, seq_params: Iterable[Any]):
        cur = self.raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        q = self._convert_query(query, None)
        cur.executemany(q, seq_params)
        return cur

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


@contextmanager
def get_conn():
    """Return a DB connection. Railway/prod uses PostgreSQL when DATABASE_URL exists."""
    if DB_TYPE == "postgres":
        if not DATABASE_URL:
            raise RuntimeError("DB_TYPE=postgres but DATABASE_URL is missing")
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is not installed. Add psycopg2-binary to requirements.txt")
        raw = psycopg2.connect(DATABASE_URL, connect_timeout=5)
        conn = PgConn(raw)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any, default: Any = None) -> str:
    if value is None:
        value = [] if default is None else default
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _clean_value(key: str, value: Any) -> Any:
    if key in JSON_FIELDS:
        return _json(value, {} if key in {"scores_breakdown", "analysis"} else [])
    if key in BOOL_FIELDS:
        return bool(value) if DB_TYPE == "postgres" else (1 if value else 0)
    return value


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for key in JSON_FIELDS:
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                d[key] = {} if key in {"scores_breakdown", "analysis"} else []
    for key in BOOL_FIELDS:
        if key in d and d[key] is not None:
            d[key] = bool(d[key])
    return d


def _table_columns(conn, table: str) -> set[str]:
    if DB_TYPE == "postgres":
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table,),
        ).fetchall()
        return {r["column_name"] for r in rows}
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _add_column(conn, table: str, name: str, sqlite_type: str, pg_type: str | None = None):
    cols = _table_columns(conn, table)
    if name not in cols:
        col_type = pg_type or sqlite_type
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")
        print(f"[DB] Migrated {table}: added {name}", flush=True)


def init_db():
    """Create/migrate database schema."""
    if DB_TYPE == "postgres":
        _init_postgres()
        print("[DB] ✓ PostgreSQL initialised", flush=True)
    else:
        _init_sqlite()
        print(f"[DB] ✓ SQLite initialized at {DB_PATH}", flush=True)


def _init_sqlite():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS organisations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL DEFAULT 'org_default',
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            name TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL DEFAULT 'org_default',
            filename TEXT,
            file_path TEXT,
            file_size INTEGER,
            agent_id TEXT,
            agent_name TEXT,
            campaign_id TEXT,
            loan_id TEXT,
            customer_id TEXT,
            source TEXT DEFAULT 'upload',
            source_uri TEXT,
            status TEXT DEFAULT 'queued',
            score REAL,
            score_pct REAL,
            confidence_pct INTEGER DEFAULT 0,
            confidence INTEGER DEFAULT 80,
            scores_breakdown TEXT DEFAULT '{}',
            compliance_flags TEXT DEFAULT '[]',
            ptp_detected INTEGER DEFAULT 0,
            ptp_amount TEXT,
            ptp_date TEXT,
            ptp_mode TEXT,
            agent_sentiment TEXT,
            sentiment_notes TEXT,
            summary TEXT,
            key_issues TEXT DEFAULT '[]',
            strengths TEXT DEFAULT '[]',
            coaching_tip TEXT,
            transcript TEXT,
            agent_transcript TEXT,
            customer_transcript TEXT,
            analysis TEXT DEFAULT '{}',
            grade TEXT,
            sentiment TEXT,
            risk_flags TEXT DEFAULT '[]',
            critical_fail INTEGER DEFAULT 0,
            critical_reason TEXT,
            final_status TEXT,
            disposition TEXT,
            dispositions TEXT DEFAULT '[]',
            risk_level TEXT,
            ai_detection TEXT DEFAULT '[]',
            ai_suggestion TEXT,
            error TEXT,
            uploaded_at TEXT DEFAULT (datetime('now')),
            processed_at TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS drive_configs (
            id TEXT PRIMARY KEY,
            org_id TEXT UNIQUE NOT NULL,
            folder_url TEXT,
            folder_id TEXT,
            auto_sync INTEGER DEFAULT 0,
            last_synced TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)
        _seed_defaults(conn)
        _migrate_common(conn)


def _init_postgres():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS organisations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL DEFAULT 'org_default',
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            name TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL DEFAULT 'org_default',
            filename TEXT,
            file_path TEXT,
            file_size BIGINT,
            agent_id TEXT,
            agent_name TEXT,
            campaign_id TEXT,
            loan_id TEXT,
            customer_id TEXT,
            source TEXT DEFAULT 'upload',
            source_uri TEXT,
            status TEXT DEFAULT 'queued',
            score REAL,
            score_pct REAL,
            confidence_pct INTEGER DEFAULT 0,
            confidence INTEGER DEFAULT 80,
            scores_breakdown JSONB DEFAULT '{}'::jsonb,
            compliance_flags JSONB DEFAULT '[]'::jsonb,
            ptp_detected BOOLEAN DEFAULT FALSE,
            ptp_amount TEXT,
            ptp_date TEXT,
            ptp_mode TEXT,
            agent_sentiment TEXT,
            sentiment_notes TEXT,
            summary TEXT,
            key_issues JSONB DEFAULT '[]'::jsonb,
            strengths JSONB DEFAULT '[]'::jsonb,
            coaching_tip TEXT,
            transcript TEXT,
            agent_transcript TEXT,
            customer_transcript TEXT,
            analysis JSONB DEFAULT '{}'::jsonb,
            grade TEXT,
            sentiment TEXT,
            risk_flags JSONB DEFAULT '[]'::jsonb,
            critical_fail BOOLEAN DEFAULT FALSE,
            critical_reason TEXT,
            final_status TEXT,
            disposition TEXT,
            dispositions JSONB DEFAULT '[]'::jsonb,
            risk_level TEXT,
            ai_detection JSONB DEFAULT '[]'::jsonb,
            ai_suggestion TEXT,
            error TEXT,
            uploaded_at TIMESTAMPTZ DEFAULT now(),
            processed_at TIMESTAMPTZ
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS drive_configs (
            id TEXT PRIMARY KEY,
            org_id TEXT UNIQUE NOT NULL,
            folder_url TEXT,
            folder_id TEXT,
            auto_sync BOOLEAN DEFAULT FALSE,
            last_synced TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_org_uploaded ON calls(org_id, uploaded_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_loan ON calls(loan_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_agent ON calls(agent_id)")
        _seed_defaults(conn)
        _migrate_common(conn)


def _seed_defaults(conn):
    conn.execute(
        """
        INSERT INTO organisations (id, name, slug)
        VALUES (:id, :name, :slug)
        ON CONFLICT (id) DO NOTHING
        """,
        {"id": "org_default", "name": "Company Finance", "slug": "company-finance"},
    )

    admin_hash = "care@2025"
    if bcrypt:
        try:
            admin_hash = bcrypt.hashpw(b"care@2025", bcrypt.gensalt()).decode("utf-8")
        except Exception:
            pass

    conn.execute(
        """
        INSERT INTO users (id, org_id, email, password_hash, role, name, is_active)
        VALUES (:id, :org_id, :email, :password_hash, :role, :name, :is_active)
        ON CONFLICT (id) DO NOTHING
        """,
        {
            "id": "user_admin",
            "org_id": "org_default",
            "email": "admin@care.ai",
            "password_hash": admin_hash,
            "role": "super_admin",
            "name": "QA Manager",
            "is_active": True if DB_TYPE == "postgres" else 1,
        },
    )


def _migrate_common(conn):
    additions = [
        ("calls", "agent_name", "TEXT", "TEXT"),
        ("calls", "customer_id", "TEXT", "TEXT"),
        ("calls", "confidence_pct", "INTEGER DEFAULT 0", "INTEGER DEFAULT 0"),
        ("calls", "confidence", "INTEGER DEFAULT 80", "INTEGER DEFAULT 80"),
        ("calls", "agent_transcript", "TEXT", "TEXT"),
        ("calls", "customer_transcript", "TEXT", "TEXT"),
        ("calls", "analysis", "TEXT DEFAULT '{}'", "JSONB DEFAULT '{}'::jsonb"),
        ("calls", "grade", "TEXT", "TEXT"),
        ("calls", "sentiment", "TEXT", "TEXT"),
        ("calls", "risk_flags", "TEXT DEFAULT '[]'", "JSONB DEFAULT '[]'::jsonb"),
        ("calls", "critical_fail", "INTEGER DEFAULT 0", "BOOLEAN DEFAULT FALSE"),
        ("calls", "critical_reason", "TEXT", "TEXT"),
        ("calls", "final_status", "TEXT", "TEXT"),
        ("calls", "disposition", "TEXT", "TEXT"),
        ("calls", "dispositions", "TEXT DEFAULT '[]'", "JSONB DEFAULT '[]'::jsonb"),
        ("calls", "risk_level", "TEXT", "TEXT"),
        ("calls", "ai_detection", "TEXT DEFAULT '[]'", "JSONB DEFAULT '[]'::jsonb"),
        ("calls", "ai_suggestion", "TEXT", "TEXT"),
    ]
    for table, name, sqlite_type, pg_type in additions:
        try:
            _add_column(conn, table, name, sqlite_type, pg_type if DB_TYPE == "postgres" else sqlite_type)
        except Exception as e:
            print(f"[DB] Migration skip {table}.{name}: {e}", flush=True)


# ── Call CRUD ────────────────────────────────────────────────────────────────

def save_call(call: dict):
    """Insert or update call record."""
    data = {col: _clean_value(col, call.get(col)) for col in CALL_COLUMNS}
    data["id"] = data["id"] or call.get("call_id")
    data["org_id"] = data["org_id"] or "org_default"
    data["source"] = data["source"] or "upload"
    data["status"] = data["status"] or "queued"
    data["uploaded_at"] = data["uploaded_at"] or now_iso()

    cols = [c for c in CALL_COLUMNS if c in data]
    placeholders = ", ".join(f":{c}" for c in cols)
    col_sql = ", ".join(cols)
    update_sql = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "id")

    with get_conn() as conn:
        if DB_TYPE == "postgres":
            conn.execute(
                f"INSERT INTO calls ({col_sql}) VALUES ({placeholders}) ON CONFLICT (id) DO UPDATE SET {update_sql}",
                {c: data[c] for c in cols},
            )
        else:
            conn.execute(
                f"INSERT OR REPLACE INTO calls ({col_sql}) VALUES ({placeholders})",
                {c: data[c] for c in cols},
            )


def update_call(call_id: str, fields: dict):
    """Update specific fields safely."""
    if not fields:
        return
    clean = {k: _clean_value(k, v) for k, v in fields.items() if k not in {"id", "call_id"}}
    if not clean:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in clean)
    clean["call_id"] = call_id
    with get_conn() as conn:
        conn.execute(f"UPDATE calls SET {set_clause} WHERE id = :call_id", clean)


def get_call(call_id: str, org_id: str | None = None) -> dict | None:
    with get_conn() as conn:
        if org_id:
            row = conn.execute("SELECT * FROM calls WHERE id=? AND org_id=?", (call_id, org_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
    return _row_to_dict(row)


def list_calls(
    org_id: str = "org_default",
    date_from: str | None = None,
    date_to: str | None = None,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    query = "SELECT * FROM calls WHERE org_id=?"
    params: list[Any] = [org_id]
    if date_from:
        query += " AND uploaded_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND uploaded_at <= ?"
        params.append(date_to + "T23:59:59")
    if agent_id:
        query += " AND agent_id=?"
        params.append(agent_id)
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY uploaded_at DESC LIMIT ?"
    params.append(int(limit))
    with get_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [_row_to_dict(r) for r in rows]


def mark_call_failed(call_id: str, error: str):
    update_call(call_id, {"status": "failed", "error": error, "processed_at": now_iso()})


def mark_call_processed(call_id: str, fields: dict | None = None):
    payload = {"status": "processed", "processed_at": now_iso()}
    if fields:
        payload.update(fields)
    update_call(call_id, payload)


# ── Dashboard / Analytics ────────────────────────────────────────────────────

def get_dashboard_stats(org_id: str = "org_default") -> dict:
    calls = list_calls(org_id=org_id, limit=1000)
    total = len(calls)
    processed = [c for c in calls if c.get("status") == "processed"]
    flags = sum(len(c.get("compliance_flags") or []) for c in calls)
    avg_score = round(sum(float(c.get("score_pct") or 0) for c in processed) / max(len(processed), 1), 1)
    ptp_count = sum(1 for c in calls if c.get("ptp_detected"))

    disposition_counts: dict[str, int] = {}
    agent_stats: dict[str, dict] = {}
    loan_stats: dict[str, dict] = {}

    for c in calls:
        dispositions = c.get("dispositions") or []
        if not dispositions and c.get("disposition"):
            dispositions = [c.get("disposition")]
        if not dispositions:
            dispositions = ["Other"]
        for d in dispositions:
            disposition_counts[str(d)] = disposition_counts.get(str(d), 0) + 1

        agent = c.get("agent_name") or c.get("agent_id") or "Unknown"
        a = agent_stats.setdefault(agent, {"agent": agent, "calls": 0, "score_sum": 0, "flags": 0, "ptp": 0})
        a["calls"] += 1
        a["score_sum"] += float(c.get("score_pct") or 0)
        a["flags"] += len(c.get("compliance_flags") or [])
        a["ptp"] += 1 if c.get("ptp_detected") else 0

        loan = c.get("loan_id") or "Unknown"
        l = loan_stats.setdefault(loan, {"loan_id": loan, "calls": 0, "agents": set(), "ptp": 0, "flags": 0})
        l["calls"] += 1
        l["agents"].add(agent)
        l["ptp"] += 1 if c.get("ptp_detected") else 0
        l["flags"] += len(c.get("compliance_flags") or [])

    agent_rows = []
    for a in agent_stats.values():
        agent_rows.append({
            "agent": a["agent"],
            "calls": a["calls"],
            "avg_score": round(a["score_sum"] / max(a["calls"], 1), 1),
            "flags": a["flags"],
            "ptp_rate": round((a["ptp"] / max(a["calls"], 1)) * 100, 1),
        })

    loan_rows = []
    for l in loan_stats.values():
        loan_rows.append({
            "loan_id": l["loan_id"],
            "calls": l["calls"],
            "agents_involved": len(l["agents"]),
            "ptp_count": l["ptp"],
            "compliance_flags": l["flags"],
        })

    return {
        "total_calls": total,
        "processed_calls": len(processed),
        "processed_pct": round((len(processed) / max(total, 1)) * 100, 1),
        "avg_score": avg_score,
        "ptp_count": ptp_count,
        "ptp_rate": round((ptp_count / max(total, 1)) * 100, 1),
        "compliance_flags": flags,
        "disposition_counts": disposition_counts,
        "agent_performance": sorted(agent_rows, key=lambda x: x["calls"], reverse=True),
        "loan_analytics": sorted(loan_rows, key=lambda x: x["calls"], reverse=True),
        "recent_calls": calls[:20],
    }


# ── User / Auth ──────────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE lower(email)=lower(?) AND is_active=true", (email,)).fetchone() if DB_TYPE == "postgres" else conn.execute("SELECT * FROM users WHERE lower(email)=lower(?) AND is_active=1", (email,)).fetchone()
    return _row_to_dict(row)


def get_user_by_id(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _row_to_dict(row)


def create_user(user_id: str, org_id: str, email: str, password_hash: str, role: str, name: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (id, org_id, email, password_hash, role, name, is_active)
            VALUES (:id, :org_id, :email, :password_hash, :role, :name, :is_active)
            """,
            {
                "id": user_id,
                "org_id": org_id,
                "email": email,
                "password_hash": password_hash,
                "role": role,
                "name": name,
                "is_active": True if DB_TYPE == "postgres" else 1,
            },
        )


# ── Drive Config ─────────────────────────────────────────────────────────────

def get_drive_config(org_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM drive_configs WHERE org_id=?", (org_id,)).fetchone()
    return _row_to_dict(row)


def save_drive_config(org_id: str, folder_url: str, folder_id: str, auto_sync: bool = False):
    payload = {
        "id": f"dc_{org_id}",
        "org_id": org_id,
        "folder_url": folder_url,
        "folder_id": folder_id,
        "auto_sync": True if DB_TYPE == "postgres" else (1 if auto_sync else 0),
    }
    with get_conn() as conn:
        if DB_TYPE == "postgres":
            conn.execute(
                """
                INSERT INTO drive_configs (id, org_id, folder_url, folder_id, auto_sync)
                VALUES (:id, :org_id, :folder_url, :folder_id, :auto_sync)
                ON CONFLICT (org_id) DO UPDATE SET
                    folder_url = EXCLUDED.folder_url,
                    folder_id = EXCLUDED.folder_id,
                    auto_sync = EXCLUDED.auto_sync
                """,
                payload,
            )
        else:
            conn.execute(
                """
                INSERT OR REPLACE INTO drive_configs (id, org_id, folder_url, folder_id, auto_sync)
                VALUES (:id, :org_id, :folder_url, :folder_id, :auto_sync)
                """,
                payload,
            )


def update_drive_last_synced(org_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE drive_configs SET last_synced=? WHERE org_id=?",
            (now_iso(), org_id),
        )


if __name__ == "__main__":
    init_db()
    print(json.dumps(get_dashboard_stats(), indent=2, default=str))
