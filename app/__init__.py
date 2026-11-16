import os

from dotenv import load_dotenv
from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()


def create_app(test_config: dict = None):
    from app import config as cfg
    from app.guard import init_guard
    from utils.server_session import ServerSessionInterface

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, "templates"),
        static_folder=os.path.join(BASE_DIR, "static"),
    )

    # Cấu hình bảo mật – production cấu hình yếu thì từ chối khởi động
    for w in cfg.apply_and_validate(app):
        app.logger.warning(w)
    app.config["JSON_SORT_KEYS"] = False
    if test_config:
        app.config.update(test_config)

    # Session phía server (thu hồi được) thay cho cookie-session mặc định
    app.session_interface = ServerSessionInterface()

    # Reverse proxy: chỉ tin đúng số lớp proxy khai báo (PROXY_HOPS, mặc định 1; 0 = không proxy)
    hops = int(os.environ.get("PROXY_HOPS", "1"))
    if hops > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    redis_url = os.environ.get("REDIS_URL", "").strip()
    storage_uri = redis_url if redis_url.startswith(("redis://", "rediss://")) else "memory://"
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["120 per minute", "3000 per hour"],
        storage_uri=storage_uri,
        strategy="moving-window",       # v1: fixed-window cho phép bùng nổ 2x ở ranh giới cửa sổ
    )
    app.limiter = limiter

    from app.routes import main_bp, api_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    try:
        from app.pricing import pricing_bp
        app.register_blueprint(pricing_bp)
    except ImportError:
        app.logger.warning("Pricing module chưa được load.")
    try:
        from app.transaction import transaction_bp
        app.register_blueprint(transaction_bp)
    except ImportError:
        app.logger.warning("Transaction module chưa được load.")

    try:
        import agentmon
        agentmon.init_app(app)
    except ImportError:
        app.logger.warning("Module agentmon chưa được load.")

    init_guard(app)

    @app.context_processor
    def inject_app_info():
        return {
            "app_name": "Anti-Bot Pro + Pricing",
            "environment": cfg.environment(),
            "turnstile_site_key": os.environ.get("TURNSTILE_SITE_KEY", ""),
        }

    return app


_wsgi_app = None


def __getattr__(name):
    """
    Cho phép `gunicorn app:app`. Thư mục app/ che mất app.py nên bản cũ báo
    "Failed to find attribute 'app' in 'app'". Khuyến nghị dùng `gunicorn run:app`.
    """
    global _wsgi_app
    if name == "app":
        if _wsgi_app is None:
            _wsgi_app = create_app()
        return _wsgi_app
    raise AttributeError(name)
