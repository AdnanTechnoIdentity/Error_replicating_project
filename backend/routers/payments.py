import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from state import app_state

logger = logging.getLogger("nexusshop.payments")
router = APIRouter(prefix="/payments", tags=["payments"])


def _log(level: str, event: str, trace_id: str = "-", **fields) -> None:
    payload = json.dumps({"event": event, "trace_id": trace_id, "service": "payments", **fields}, default=str)
    getattr(logger, level)(payload)


class ChargeRequest(BaseModel):
    amount: float
    currency: str = "USD"
    card_token: str


@router.post("/charge")
async def charge(body: ChargeRequest, request: Request):
    trace_id = getattr(request.state, "trace_id", "-")
    svc = app_state.services["payments"]
    scenario = svc.active_scenario

    _log("info", "charge_attempt", trace_id,
         amount=body.amount, currency=body.currency, active_scenario=scenario)

    if scenario == "api_gateway_timeout":
        _log("error", "charge_blocked_gateway_timeout", trace_id,
             msg="Sleeping 65s — caller gateway will fire at 60s", gateway_timeout_ms=60000)
        await asyncio.sleep(65)

    if scenario == "db_timeout":
        _log("error", "charge_blocked_db_timeout", trace_id,
             db_host="payments-db.internal", timeout_ms=30000,
             msg="DB hang simulated — sleeping 30s then raising 504")
        await asyncio.sleep(30)
        raise HTTPException(status_code=504, detail="Database connection timeout after 30000ms")

    if scenario == "db_pool_exhausted":
        _log("error", "charge_blocked_pool_exhausted", trace_id,
             msg="No DB connection available — pool full (50/50)")
        raise HTTPException(status_code=503, detail="No database connections available")

    if scenario == "payment_failure":
        _log("error", "charge_blocked_gateway_error", trace_id,
             gateway_error="PG_503", msg="Gateway returning PG_503 on all transactions")
        raise HTTPException(
            status_code=500,
            detail={"error": "GATEWAY_REJECTED", "message": "Payment processor unavailable", "code": "PG_503"},
        )

    if scenario == "rate_limit":
        _log("warning", "charge_blocked_rate_limited", trace_id,
             downstream="fraud-check-api", retry_after=60)
        raise HTTPException(status_code=429, detail={"error": "RATE_LIMITED", "retry_after": 60})

    if scenario == "auth_failure":
        _log("error", "charge_blocked_auth_failure", trace_id,
             reason="JWT signature verification failed")
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    if scenario in ("cascade_failure", "disk_full"):
        _log("error", "charge_blocked_scenario", trace_id, scenario=scenario,
             msg=f"Write rejected — active scenario: {scenario}")
        raise HTTPException(status_code=507 if scenario == "disk_full" else 503,
                            detail=f"Service unavailable — {scenario}")

    txn_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
    app_state.transactions[txn_id] = {
        "transaction_id": txn_id,
        "status": "SUCCESS",
        "amount": body.amount,
        "currency": body.currency,
    }
    _log("info", "charge_success", trace_id, transaction_id=txn_id, amount=body.amount)
    return {"transaction_id": txn_id, "status": "SUCCESS"}


@router.get("/status/{transaction_id}")
async def payment_status(transaction_id: str, request: Request):
    trace_id = getattr(request.state, "trace_id", "-")
    svc = app_state.services["payments"]
    if svc.active_scenario == "auth_failure":
        _log("error", "status_blocked_auth_failure", trace_id, transaction_id=transaction_id)
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    txn = app_state.transactions.get(transaction_id)
    if not txn:
        _log("warning", "transaction_not_found", trace_id, transaction_id=transaction_id)
        raise HTTPException(status_code=404, detail="Transaction not found")

    _log("info", "status_fetched", trace_id, transaction_id=transaction_id, status=txn["status"])
    return txn


@router.get("/health")
async def payments_health():
    svc = app_state.services["payments"]
    return {"service": "payments", "status": svc.status, "db_connections": svc.db_connections}
