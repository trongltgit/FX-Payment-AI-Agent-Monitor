"""
Audit / Behavior log – TSC thấy hết; CN_ADMIN theo branch.
"""
from threading import Lock, Thread
from copy import deepcopy
from typing import Any, Dict, List, Optional
import json
import os
import time
import csv
import io

from utils import store

_lock = Lock()
_LOGS: List[Dict[str, Any]] = []


def add_log(
    event: str,
    *,
    user_id: str = "",
    role: str = "",
    customer_id: str = "",
    branch_id: str = "",
    detail: Optional[Dict] = None,
    ip: str = "",
    level: str = "info",
) -> None:
    entry = {
        "ts": int(time.time()),
        "event": event,
        "user_id": user_id or "",
        "role": (role or "").upper(),
        "customer_id": customer_id or "",
        "branch_id": branch_id or "",
        "ip": ip or "",
        "level": level,
        "detail": detail or {},
    }
    with _lock:
        _LOGS.append(entry)
        if len(_LOGS) > 8000:
            del _LOGS[: len(_LOGS) - 8000]
    _persist(entry)
    if level == "critical":
        _alert(entry)


def _persist(entry: Dict[str, Any]) -> None:
    """Ghi thêm (append-only) ra file JSON Lines nếu cấu hình AUDIT_LOG_FILE.
    Production: trỏ file này vào agent đẩy log (Filebeat/Fluent Bit) -> SIEM."""
    path = os.environ.get("AUDIT_LOG_FILE", "").strip()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _alert(entry: Dict[str, Any]) -> None:
    """Gửi cảnh báo sự kiện critical (bot_blocked, honeypot_hit...) tới webhook (Slack/Teams/SIEM)."""
    url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return

    def _send():
        try:
            import requests
            requests.post(url, json={
                "text": f"[ANTI-BOT][{entry['level'].upper()}] {entry['event']} user={entry['user_id']} "
                        f"ip={entry['ip']} detail={json.dumps(entry['detail'], ensure_ascii=False)[:300]}"
            }, timeout=3)
        except Exception:
            pass

    Thread(target=_send, daemon=True).start()


def list_logs(
    *,
    role_viewer: str = "HQ",
    branch_id: str = "",
    user_id: str = "",
    limit: int = 200,
) -> List[Dict[str, Any]]:
    role_viewer = (role_viewer or "").upper()
    with _lock:
        items = list(_LOGS)
    if role_viewer == "HQ":
        selected = items
    elif role_viewer == "CN_ADMIN" and branch_id:
        selected = [x for x in items if x.get("branch_id") == branch_id]
    elif role_viewer in {"PNV", "STAFF", "BRANCH"} and user_id:
        selected = [x for x in items if x.get("user_id") == user_id]
    else:
        selected = []
    return [deepcopy(x) for x in selected[-limit:]]


def count_recent_quotes(user_id: str, window_seconds: int = 60) -> int:
    cutoff = int(time.time()) - window_seconds
    with _lock:
        return sum(
            1
            for x in _LOGS
            if x.get("user_id") == user_id
            and x.get("event") == "quote_request"
            and x.get("ts", 0) >= cutoff
        )


def check_same_param_cooldown(
    user_id: str, currency: str, side: str, amount: float, cooldown_seconds: int = 60
) -> Optional[int]:
    """
    Số giây còn lại nếu KH hỏi lại cùng ccy+side+NHÓM số tiền trong cooldown; None = được hỏi.
    v2: dùng nhóm số tiền (2 chữ số có nghĩa) nên đổi amount 0,01 không còn né được cooldown.
    Dùng store.setnx -> nguyên tử và đồng bộ giữa worker khi có Redis.
    """
    from services.bot_defense import amount_bucket
    key = f"cd:{user_id}:{currency.upper()}:{side.upper()}:{amount_bucket(amount)}"
    if store.setnx(key, "1", ttl=cooldown_seconds):
        return None
    return max(store.ttl(key), 1)


def bump_cif_quote_version(customer_id: str) -> int:
    """CN đổi margin/NSDH -> tăng version -> quote cũ hết hiệu lực."""
    return store.incr(f"cifver:{customer_id}")


def get_cif_quote_version(customer_id: str) -> int:
    return store.get_int(f"cifver:{customer_id}")


def claim_quote(quote_id: str, ttl: int = 900) -> bool:
    """True nếu quote chưa dùng (đồng thời đánh dấu đã dùng). Nguyên tử, dùng chung Redis."""
    if not quote_id:
        return False
    return store.setnx(f"quote_used:{quote_id}", "1", ttl=ttl)


def logs_to_csv(logs: List[Dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ts", "event", "level", "user_id", "role", "customer_id", "branch_id", "ip", "detail"])
    for x in logs:
        writer.writerow([
            x.get("ts"), x.get("event"), x.get("level"), x.get("user_id"),
            x.get("role"), x.get("customer_id"), x.get("branch_id"), x.get("ip"),
            str(x.get("detail") or {}),
        ])
    return buf.getvalue()
