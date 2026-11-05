"""
Rate limit helpers – theo IP và theo user_id.
"""
from functools import wraps
from flask import current_app, session, request


def _user_or_ip_key():
    """Key rate-limit: ưu tiên user_id khi đã đăng nhập, không thì IP."""
    uid = session.get("user_id")
    if uid:
        return f"user:{uid}"
    # fallback IP (sau ProxyFix)
    return request.remote_addr or "unknown"


def custom_rate_limit(limit_string: str):
    """
    Decorator rate limit theo IP (mặc định của Flask-Limiter).
    Cách dùng: @custom_rate_limit("10 per minute")
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            limiter = getattr(current_app, "limiter", None)
            if limiter is None:
                return f(*args, **kwargs)
            return limiter.limit(limit_string)(f)(*args, **kwargs)
        return wrapped
    return decorator


def user_rate_limit(limit_string: str):
    """
    Rate limit theo user_id (hoặc IP nếu chưa login).
    Áp dụng cho quote / execute để chống bot dùng nhiều tài khoản chậm.
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            limiter = getattr(current_app, "limiter", None)
            if limiter is None:
                return f(*args, **kwargs)
            return limiter.limit(limit_string, key_func=_user_or_ip_key)(f)(*args, **kwargs)
        return wrapped
    return decorator
