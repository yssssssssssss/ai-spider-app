from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import requests, search, admin, images

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

@app.get("/health")
def health_check():
    return {"status": "ok"}
