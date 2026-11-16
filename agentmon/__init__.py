"""AI Agent Monitor – module giám sát AI Agent (FX Trading + Thanh toán) tích hợp vào Anti-Bot Pro."""

from agentmon.constants import CODE_VERSION as __version__  # noqa: E402,F401


def init_app(app):
    """Gắn module vào Flask app: DB + dữ liệu demo + blueprint."""
    from agentmon import db, seed
    from agentmon.api import agent_bp
    from agentmon.agent_api import gateway_bp
    db.init()
    if not db.meta_get("seeded"):
        seed.seed()
    app.register_blueprint(agent_bp, url_prefix="/api/agent")
    app.register_blueprint(gateway_bp)
    from agentmon.txn_api import txn_bp
    from agentmon.gateway import gw_bp
    app.register_blueprint(txn_bp)
    app.register_blueprint(gw_bp)
    from agentmon import profiles
    profiles.enforce(app)
