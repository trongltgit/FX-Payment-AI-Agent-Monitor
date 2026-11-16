"""
KYA (Know Your Agent) – xác minh giao dịch bất thường qua ứng dụng Authenticator của khách hàng.

Hai kênh xác nhận (khách chọn một):
  1) PUSH: trang/ứng dụng /authenticator đã GHÉP THIẾT BỊ (mã ghép 8 số dùng 1 lần + PIN thiết bị) → Duyệt/Từ chối.
  2) TOTP (RFC 6238): nhập mã 6 số từ Google/Microsoft Authenticator vào cổng KH (secret sinh khi đăng ký Authenticator).
Giao dịch chỉ được thực hiện SAU khi khách duyệt. Quá hạn/Từ chối -> không thực hiện. Từ chối nhiều lần -> tự đình chỉ Agent.
"""
import hashlib
import hmac
import secrets
import time
import base64

from agentmon import db
from utils import store
from utils import totp as totp_mod

DENY_LIMIT = 3


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def now() -> float:
    return store.now()


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def otpauth_uri(customer_id: str, secret: str) -> str:
    return f"otpauth://totp/AIAgentBank:{customer_id}?secret={secret}&issuer=AIAgentBank&digits=6&period=30"


def get_auth(customer_id):
    return db.one("SELECT * FROM authenticators WHERE customer_id=?", (customer_id,))


def enrolled(customer_id) -> bool:
    a = get_auth(customer_id)
    return bool(a and a.get("totp_secret"))


def device_paired(customer_id) -> bool:
    a = get_auth(customer_id)
    return bool(a and a.get("device_hash"))


def start_pairing(customer_id):
    """Sinh (nếu chưa có) secret TOTP + mã ghép 8 số dùng 1 lần, hết hạn 10 phút."""
    a = get_auth(customer_id)
    code = "".join(secrets.choice("0123456789") for _ in range(8))
    t = now()
    if not a:
        db.execute("INSERT INTO authenticators(customer_id,totp_secret,pairing_hash,pairing_exp,created_at) VALUES(?,?,?,?,?)",
                   (customer_id, new_secret(), _h(code), t + 600, t))
    else:
        db.execute("UPDATE authenticators SET pairing_hash=?, pairing_exp=?, pairing_fails=0, "
                   "totp_secret=COALESCE(totp_secret,?) WHERE customer_id=?", (_h(code), t + 600, new_secret(), customer_id))
    a = get_auth(customer_id)
    return {"pairing_code": code, "expires_in": 600, "totp_secret": a["totp_secret"],
            "otpauth_uri": otpauth_uri(customer_id, a["totp_secret"])}


def pair_device(code: str, pin: str, label: str = "Điện thoại"):
    """Gọi từ trang /authenticator (chưa có phiên). Trả device_token (chỉ hiển thị một lần)."""
    code = (code or "").strip()
    if not (code.isdigit() and len(code) == 8) or not (pin or "").isdigit() or not (4 <= len(pin) <= 8):
        return None, "Mã ghép phải 8 số, PIN 4–8 số."
    h = _h(code)
    row = db.one("SELECT * FROM authenticators WHERE pairing_hash=? AND pairing_exp>?", (h, now()))
    if not row:
        # chống dò mã: đếm lỗi toàn cục theo store (IP do route đảm nhiệm)
        return None, "Mã ghép sai hoặc đã hết hạn."
    token = "dev_" + secrets.token_urlsafe(32)
    db.execute("UPDATE authenticators SET device_hash=?, pin_hash=?, device_label=?, paired_at=?, pairing_hash=NULL, "
               "pairing_exp=0, pin_fails=0, pin_locked_until=0 WHERE customer_id=?",
               (_h(token), _h(row["customer_id"] + ":" + pin), (label or "Điện thoại")[:40], now(), row["customer_id"]))
    return {"device_token": token, "customer_id": row["customer_id"]}, "OK"


def device_by_token(token: str):
    if not token or not token.startswith("dev_"):
        return None
    return db.one("SELECT * FROM authenticators WHERE device_hash=?", (_h(token),))


def unpair(customer_id):
    db.execute("UPDATE authenticators SET device_hash=NULL, pin_hash=NULL, device_label=NULL, paired_at=NULL WHERE customer_id=?",
               (customer_id,))


def create_challenge(action_id: int, customer_id: str, ttl: int):
    kid = "KYA" + secrets.token_hex(6).upper()
    t = now()
    db.execute("INSERT INTO kya(id,action_id,customer_id,status,created_at,expires_at) VALUES(?,?,?,?,?,?)",
               (kid, action_id, customer_id, "PENDING", t, t + ttl))
    return kid


def expire_stale():
    """Đánh dấu hết hạn các thử thách quá TTL và hủy giao dịch tương ứng (không thực hiện)."""
    t = now()
    rows = db.query("SELECT id, action_id FROM kya WHERE status='PENDING' AND expires_at<=?", (t,))
    for r in rows:
        db.execute("UPDATE kya SET status='EXPIRED', decided_at=? WHERE id=? AND status='PENDING'", (t, r["id"]))
        db.execute("UPDATE actions SET status='EXPIRED', reason_public='Hết hạn xác minh KYA – giao dịch không được thực hiện' "
                   "WHERE id=? AND status='PENDING_KYA'", (r["action_id"],))
    return len(rows)


