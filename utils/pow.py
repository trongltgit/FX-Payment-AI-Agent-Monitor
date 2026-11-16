"""
Proof-of-Work challenge (chống bot đăng nhập / hỏi giá hàng loạt).

Server phát  prefix  ngẫu nhiên + độ khó  bits.
Client phải tìm nonce sao cho SHA-256(prefix + nonce) có >= bits bit 0 đứng đầu.
  * Trình duyệt thật: giải trong ~0.2-1 giây (không ai để ý).
  * Bot chạy hàng nghìn request: mỗi request tốn CPU -> chi phí tăng tuyến tính.

LƯU Ý TRUNG THỰC: PoW là rào kinh tế, KHÔNG phải bằng chứng "là người".
Nó làm bot rẻ tiền đắt lên, kết hợp với Turnstile/CAPTCHA mới có ý nghĩa phân biệt người/máy.
Challenge dùng đúng 1 lần (xóa ngay khi verify) và hết hạn sau TTL giây.
"""
import hashlib
import os
import secrets
from typing import Optional, Tuple

from utils import store

TTL = 120


def default_bits() -> int:
    try:
        return int(os.environ.get("LOGIN_POW_BITS", "18"))
    except ValueError:
        return 18


def issue(bits: Optional[int] = None, bind: str = "") -> dict:
    cid = secrets.token_urlsafe(16)
    prefix = secrets.token_hex(12)
    bits = int(bits or default_bits())
    store.set_json(f"pow:{cid}", {"prefix": prefix, "bits": bits, "bind": bind}, ttl=TTL)
    return {"challenge_id": cid, "prefix": prefix, "bits": bits, "expires_in": TTL}


def _leading_zero_bits(digest: bytes) -> int:
    n = 0
    for b in digest:
        if b == 0:
            n += 8
            continue
        n += 8 - b.bit_length()
        break
    return n


def solve(prefix: str, bits: int, limit: int = 50_000_000) -> int:
    """Giải thử phía Python (dùng cho test / client tích hợp)."""
    for nonce in range(limit):
        h = hashlib.sha256(f"{prefix}{nonce}".encode()).digest()
        if _leading_zero_bits(h) >= bits:
            return nonce
    raise RuntimeError("không giải được PoW")


def verify(challenge_id: str, nonce, bind: str = "", min_bits: int = 0) -> Tuple[bool, str]:
    """(ok, reason). Challenge bị tiêu thụ dù đúng hay sai (single-use)."""
    if not challenge_id or nonce is None:
        return False, "missing"
    key = f"pow:{challenge_id}"
    rec = store.get_json(key)
    if not rec:
        return False, "expired_or_used"
    store.delete(key)  # single-use
    if rec.get("bind") and bind and rec["bind"] != bind:
        return False, "bind_mismatch"
    bits = max(int(rec["bits"]), int(min_bits))
    digest = hashlib.sha256(f"{rec['prefix']}{nonce}".encode()).digest()
    if _leading_zero_bits(digest) < bits:
        return False, "insufficient_work"
    return True, "ok"
