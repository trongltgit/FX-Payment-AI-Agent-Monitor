"""Hệ thống nguồn (portal, Digibank/Digibiz, switch thẻ, ATM, IPS) gửi giao dịch của NGƯỜI vào Monitor.
Mỗi hệ thống có API key riêng `skx_<prefix>_<secret>` (chỉ lưu băm), gắn với MỘT loại nguồn → chỉ được gửi các loại giao dịch của nguồn đó."""
import hmac
import re
import secrets
import time

from agentmon import db
from agentmon.constants import SOURCE_SYSTEMS
from agentmon.registry import _h


def register(system_id: str, source: str, name: str = ""):
    if source not in SOURCE_SYSTEMS:
        raise ValueError("source phải là một trong: " + ", ".join(SOURCE_SYSTEMS))
    if not re.fullmatch(r"[A-Za-z0-9_\-]{3,40}", system_id or ""):
        raise ValueError("system_id không hợp lệ")
    if not db.one("SELECT system_id FROM source_systems WHERE system_id=?", (system_id,)):
        db.execute("INSERT INTO source_systems(system_id,source,name,status,created_at) VALUES(?,?,?,?,?)",
                   (system_id, source, name or SOURCE_SYSTEMS[source]["name"], "ACTIVE", time.time()))
    return get(system_id)


def get(system_id):
    return db.one("SELECT system_id,source,name,status,key_prefix,created_at FROM source_systems WHERE system_id=?", (system_id,))


def issue_key(system_id):
    s = db.one("SELECT * FROM source_systems WHERE system_id=?", (system_id,))
    if not s or s["status"] != "ACTIVE":
        return None
    prefix, secret = secrets.token_hex(4), secrets.token_urlsafe(30)
    key = f"skx_{prefix}_{secret}"
    db.execute("UPDATE source_systems SET key_hash=?, key_prefix=? WHERE system_id=?", (_h(key), prefix, system_id))
    return key


def by_key(key: str):
    m = re.fullmatch(r"skx_([0-9a-f]{8})_[A-Za-z0-9_\-]{20,64}", key or "")
    if not m:
        return None
    r = db.one("SELECT * FROM source_systems WHERE key_prefix=? AND status='ACTIVE'", (m.group(1),))
    if r and r.get("key_hash") and hmac.compare_digest(r["key_hash"], _h(key)):
        return r
    return None


def set_status(system_id, status):
    db.execute("UPDATE source_systems SET status=? WHERE system_id=?", (status, system_id))


def list_all():
    return db.query("SELECT system_id,source,name,status,key_prefix,created_at FROM source_systems ORDER BY system_id")