def pending_for(customer_id):
    expire_stale()
    rows = db.query("SELECT k.*, a.domain, a.kind, a.amount_vnd, a.amount_usd, a.pair, a.side, a.leverage, a.beneficiary, "
                    "a.merchant, a.country, a.agent_id, a.triggers, a.reason_public FROM kya k JOIN actions a ON a.id=k.action_id "
                    "WHERE k.customer_id=? AND k.status='PENDING' ORDER BY k.created_at DESC", (customer_id,))
    out = []
    for r in rows:
        ben = r.get("beneficiary")
        out.append({"kya_id": r["id"], "action_id": r["action_id"], "domain": r["domain"], "kind": r["kind"],
                    "amount_vnd": r["amount_vnd"], "amount_usd": r["amount_usd"], "pair": r["pair"], "side": r["side"],
                    "leverage": r["leverage"], "beneficiary": ("***" + ben[-4:]) if ben else None, "merchant": r["merchant"],
                    "country": r["country"], "agent_id": r["agent_id"], "triggers": db.jload(r["triggers"], []),
                    "expires_in": max(0, int(r["expires_at"] - now())), "created_at": r["created_at"]})
    return out


def _finish(kid, approved: bool, method: str):
    from agentmon import engine
    k = db.one("SELECT * FROM kya WHERE id=?", (kid,))
    t = now()
    if approved:
        db.execute("UPDATE kya SET status='APPROVED', decided_at=?, method=? WHERE id=?", (t, method, kid))
        return engine.execute_action(k["action_id"], via=f"KYA:{method}")
    db.execute("UPDATE kya SET status='DENIED', decided_at=?, method=? WHERE id=?", (t, method, kid))
    db.execute("UPDATE actions SET status='DENIED_BY_CUSTOMER', reason_public='Khách hàng TỪ CHỐI giao dịch qua Authenticator' WHERE id=?",
               (k["action_id"],))
    engine.on_customer_denied(k["action_id"])
    return {"status": "DENIED_BY_CUSTOMER"}


def _load_open(customer_id, kid):
    expire_stale()
    k = db.one("SELECT * FROM kya WHERE id=? AND customer_id=?", (kid, customer_id))
    if not k:
        return None, "Không tìm thấy yêu cầu xác minh."
    if k["status"] != "PENDING":
        return None, f"Yêu cầu đã ở trạng thái {k['status']}."
    return k, "OK"


def approve_totp(customer_id, kid, code):
    k, msg = _load_open(customer_id, kid)
    if not k:
        return False, msg, None
    if k["attempts"] >= 3:
        db.execute("UPDATE kya SET status='DENIED', decided_at=?, method='TOTP_LOCK' WHERE id=?", (now(), kid))
        db.execute("UPDATE actions SET status='DENIED_BY_CUSTOMER', reason_public='Nhập sai OTP quá 3 lần – giao dịch bị hủy' WHERE id=?",
                   (k["action_id"],))
        return False, "Nhập sai OTP quá 3 lần – giao dịch bị hủy.", None
    a = get_auth(customer_id)
    if not a or not a.get("totp_secret"):
        return False, "Chưa đăng ký Authenticator.", None
    db.execute("UPDATE kya SET attempts=attempts+1 WHERE id=?", (kid,))
    if not totp_mod.verify(customer_id, a["totp_secret"], code):
        return False, "Mã OTP không đúng hoặc đã dùng.", None
    return True, "OK", _finish(kid, True, "TOTP")


def decide_device(token, kid, approve: bool, pin: str):
    a = device_by_token(token)
    if not a:
        return False, "Thiết bị chưa ghép hoặc đã hủy.", None
    if a["pin_locked_until"] and a["pin_locked_until"] > now():
        return False, "Thiết bị bị khóa tạm do nhập sai PIN.", None
    k, msg = _load_open(a["customer_id"], kid)
    if not k:
        return False, msg, None
    if approve:
        if not hmac.compare_digest(_h(a["customer_id"] + ":" + (pin or "")), a["pin_hash"] or ""):
            fails = (a["pin_fails"] or 0) + 1
            lock = now() + 900 if fails >= 5 else 0
            db.execute("UPDATE authenticators SET pin_fails=?, pin_locked_until=? WHERE customer_id=?",
                       (0 if lock else fails, lock, a["customer_id"]))
            return False, "PIN không đúng." + (" Thiết bị bị khóa 15 phút." if lock else ""), None
        db.execute("UPDATE authenticators SET pin_fails=0 WHERE customer_id=?", (a["customer_id"],))
        return True, "OK", _finish(kid, True, "PUSH")
    return True, "OK", _finish(kid, False, "PUSH")


def deny_portal(customer_id, kid):
    k, msg = _load_open(customer_id, kid)
    if not k:
        return False, msg, None
    return True, "OK", _finish(kid, False, "PORTAL")
