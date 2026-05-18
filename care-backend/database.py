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

# (table, column) -> information_schema data_type e.g. "boolean" | "integer"
BOOL_COLUMN_TYPES: dict[tuple[str, str], str] = {}

# PostgreSQL BOOLEAN columns on calls — cast in SQL so 1/0 still works if old code is deployed.
CALL_PG_BOOL_CAST = {"critical_fail", "ptp_detected"}

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
        stripped = value.strip()
        if stripped and stripped[0] in "[{":
            return value
        return value
    return json.dumps(value, ensure_ascii=False)


def _pg_json(value: Any, default: Any = None):
    """PostgreSQL JSONB adapter — avoids 'type list is not supported' binding errors."""
    if DB_TYPE != "postgres" or psycopg2 is None:
        return _json(value, default)
    if value is None:
        value = default if default is not None else []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            value = default if default is not None else []
        else:
            try:
                value = json.loads(stripped)
            except Exception:
                pass
    return psycopg2.extras.Json(value)


def _bool_db(value: Any) -> int:
    """1/0 storage — works for SQLite INTEGER and legacy Postgres INTEGER bool columns."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    if isinstance(value, str):
        return 1 if value.strip().lower() in {"1", "true", "yes", "t"} else 0
    return 1 if value else 0


def _refresh_bool_column_types(conn) -> None:
    """Detect whether bool columns are BOOLEAN or legacy INTEGER on this Postgres instance."""
    global BOOL_COLUMN_TYPES
    if DB_TYPE != "postgres":
        BOOL_COLUMN_TYPES = {}
        return
    rows = conn.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_name IN ('ptp_detected', 'critical_fail', 'is_active', 'auto_sync')
        """,
    ).fetchall()
    BOOL_COLUMN_TYPES = {(r["table_name"], r["column_name"]): r["data_type"] for r in rows}
    print(f"[DB] Bool column types loaded: {BOOL_COLUMN_TYPES}", flush=True)


def _clean_bool_value(key: str, value: Any, table: str = "calls") -> Any:
    """Use bool for PostgreSQL BOOLEAN columns and 1/0 for INTEGER legacy columns."""
    if DB_TYPE != "postgres":
        return _bool_db(value)
    # RDS calls table uses BOOLEAN for these — never send 1/0 (causes PG type error).
    if table == "calls" and key in {"ptp_detected", "critical_fail"}:
        return bool(_bool_db(value))
    col_type = BOOL_COLUMN_TYPES.get((table, key))
    if col_type == "boolean":
        return bool(_bool_db(value))
    if col_type in {"integer", "smallint", "bigint"}:
        return _bool_db(value)
    return _bool_db(value)


def _clean_value(key: str, value: Any, table: str = "calls") -> Any:
    if key in JSON_FIELDS:
        default = {} if key in {"scores_breakdown", "analysis"} else []
        # JSON strings work for both JSONB and legacy TEXT columns on PostgreSQL.
        return _json(value, default)
    if key in BOOL_FIELDS:
        return _clean_bool_value(key, value, table)
    return value


def _format_ts(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_json_field(key: str, raw: Any) -> Any:
    if raw is None:
        return {} if key in {"scores_breakdown", "analysis"} else []
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {} if key in {"scores_breakdown", "analysis"} else []
    return raw


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for key in JSON_FIELDS:
        if key in d:
            d[key] = _parse_json_field(key, d[key])
    for key in BOOL_FIELDS:
        if key in d and d[key] is not None:
            d[key] = bool(d[key])
    for ts_key in ("uploaded_at", "processed_at", "created_at", "last_synced"):
        if ts_key in d and d[ts_key] is not None:
            d[ts_key] = _format_ts(d[ts_key])
    return d


def _pg_value_placeholder(col: str, table: str = "calls") -> str:
    if DB_TYPE == "postgres" and table == "calls" and col in CALL_PG_BOOL_CAST:
        return f":{col}::boolean"
    return f":{col}"


def _pg_set_clause(key: str, table: str = "calls") -> str:
    if DB_TYPE == "postgres" and table == "calls" and key in CALL_PG_BOOL_CAST:
        return f"{key} = :{key}::boolean"
    return f"{key} = :{key}"


def clean_fields(fields: dict, table: str = "calls") -> dict:
    """Serialize a partial call update/insert payload for the active DB backend."""
    clean = {
        k: _clean_value(k, v, table)
        for k, v in fields.items()
        if k not in {"id", "call_id"}
    }
    if DB_TYPE == "postgres" and table == "calls":
        for key in ("critical_fail", "ptp_detected"):
            if key in clean and not isinstance(clean[key], bool):
                clean[key] = bool(_bool_db(clean[key]))
    return clean


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
        print("[DB] PostgreSQL initialised", flush=True)
    else:
        _init_sqlite()
        print(f"[DB] SQLite initialized at {DB_PATH}", flush=True)


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
        _migrate_common(conn)
        _seed_defaults(conn)


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
        _migrate_common(conn)
        _seed_defaults(conn)


def _seed_defaults(conn):
    try:
        conn.execute(
            """
            INSERT INTO organisations (id, name, slug)
            VALUES (:id, :name, :slug)
            ON CONFLICT (id) DO NOTHING
            """,
            {"id": "org_default", "name": "Company Finance", "slug": "company-finance"},
        )
    except Exception as exc:
        print(f"[DB] Seed organisations skipped: {exc}", flush=True)

    admin_hash = "care@2025"
    if bcrypt:
        try:
            admin_hash = bcrypt.hashpw(b"care@2025", bcrypt.gensalt()).decode("utf-8")
        except Exception:
            pass

    try:
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
                "is_active": _clean_bool_value("is_active", True, "users"),
            },
        )
    except Exception as exc:
        print(f"[DB] Seed admin user skipped: {exc}", flush=True)


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
    _refresh_bool_column_types(conn)


