"""SQLite (WAL) cho AI Agent Monitor. Production: chuyển sang PostgreSQL (cùng schema, xem docs)."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lock = threading.RLock()
_ready_path = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS accounts(customer_id TEXT PRIMARY KEY, balance_vnd REAL NOT NULL);
CREATE TABLE IF NOT EXISTS cards(
  card_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, network TEXT NOT NULL, bin6 TEXT NOT NULL, last4 TEXT NOT NULL,
  token TEXT UNIQUE NOT NULL, pan_hash TEXT UNIQUE NOT NULL, holder TEXT, exp_month INTEGER, exp_year INTEGER,
  status TEXT DEFAULT 'ACTIVE', per_txn_limit REAL, daily_limit REAL, cnp_enabled INTEGER DEFAULT 1,
  intl_enabled INTEGER DEFAULT 0, created_at REAL);
CREATE INDEX IF NOT EXISTS ix_cards_cust ON cards(customer_id);
CREATE TABLE IF NOT EXISTS trusted_beneficiaries(customer_id TEXT, account TEXT, bank TEXT, added_at REAL,
  PRIMARY KEY(customer_id, account));
CREATE TABLE IF NOT EXISTS agents(
  agent_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, branch_id TEXT, name TEXT, purpose TEXT,
  domains TEXT, kinds TEXT, status TEXT NOT NULL, limits TEXT, requested_limits TEXT,
  consent_version TEXT, consent_at REAL, consent_ip TEXT, consent_hash TEXT,
  requested_at REAL, approved_by TEXT, approved_at REAL, valid_until REAL, reject_reason TEXT,
  key_hash TEXT, key_prefix TEXT, probation_left INTEGER DEFAULT 3, denied_count INTEGER DEFAULT 0,
  status_note TEXT, is_demo INTEGER DEFAULT 0, created_at REAL);
CREATE INDEX IF NOT EXISTS ix_agents_cust ON agents(customer_id);
CREATE INDEX IF NOT EXISTS ix_agents_key ON agents(key_prefix);
CREATE TABLE IF NOT EXISTS authenticators(
  customer_id TEXT PRIMARY KEY, totp_secret TEXT, pairing_hash TEXT, pairing_exp REAL, pairing_fails INTEGER DEFAULT 0,
  device_label TEXT, device_hash TEXT, pin_hash TEXT, paired_at REAL, pin_fails INTEGER DEFAULT 0, pin_locked_until REAL DEFAULT 0,
  created_at REAL);
CREATE TABLE IF NOT EXISTS actions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, domain TEXT, kind TEXT, customer_id TEXT, branch_id TEXT,
  agent_id TEXT, channel TEXT, client_ref TEXT, amount_vnd REAL, amount_usd REAL, pair TEXT, side TEXT, leverage REAL,
  beneficiary TEXT, merchant TEXT, mcc TEXT, country TEXT, card_id TEXT, hour INTEGER,
  details TEXT, anomaly REAL, behavior REAL, velocity REAL, final_risk REAL,
  decision TEXT, status TEXT, hard_reason TEXT, reasons TEXT, triggers TEXT, reason_public TEXT, llm TEXT,
  kya_id TEXT, reviewer TEXT, review_note TEXT, executed_at REAL, source TEXT, sim INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_act_cust_ts ON actions(customer_id, ts);
CREATE INDEX IF NOT EXISTS ix_act_agent_ts ON actions(agent_id, ts);
CREATE INDEX IF NOT EXISTS ix_act_dom ON actions(domain, ts);
CREATE UNIQUE INDEX IF NOT EXISTS ux_act_ref ON actions(agent_id, client_ref) WHERE client_ref IS NOT NULL;
CREATE TABLE IF NOT EXISTS kya(
  id TEXT PRIMARY KEY, action_id INTEGER, customer_id TEXT, status TEXT, created_at REAL, expires_at REAL,
  attempts INTEGER DEFAULT 0, decided_at REAL, method TEXT);
CREATE INDEX IF NOT EXISTS ix_kya_cust ON kya(customer_id, status);
CREATE TABLE IF NOT EXISTS policies(key TEXT PRIMARY KEY, value TEXT, updated_by TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS limits(customer_id TEXT, domain TEXT, value TEXT, updated_by TEXT, updated_at REAL,
  PRIMARY KEY(customer_id, domain));
CREATE TABLE IF NOT EXISTS flags(customer_id TEXT PRIMARY KEY, suspicion REAL DEFAULT 0, watchlist INTEGER DEFAULT 0, updated_at REAL);
"""


def path() -> str:
    p = os.environ.get("AGENTMON_DB", "").strip()
    if not p:
        p = os.path.join(_BASE, "data", "agentmon.db")
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    return p


def _connect():
    c = sqlite3.connect(path(), timeout=15, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init():
    global _ready_path
    with _lock:
        c = _connect()
        try:
            c.executescript(SCHEMA)
        finally:
            c.close()
        _ready_path = path()


@contextmanager
def tx():
    """Giao dịch ghi (BEGIN IMMEDIATE) – tuần tự hóa các thao tác ghi quan trọng (hạn mức, số dư)."""
    with _lock:
        if _ready_path != path():
            init()
        c = _connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except Exception:
            try:
                c.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            c.close()


def query(sql, args=()):
    with _lock:
        if _ready_path != path():
            init()
        c = _connect()
        try:
            return [dict(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()


def one(sql, args=()):
    r = query(sql, args)
    return r[0] if r else None


def execute(sql, args=()):
    with tx() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def jdump(o):
    return json.dumps(o, ensure_ascii=False, default=str)


def jload(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


def meta_get(key, default=None):
    r = one("SELECT value FROM meta WHERE key=?", (key,))
    return jload(r["value"], default) if r else default


def meta_set(key, value):
    execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, jdump(value)))
