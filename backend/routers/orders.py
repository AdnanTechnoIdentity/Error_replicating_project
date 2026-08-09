import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List

from state import app_state

logger = logging.getLogger("nexusshop.orders")
router = APIRouter(prefix="/orders", tags=["orders"])


def _log(level: str, event: str, trace_id: str = "-", **fields) -> None:
    payload = json.dumps({"event": event, "trace_id": trace_id, "service": "orders", **fields}, default=str)
    getattr(logger, level)(payload)


class OrderItem(BaseModel):
    sku: str
    qty: int
    price: float


class CreateOrderRequest(BaseModel):
    user_id: str
    items: List[OrderItem]
    total: float


@router.post("/create")
async def create_order(body: CreateOrderRequest, request: Request):
    trace_id = getattr(request.state, "trace_id", "-")
    svc = app_state.services["orders"]
    scenario = svc.active_scenario

    _log("info", "order_attempt", trace_id,
         user_id=body.user_id, item_count=len(body.items), total=body.total,
         active_scenario=scenario)

    if scenario == "auth_failure":
        _log("error", "order_blocked_auth_failure", trace_id,
             reason="JWT signature verification failed")
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    if scenario == "deadlock":
        _log("error", "order_blocked_deadlock", trace_id,
             msg="Write blocked — DB deadlock on orders + inventory tables")
        raise HTTPException(status_code=503, detail="Database deadlock — write operation blocked")

    if scenario == "memory_spike":
        _log("error", "order_blocked_memory_spike", trace_id,
             heap_used_mb=960, heap_max_mb=1024, msg="High memory pressure causing 503")
        raise HTTPException(status_code=503, detail="Service degraded — high memory pressure")

    if scenario == "rate_limit":
        _log("warning", "order_blocked_rate_limited", trace_id,
             downstream="fraud-check-api", retry_after=60)
        raise HTTPException(status_code=429, detail={"error": "RATE_LIMITED", "retry_after": 60})

    if scenario in ("cascade_failure", "disk_full", "cpu_spike"):
        _log("error", "order_blocked_scenario", trace_id, scenario=scenario,
             msg=f"Write rejected — active scenario: {scenario}")
        raise HTTPException(status_code=507 if scenario == "disk_full" else 503,
                            detail=f"Service unavailable — {scenario}")

    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    app_state.orders[order_id] = {
        "order_id": order_id,
        "user_id": body.user_id,
        "status": "CONFIRMED",
        "items": [i.model_dump() for i in body.items],
        "total": body.total,
    }
    _log("info", "order_created", trace_id, order_id=order_id, user_id=body.user_id, total=body.total)
    return {"order_id": order_id, "status": "CONFIRMED"}


@router.get("/health")
async def orders_health():
    svc = app_state.services["orders"]
    return {"service": "orders", "status": svc.status}


@router.get("/{order_id}")
async def get_order(order_id: str, request: Request):
    trace_id = getattr(request.state, "trace_id", "-")
    svc = app_state.services["orders"]
    if svc.active_scenario == "auth_failure":
        _log("error", "get_order_blocked_auth_failure", trace_id, order_id=order_id)
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    order = app_state.orders.get(order_id)
    if not order:
        _log("warning", "order_not_found", trace_id, order_id=order_id)
        raise HTTPException(status_code=404, detail="Order not found")

    _log("info", "order_fetched", trace_id, order_id=order_id, status=order["status"])
    return order
