"""
Security utilities – IP, fingerprint, User-Agent, header profile, HMAC, nonce.

Thay đổi so với v1:
  * get_client_ip(): chỉ tin CF-Connecting-IP khi TRUSTED_PROXY=cloudflare
    (v1 tin header này nếu có CF-Ray -> client tự giả IP được).
  * verify_fingerprint(): luôn strict cho phiên đã đăng nhập (v1 tự re-bind khi lệch).
  * header_profile(): chấm điểm "giống trình duyệt thật" qua Sec-Fetch-*, Accept-Language...
  * Nonce lưu trong store (Redis) thay vì dict trong RAM từng worker.
  * Không còn secret mặc định trong mã: thiếu API_SIGNING_SECRET -> báo lỗi rõ ràng.
"""
import hashlib
import hmac
import os
import re
import time
from typing import List, Tuple

from flask import request, session

from utils import store

_NONCE_TTL = 120


# ----------------------------------------------------------------------- IP
def get_client_ip() -> str:
    """
    IP client. Sau ProxyFix, request.remote_addr đã là IP thật do proxy tin cậy gắn.
    CF-Connecting-IP chỉ được tin khi vận hành thật sự đứng sau Cloudflare
    (đặt TRUSTED_PROXY=cloudflare) VÀ origin chỉ nhận traffic từ dải IP Cloudflare.
    """
    remote = request.remote_addr or "unknown"
    if os.environ.get("TRUSTED_PROXY", "").strip().lower() == "cloudflare":
        cf = request.headers.get("CF-Connecting-IP")
        if cf:
            return cf.strip()
    return remote


# -------------------------------------------------------------- fingerprint
def get_client_fingerprint() -> str:
    components = [
        request.headers.get("User-Agent", ""),
        request.headers.get("Accept-Language", ""),
        request.headers.get("Sec-CH-UA-Platform", ""),
    ]
    return hashlib.sha256("|".join(components).encode("utf-8")).hexdigest()[:24]


def bind_fingerprint() -> str:
    fp = get_client_fingerprint()
    session["fingerprint"] = fp
    return fp


def verify_fingerprint(strict: bool = True) -> bool:
    """
    Phiên đã đăng nhập: fingerprint PHẢI khớp lúc đăng nhập (không re-bind).
    Phiên chưa có fingerprint (ẩn danh): gắn mới và cho qua.
    """
    current = get_client_fingerprint()
    stored = session.get("fingerprint")
    if not stored:
        session["fingerprint"] = current
        return True
    if hmac.compare_digest(current, stored):
        return True
    if session.get("user_id") or strict:
        return False
    session["fingerprint"] = current
    return True


# -------------------------------------------------------------- User-Agent
_BAD_UA = (
    "bot", "crawl", "spider", "slurp", "scrapy", "httpclient", "python-requests",
    "python-urllib", "python/", "aiohttp", "httpx", "curl", "wget", "libwww", "lwp-",
    "go-http", "java/", "okhttp", "apache-http", "phantomjs", "headless", "selenium",
    "puppeteer", "playwright", "mechanize", "postman", "insomnia", "axios/",
    "node-fetch", "undici", "guzzle", "restsharp", "powershell", "scraper", "harvest",
)


def is_suspicious_user_agent() -> bool:
    ua = (request.headers.get("User-Agent") or "").lower().strip()
    if not ua or len(ua) < 10:
        return True
    return any(k in ua for k in _BAD_UA)


# ----------------------------------------------------------- header profile
_BROWSER_UA = re.compile(r"(chrome/|firefox/|safari/|edg/)", re.I)


def header_profile() -> Tuple[int, List[str]]:
    """
    Chấm điểm bất thường của bộ header so với một trình duyệt thật.
    Điểm càng cao càng giống script giả UA trình duyệt.

    Trình duyệt hiện đại LUÔN gửi Sec-Fetch-Site/Mode/Dest và Accept-Language trên
    mọi request. Thư viện HTTP (requests, httpx, axios...) giả UA Chrome thường quên.
    Đây là tín hiệu (không phải bằng chứng) vì client tự viết vẫn có thể thêm đủ header.
    """
    score, reasons = 0, []
    h = request.headers
    ua = h.get("User-Agent", "")
    claims_browser = bool(_BROWSER_UA.search(ua))

    if not h.get("Accept-Language"):
        score += 15
        reasons.append("no_accept_language")
    if claims_browser and not h.get("Sec-Fetch-Site"):
        score += 25
        reasons.append("browser_ua_without_sec_fetch")
    if claims_browser and h.get("Sec-Fetch-Site") and not h.get("Sec-Fetch-Mode"):
        score += 10
        reasons.append("partial_sec_fetch")
    if h.get("Sec-Fetch-Site") == "cross-site":
        score += 30
        reasons.append("cross_site_request")
    if "Chrome/" in ua and "HeadlessChrome" not in ua and not h.get("Sec-CH-UA") and request.is_secure:
        score += 10
        reasons.append("chrome_ua_without_client_hints")
    if h.get("Accept-Encoding") is None:
        score += 5
        reasons.append("no_accept_encoding")
    return score, reasons


# -------------------------------------------------------------------- HMAC
def _signing_secret() -> str:
    secret = os.environ.get("API_SIGNING_SECRET", "").strip()
    if not secret:
        raise RuntimeError("API_SIGNING_SECRET chưa được cấu hình")
    return secret


def generate_pricing_signature(timestamp: str, method: str, path: str, body: str,
                               nonce: str = "", secret: str = None) -> str:
    secret = secret or _signing_secret()
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    message = (
        f"{timestamp}:{method.upper()}:{path}:{body_hash}:"
        f"{get_client_ip()}:{session.get('fingerprint', '')}:{nonce}"
    )
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_pricing_signature(timestamp: str, signature: str, method: str, path: str,
                             body: str, nonce: str = "", max_age_seconds: int = 60) -> bool:
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(int(time.time()) - ts) > max_age_seconds:
        return False
    # HMAC dùng cho client tích hợp -> BẮT BUỘC có nonce 8-64 ký tự, dùng 1 lần
    if not nonce or not (8 <= len(nonce) <= 64):
        return False
    expected = generate_pricing_signature(timestamp, method, path, body, nonce)
    if not hmac.compare_digest(expected, signature or ""):
        return False
    return store.setnx(f"nonce:{nonce}", "1", ttl=_NONCE_TTL)  # đúng chữ ký rồi mới tiêu thụ nonce
