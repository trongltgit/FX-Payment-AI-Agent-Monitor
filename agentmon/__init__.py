"""AI Agent Monitor – module giám sát AI Agent (FX Trading + Thanh toán) tích hợp vào Anti-Bot Pro."""


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
