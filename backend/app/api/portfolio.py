"""Paper-trading portfolio endpoints.

  GET   /api/portfolio              → current state + holdings + P&L
  GET   /api/portfolio/history      → equity curve over a range
  GET   /api/portfolio/trades       → recent trade log
  POST  /api/portfolio/buy          → execute a buy
  POST  /api/portfolio/sell         → execute a sell
  POST  /api/portfolio/funds        → deposit / withdraw virtual cash (paper-only)
  POST  /api/portfolio/reset        → wipe and start over from $10k
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError as PydanticValidationError

from app.models.portfolio import FundsAdjust, TradeCreate
from app.services import portfolio_service
from app.utils.errors import ValidationError

bp = Blueprint("portfolio", __name__)


def _parse_trade(data) -> TradeCreate:
    try:
        return TradeCreate(**(data or {}))
    except PydanticValidationError as e:
        details = {(err["loc"][0] if err["loc"] else "body"): err["msg"] for err in e.errors()}
        raise ValidationError("Invalid request", details=details) from e


def _parse_funds(data) -> FundsAdjust:
    try:
        return FundsAdjust(**(data or {}))
    except PydanticValidationError as e:
        details = {(err["loc"][0] if err["loc"] else "body"): err["msg"] for err in e.errors()}
        raise ValidationError("Invalid request", details=details) from e


@bp.get("/portfolio")
@jwt_required()
def get_portfolio():
    p = portfolio_service.get_portfolio(get_jwt_identity())
    return jsonify(p.model_dump(mode="json"))


@bp.get("/portfolio/history")
@jwt_required()
def get_history():
    range_key = (request.args.get("range") or "3M").upper()
    h = portfolio_service.history(get_jwt_identity(), range_key=range_key)
    return jsonify(h.model_dump(mode="json"))


@bp.get("/portfolio/trades")
@jwt_required()
def list_trades():
    limit = min(int(request.args.get("limit", 200)), 500)
    trades = portfolio_service.list_trades(get_jwt_identity(), limit=limit)
    return jsonify({"trades": [t.model_dump(mode="json") for t in trades]})


@bp.post("/portfolio/buy")
@jwt_required()
def buy():
    payload = _parse_trade(request.get_json(silent=True))
    trade = portfolio_service.buy(get_jwt_identity(), payload.ticker, payload.qty)
    return jsonify({"trade": trade.model_dump(mode="json")}), 201


@bp.post("/portfolio/sell")
@jwt_required()
def sell():
    payload = _parse_trade(request.get_json(silent=True))
    trade = portfolio_service.sell(get_jwt_identity(), payload.ticker, payload.qty)
    return jsonify({"trade": trade.model_dump(mode="json")}), 201


@bp.post("/portfolio/funds")
@jwt_required()
def adjust_funds():
    """Deposit or withdraw virtual USD into/out of the paper portfolio.
    Not linked to the Cash account or the PFM transactions ledger — the
    Funds dialog tells the user this and suggests logging a manual
    transaction if they want the other side of the entry."""
    payload = _parse_funds(request.get_json(silent=True))
    trade = portfolio_service.adjust_funds(
        get_jwt_identity(), payload.direction, payload.amount_usd,
    )
    return jsonify({"trade": trade.model_dump(mode="json")}), 201


@bp.post("/portfolio/reset")
@jwt_required()
def reset():
    p = portfolio_service.reset(get_jwt_identity())
    return jsonify(p.model_dump(mode="json"))
