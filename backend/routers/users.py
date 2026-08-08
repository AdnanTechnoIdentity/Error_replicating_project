import uuid
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from state import app_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest):
    svc = app_state.services["users"]
    if svc.active_scenario == "auth_failure":
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    # Find user by email (demo — no real password check)
    user = next(
        (u for u in app_state.users.values() if u["email"] == body.email),
        None,
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    fake_token = f"eyJ.demo.{uuid.uuid4().hex}"
    return {"token": fake_token, "user_id": user["id"]}


@router.get("/health")
async def users_health():
    svc = app_state.services["users"]
    return {"service": "users", "status": svc.status}


@router.get("/{user_id}")
async def get_user(user_id: str):
    svc = app_state.services["users"]
    if svc.active_scenario == "auth_failure":
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    user = app_state.users.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
