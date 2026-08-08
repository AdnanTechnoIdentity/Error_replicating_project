import uuid
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any

from state import app_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["orders"])


class OrderItem(BaseModel):
    sku: str
    qty: int
    price: float


class CreateOrderRequest(BaseModel):
    user_id: str
    items: List[OrderItem]
    total: float


@router.post("/create")
async def create_order(body: CreateOrderRequest):
    svc = app_state.services["orders"]
    scenario = svc.active_scenario

    if scenario == "auth_failure":
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    if scenario == "deadlock":
        raise HTTPException(status_code=503, detail="Database deadlock — write operation blocked")

    if scenario == "memory_spike":
        raise HTTPException(status_code=503, detail="Service degraded — high memory pressure")

    if scenario == "rate_limit":
        raise HTTPException(
            status_code=429,
            detail={"error": "RATE_LIMITED", "retry_after": 60},
        )

    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    app_state.orders[order_id] = {
        "order_id": order_id,
        "user_id": body.user_id,
        "status": "CONFIRMED",
        "items": [i.model_dump() for i in body.items],
        "total": body.total,
    }
    return {"order_id": order_id, "status": "CONFIRMED"}


@router.get("/health")
async def orders_health():
    svc = app_state.services["orders"]
    return {"service": "orders", "status": svc.status}


@router.get("/{order_id}")
async def get_order(order_id: str):
    svc = app_state.services["orders"]
    if svc.active_scenario == "auth_failure":
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    order = app_state.orders.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
