"""TOTP (RFC 6238) tối giản – MFA cho HQ / Admin CN. Không phụ thuộc thư viện ngoài."""
import base64
import hashlib
import hmac
import struct
import time

from utils import store


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32.replace(" ", "").upper() + "=" * (-len(secret_b32) % 8))
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_now(secret_b32: str, at: float = None, step: int = 30) -> str:
    return _hotp(secret_b32, int((at if at is not None else time.time()) // step))


def verify(user_id: str, secret_b32: str, code: str, window: int = 1, step: int = 30) -> bool:
    """Đúng mã trong cửa sổ ±window và mã đó chưa được dùng (chống replay OTP)."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6) or not secret_b32:
        return False
    counter = int(store.now() // step)
    for c in range(counter - window, counter + window + 1):
        if hmac.compare_digest(_hotp(secret_b32, c), code):
            return store.setnx(f"totp:{user_id}:{c}", "1", ttl=step * (2 * window + 2))
    return False