# ── Call CRUD ────────────────────────────────────────────────────────────────

def save_call(call: dict):
    """Insert or update call record."""
    call_id = call.get("id") or call.get("call_id")
    data: dict[str, Any] = {}
    for col, raw in call.items():
        key = "id" if col == "call_id" else col
        if key not in CALL_COLUMNS:
            continue
        if raw is None or raw == "":
            continue
        data[key] = _clean_value(key, raw, "calls")

    data["id"] = data.get("id") or call_id
    if not data.get("id"):
        raise ValueError("save_call requires id or call_id")
    data["org_id"] = data.get("org_id") or call.get("org_id") or "org_default"
    data["source"] = data.get("source") or call.get("source") or "upload"
    data["status"] = data.get("status") or call.get("status") or "queued"
    data["uploaded_at"] = data.get("uploaded_at") or call.get("uploaded_at") or now_iso()

    cols = list(data.keys())
    placeholders = ", ".join(_pg_value_placeholder(c, "calls") for c in cols)
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
    clean = clean_fields(fields)
    if not clean:
        return
    set_clause = ", ".join(_pg_set_clause(k, "calls") for k in clean)
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

def _call_upload_date(call: dict) -> str:
    ts = _format_ts(call.get("uploaded_at")) or ""
    return ts[:10]


def get_dashboard_stats(org_id: str = "org_default") -> dict:
    calls = list_calls(org_id=org_id, limit=1000)
    total = len(calls)
    processed = [c for c in calls if c.get("status") == "processed"]
    flags = sum(len(c.get("compliance_flags") or []) for c in calls)
    scores = [float(c.get("score_pct") or c.get("score") or 0) for c in processed]
    avg_score = round(sum(scores) / max(len(scores), 1), 1) if scores else 0
    ptp_count = sum(1 for c in calls if c.get("ptp_detected"))

    score_distribution = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
    for score in scores:
        if score <= 20:
            score_distribution["0-20"] += 1
        elif score <= 40:
            score_distribution["21-40"] += 1
        elif score <= 60:
            score_distribution["41-60"] += 1
        elif score <= 80:
            score_distribution["61-80"] += 1
        else:
            score_distribution["81-100"] += 1

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
            "agent_id": a["agent"],
            "name": a["agent"],
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

    today = datetime.now(timezone.utc).date().isoformat()
    calls_today = [c for c in calls if _call_upload_date(c) == today]
    ingestion = {"direct": 0, "google_drive": 0, "dialer_webhook": 0, "s3": 0}
    for c in calls_today:
        src = (c.get("source") or "upload").lower()
        if src in {"gdrive", "google_drive"}:
            ingestion["google_drive"] += 1
        elif src == "s3":
            ingestion["s3"] += 1
        elif src in {"webhook", "dialer", "dialer_webhook"}:
            ingestion["dialer_webhook"] += 1
        else:
            ingestion["direct"] += 1

    live_statuses = {"queued", "fetching", "transcribing", "scoring", "processing"}
    processed_ptp = sum(1 for c in processed if c.get("ptp_detected"))

    return {
        "total_calls": total,
        "calls_today": len(calls_today),
        "processed_calls": len(processed),
        "processed": len(processed),
        "processed_pct": round((len(processed) / max(total, 1)) * 100, 1),
        "processing_pct": round((len(processed) / max(total, 1)) * 100),
        "avg_score": avg_score,
        "ptp_count": ptp_count,
        "ptp_rate": round((processed_ptp / max(len(processed), 1)) * 100, 1),
        "compliance_flags": flags,
        "live_calls": len([c for c in calls if (c.get("status") or "").lower() in live_statuses]),
        "disposition_counts": disposition_counts,
        "disposition_breakdown": disposition_counts,
        "score_distribution": score_distribution,
        "agent_performance": sorted(agent_rows, key=lambda x: x["calls"], reverse=True),
        "loan_analytics": sorted(loan_rows, key=lambda x: x["calls"], reverse=True),
        "ingestion": ingestion,
        "recent_calls": calls[:20],
    }


# ── User / Auth ──────────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(email)=lower(?) AND is_active = 1",
            (email,),
        ).fetchone()
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
                "is_active": _clean_bool_value("is_active", True, "users"),
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
        "auto_sync": _clean_bool_value("auto_sync", auto_sync, "drive_configs"),
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
