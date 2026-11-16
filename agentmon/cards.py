"""
Tuân thủ số thẻ Visa / Mastercard (mô phỏng PCI DSS):
  - Luhn + dải BIN/IIN + độ dài đúng mạng thẻ.
  - KHÔNG lưu PAN đầy đủ: chỉ BIN6 + 4 số cuối + token + băm HMAC (chống trùng thẻ).
  - Hiển thị che số (tối đa 6 đầu + 4 cuối).
  - Không bao giờ nhận/lưu CVV/CVC/PIN/dữ liệu rãnh từ. Payload của agent chứa PAN hoặc CVV -> bị chặn + che dữ liệu.
"""
import hashlib
import hmac
import os
import re
import secrets
import time

_PAN_RUN = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
SENSITIVE_KEYS = {"cvv", "cvc", "cvv2", "cvc2", "cid", "pin", "track1", "track2", "pan", "card_number", "cardnumber"}


def _key() -> bytes:
    k = os.environ.get("CARD_VAULT_KEY") or os.environ.get("API_SIGNING_SECRET") or os.environ.get("SECRET_KEY") or "demo-vault-key"
    return k.encode()


def luhn_ok(num: str) -> bool:
    d = [int(c) for c in num if c.isdigit()]
    if len(d) != len(num) or len(d) < 12:
        return False
    s = 0
    for i, x in enumerate(reversed(d)):
        if i % 2 == 1:
            x *= 2
            if x > 9:
                x -= 9
        s += x
    return s % 10 == 0


def detect_network(pan: str):
    """Trả về 'VISA' | 'MASTERCARD' | None theo dải IIN và độ dài."""
    if not pan.isdigit():
        return None
    n = len(pan)
    if pan[0] == "4" and n in (13, 16, 19):
        return "VISA"
    if n == 16:
        p2 = int(pan[:2])
        p4 = int(pan[:4])
        if 51 <= p2 <= 55 or 2221 <= p4 <= 2720:
            return "MASTERCARD"
    return None


def normalize_pan(raw: str) -> str:
    return re.sub(r"[ \-]", "", str(raw or ""))


def validate_pan(raw: str):
    pan = normalize_pan(raw)
    if not pan.isdigit() or not (13 <= len(pan) <= 19):
        return False, "Số thẻ phải gồm 13–19 chữ số.", None
    net = detect_network(pan)
    if not net:
        return False, "Chỉ hỗ trợ thẻ Visa (bắt đầu 4) và Mastercard (51–55 / 2221–2720, 16 số).", None
    if not luhn_ok(pan):
        return False, "Số thẻ không hợp lệ (sai Luhn).", None
    return True, "OK", net


def pan_hash(pan: str) -> str:
    return hmac.new(_key(), pan.encode(), hashlib.sha256).hexdigest()


def new_token() -> str:
    return "tok_" + secrets.token_hex(12)


def mask(bin6: str, last4: str) -> str:
    return f"{bin6[:4]} {bin6[4:6]}** **** {last4}"


def find_pan_in(obj) -> bool:
    """True nếu bất kỳ giá trị chuỗi/số nào trong payload chứa dãy số qua Luhn như PAN, hoặc có khóa nhạy cảm."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in SENSITIVE_KEYS and v not in (None, "", False):
                return True
            if find_pan_in(v):
                return True
        return False
    if isinstance(obj, (list, tuple)):
        return any(find_pan_in(x) for x in obj)
    if isinstance(obj, (str, int)) and not isinstance(obj, bool):
        s = str(obj)
        for m in _PAN_RUN.finditer(s):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and luhn_ok(digits):
                return True
    return False


def redact(obj):
    """Che mọi PAN/CVV trong payload trước khi lưu hoặc ghi log."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in SENSITIVE_KEYS:
                out[k] = "[REDACTED]"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    if isinstance(obj, str):
        def _sub(m):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and luhn_ok(digits):
                return digits[:6] + "*" * (len(digits) - 10) + digits[-4:]
            return m.group(0)
        return _PAN_RUN.sub(_sub, obj)
    return obj


def expired(exp_month, exp_year, now=None) -> bool:
    t = time.gmtime(now or time.time())
    y = int(exp_year)
    if y < 100:
        y += 2000
    return (y, int(exp_month)) < (t.tm_year, t.tm_mon)


def add_card(customer_id, pan_raw, holder, exp_month, exp_year, per_txn=None, daily=None,
             cnp=True, intl=False, card_id=None):
    from agentmon import db
    ok, msg, net = validate_pan(pan_raw)
    if not ok:
        return False, msg, None
    try:
        em, ey = int(exp_month), int(exp_year)
    except (TypeError, ValueError):
        return False, "Ngày hết hạn không hợp lệ.", None
    if not (1 <= em <= 12) or expired(em, ey):
        return False, "Thẻ đã hết hạn hoặc ngày hết hạn sai.", None
    pan = normalize_pan(pan_raw)
    h = pan_hash(pan)
    if db.one("SELECT card_id FROM cards WHERE pan_hash=?", (h,)):
        return False, "Thẻ này đã được đăng ký trong hệ thống.", None
    cid = card_id or ("CARD" + secrets.token_hex(4).upper())
    rec = dict(card_id=cid, customer_id=customer_id, network=net, bin6=pan[:6], last4=pan[-4:],
               token=new_token(), pan_hash=h, holder=(holder or "")[:40], exp_month=em, exp_year=ey % 100 if ey > 99 else ey,
               status="ACTIVE", per_txn_limit=per_txn, daily_limit=daily, cnp_enabled=1 if cnp else 0,
               intl_enabled=1 if intl else 0, created_at=time.time())
    db.execute("INSERT INTO cards(card_id,customer_id,network,bin6,last4,token,pan_hash,holder,exp_month,exp_year,status,"
               "per_txn_limit,daily_limit,cnp_enabled,intl_enabled,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               tuple(rec[k] for k in ["card_id", "customer_id", "network", "bin6", "last4", "token", "pan_hash", "holder",
                                      "exp_month", "exp_year", "status", "per_txn_limit", "daily_limit", "cnp_enabled",
                                      "intl_enabled", "created_at"]))
    del pan   # PAN không được giữ lại
    return True, "OK", public_view(rec)


def public_view(c: dict) -> dict:
    """Dữ liệu thẻ trả ra giao diện: KHÔNG có pan_hash; token chỉ trả cho chủ thẻ/agent."""
    return {
        "card_id": c["card_id"], "customer_id": c["customer_id"], "network": c["network"],
        "masked": mask(c["bin6"], c["last4"]), "holder": c.get("holder"),
        "expiry": f"{int(c['exp_month']):02d}/{int(c['exp_year']):02d}", "status": c.get("status"),
        "per_txn_limit": c.get("per_txn_limit"), "daily_limit": c.get("daily_limit"),
        "cnp_enabled": bool(c.get("cnp_enabled")), "intl_enabled": bool(c.get("intl_enabled")),
        "token": c.get("token"),
    }
