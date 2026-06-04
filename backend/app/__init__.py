from flask import Flask, jsonify

from app.config import Config
from app.extensions import bcrypt, cors, jwt, mongo
from app.utils.db import ensure_indexes
from app.utils.errors import register_error_handlers


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    mongo.init_app(app)
    jwt.init_app(app)
    bcrypt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    # JWT failure responses use the same `{error_code, message, details}` envelope as AppError
    @jwt.unauthorized_loader
    def _missing_token(reason: str):
        return jsonify({"error_code": "UNAUTHORIZED", "message": reason, "details": {}}), 401

    @jwt.invalid_token_loader
    def _invalid_token(reason: str):
        return jsonify({"error_code": "INVALID_TOKEN", "message": reason, "details": {}}), 401

    @jwt.expired_token_loader
    def _expired_token(_jwt_header, _jwt_payload):
        return jsonify({"error_code": "TOKEN_EXPIRED", "message": "Token has expired", "details": {}}), 401

    @jwt.needs_fresh_token_loader
    def _needs_fresh(_jwt_header, _jwt_payload):
        return jsonify({"error_code": "FRESH_TOKEN_REQUIRED", "message": "Fresh token required", "details": {}}), 401

    @jwt.revoked_token_loader
    def _revoked(_jwt_header, _jwt_payload):
        return jsonify({"error_code": "TOKEN_REVOKED", "message": "Token has been revoked", "details": {}}), 401

    # Blueprints
    from app.api.accounts import bp as accounts_bp
    from app.api.alerts import bp as alerts_bp
    from app.api.auth import bp as auth_bp
    from app.api.categories import bp as categories_bp
    from app.api.fx import bp as fx_bp
    from app.api.goals import bp as goals_bp
    from app.api.health import bp as health_bp
    from app.api.me import bp as me_bp
    from app.api.networth import bp as networth_bp
    from app.api.portfolio import bp as portfolio_bp
    from app.api.recurring import bp as recurring_bp
    from app.api.reports import bp as reports_bp
    from app.api.search import bp as search_bp
    from app.api.stocks import bp as stocks_bp
    from app.api.transactions import bp as transactions_bp

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(me_bp, url_prefix="/api")
    app.register_blueprint(categories_bp, url_prefix="/api")
    app.register_blueprint(transactions_bp, url_prefix="/api")
    app.register_blueprint(goals_bp, url_prefix="/api")
    app.register_blueprint(reports_bp, url_prefix="/api")
    app.register_blueprint(accounts_bp, url_prefix="/api")
    app.register_blueprint(recurring_bp, url_prefix="/api")
    app.register_blueprint(fx_bp, url_prefix="/api")
    app.register_blueprint(networth_bp, url_prefix="/api")
    app.register_blueprint(stocks_bp, url_prefix="/api")
    app.register_blueprint(portfolio_bp, url_prefix="/api")
    app.register_blueprint(alerts_bp, url_prefix="/api")
    app.register_blueprint(search_bp, url_prefix="/api")

    register_error_handlers(app)

    # Idempotent index bootstrap. Skipped under TESTING (mongomock would no-op).
    if not app.config.get("TESTING") and mongo.db is not None:
        try:
            ensure_indexes(mongo.db)
        except Exception:  # noqa: BLE001 — connection failures shouldn't block startup in dev
            app.logger.warning("ensure_indexes failed; continuing without indexes")

    # Background jobs (auto-materialize planned payments, etc.). No-op under TESTING.
    from app.jobs import init_scheduler
    init_scheduler(app)

    return app
