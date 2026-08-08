import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from state import app_state
from routers import payments, orders, users
from chaos.controller import router as chaos_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

app = FastAPI(title="NexusShop Demo API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(payments.router)
app.include_router(orders.router)
app.include_router(users.router)
app.include_router(chaos_router)


@app.get("/state")
async def get_state():
    return app_state.to_dict()


@app.get("/health")
async def root_health():
    return {"status": "ok", "app": "NexusShop"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "9000")),
        reload=False,
    )
