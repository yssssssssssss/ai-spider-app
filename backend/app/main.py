import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.routers import requests, search, admin, images
from app.config import settings

app = FastAPI(title="竞品分析平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(requests.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(images.router, prefix="/api")

# 静态文件服务：将项目根目录下的图片通过 /static 提供访问
app.mount("/static", StaticFiles(directory=settings.PROJECT_ROOT), name="static")

@app.get("/health")
def health_check():
    return {"status": "ok"}
