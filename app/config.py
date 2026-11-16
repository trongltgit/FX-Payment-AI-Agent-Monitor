"""
Cấu hình & kiểm tra khởi động.

Nguyên tắc: production mà cấu hình yếu -> KHÔNG khởi động (fail closed),
thay vì chạy với giá trị mặc định mà không ai để ý.
"""
import os
import secrets

DEFAULT_DEMO_PASSWORD = "demo123"


def environment() -> str:
    return os.environ.get("PRICING_ENVIRONMENT", "demo").strip().lower()


def is_production() -> bool:
    return environment() == "production"


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def apply_and_validate(app) -> list:
    """Áp cấu hình bảo mật cho app; trả về danh sách cảnh báo (không chặn)."""
    warnings = []
    prod = is_production()

    secret = os.environ.get("SECRET_KEY", "").strip()
    signing = os.environ.get("API_SIGNING_SECRET", "").strip()
    weak = {"dev", "change-this-secret-key-in-production-32chars",
            "doi-thanh-chuoi-dai-ngau-nhien-rat-bao-mat"}

    if prod:
        errors = []
        if len(secret) < 32 or secret in weak:
            errors.append("SECRET_KEY phải ngẫu nhiên, >= 32 ký tự")
        if len(signing) < 32 or signing in weak or signing == secret:
            errors.append("API_SIGNING_SECRET phải ngẫu nhiên, >= 32 ký tự và khác SECRET_KEY")
        if not os.environ.get("REDIS_URL", "").strip() and not _truthy("ALLOW_MEMORY_STORE"):
            errors.append("REDIS_URL bắt buộc (session, rate limit, ban, quote phải dùng chung giữa worker). "
                          "Chỉ khi chạy đúng 1 worker mới đặt ALLOW_MEMORY_STORE=1")
        dp = os.environ.get("DEMO_PASSWORD", DEFAULT_DEMO_PASSWORD)
        if dp == DEFAULT_DEMO_PASSWORD or len(dp) < 12:
            errors.append("DEMO_PASSWORD bắt buộc đặt >= 12 ký tự khi production (không dùng demo123)")
        if errors:
            raise RuntimeError("Cấu hình production không an toàn:\n - " + "\n - ".join(errors))
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["DEBUG"] = False
    else:
        if len(secret) < 16:
            secret = secrets.token_urlsafe(48)
            warnings.append("SECRET_KEY chưa đặt -> dùng khóa ngẫu nhiên cho tiến trình này "
                            "(phiên sẽ mất khi restart).")
        if len(signing) < 16:
            signing = secrets.token_urlsafe(48)
            os.environ["API_SIGNING_SECRET"] = signing
        app.config["SESSION_COOKIE_SECURE"] = _truthy("SESSION_COOKIE_SECURE")

    app.secret_key = secret
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = 1800
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024        # body JSON tối đa 64KB
    return warnings


def mfa_required_roles() -> set:
    default = "HQ,CN_ADMIN" if is_production() else ""
    raw = os.environ.get("MFA_REQUIRED_ROLES", default)
    return {r.strip().upper() for r in raw.split(",") if r.strip()}
