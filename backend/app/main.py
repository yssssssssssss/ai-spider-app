import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import requests, search, admin, images, watch_plans, auth, worker
from app.config import settings
from app.database import ensure_schema
from app.services.watch_service import start_watch_scheduler

app = FastAPI(title="竞品分析平台", version="1.0.0")
allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:6173,http://127.0.0.1:6173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(requests.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(images.router, prefix="/api")
app.include_router(watch_plans.router, prefix="/api")
app.include_router(worker.router, prefix="/api")

@app.on_event("startup")
def startup():
    ensure_schema()
    start_watch_scheduler()

@app.get("/health")
def health_check():
    return {"status": "ok"}
