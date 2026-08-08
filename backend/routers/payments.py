import asyncio
import uuid
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from state import app_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])


class ChargeRequest(BaseModel):
    amount: float
    currency: str = "USD"
    card_token: str


@router.post("/charge")
async def charge(body: ChargeRequest):
    svc = app_state.services["payments"]
    scenario = svc.active_scenario

    if scenario == "api_gateway_timeout":
        await asyncio.sleep(65)

    if scenario == "db_timeout":
        await asyncio.sleep(30)
        raise HTTPException(status_code=504, detail="Database connection timeout after 30000ms")

    if scenario in ("db_pool_exhausted",):
        raise HTTPException(status_code=503, detail="No database connections available")

    if scenario == "payment_failure":
        raise HTTPException(
            status_code=500,
            detail={"error": "GATEWAY_REJECTED", "message": "Payment processor unavailable", "code": "PG_503"},
        )

    if scenario == "rate_limit":
        raise HTTPException(
            status_code=429,
            detail={"error": "RATE_LIMITED", "retry_after": 60},
        )

    if scenario == "auth_failure":
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    txn_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
    app_state.transactions[txn_id] = {
        "transaction_id": txn_id,
        "status": "SUCCESS",
        "amount": body.amount,
        "currency": body.currency,
    }
    return {"transaction_id": txn_id, "status": "SUCCESS"}


@router.get("/status/{transaction_id}")
async def payment_status(transaction_id: str):
    svc = app_state.services["payments"]
    if svc.active_scenario == "auth_failure":
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    txn = app_state.transactions.get(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


@router.get("/health")
async def payments_health():
    svc = app_state.services["payments"]
    return {
        "service": "payments",
        "status": svc.status,
        "db_connections": svc.db_connections,
    }
