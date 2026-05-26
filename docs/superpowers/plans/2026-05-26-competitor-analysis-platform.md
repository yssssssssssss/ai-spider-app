# 竞品分析平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有截图采集工具基础上，搭建完整的竞品分析平台（数据库、AI分析、前后台Web界面）

**Architecture:** FastAPI后端 + React前后台 + PostgreSQL/pgvector数据库 + LLM分析流水线。采集脚本复用现有uiautomator2逻辑，通过新增入库层持久化。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, PostgreSQL + pgvector, React + Vite, OpenAI/智谱 Embedding API, AutoGLM VLM

---

## 文件结构规划

```
ai-taobao-app/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI入口
│   │   ├── database.py         # SQLAlchemy + pgvector连接
│   │   ├── models.py           # 数据库模型
│   │   ├── schemas.py          # Pydantic schemas
│   │   ├── crud.py             # 数据库CRUD操作
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── requests.py     # 前台需求接口
│   │   │   ├── search.py       # 检索接口
│   │   │   ├── admin.py        # 后台管理接口
│   │   │   └── images.py       # 图片/分析接口
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── llm_analyzer.py # LLM分析服务
│   │   │   ├── embedder.py     # Embedding生成服务
│   │   │   └── collector.py    # 采集任务调度
│   │   └── config.py           # 后端配置
│   ├── requirements.txt
│   └── alembic/                # 数据库迁移
│
├── frontend/                   # React 前端
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api.ts              # API客户端
│       ├── components/
│       │   ├── Layout.tsx
│       │   ├── SearchBox.tsx
│       │   ├── ImageCard.tsx
│       │   └── RequestForm.tsx
│       ├── pages/
│       │   ├── HomePage.tsx    # 前台-需求提交
│       │   ├── SearchPage.tsx  # 前台-检索
│       │   ├── AdminRequests.tsx  # 后台-需求汇总
│       │   ├── AdminTasks.tsx     # 后台-任务管理
│       │   └── AdminDashboard.tsx # 后台-数据看板
│       └── styles/
│           └── index.css
│
├── scripts/
│   └── migrate_images.py       # 存量图片批量入库脚本
│
└── docs/superpowers/specs/
    └── 2026-05-26-competitor-analysis-platform-design.md
```

---

## Task 1: 搭建PostgreSQL + pgvector环境

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/requirements.txt`
- Create: `docker-compose.yml` (可选，如本地无PostgreSQL)

- [ ] **Step 1: 编写后端requirements.txt**

```txt
fastapi==0.111.0
uvicorn[standard]==0.30.0
sqlalchemy==2.0.30
psycopg2-binary==2.9.9
pgvector==0.2.5
pydantic==2.7.0
pydantic-settings==2.2.0
python-multipart==0.0.9
httpx==0.27.0
openai==1.30.0
alembic==1.13.0
python-dotenv==1.0.0
```

- [ ] **Step 2: 编写后端配置 config.py**

```python
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/competitor_db")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIM: int = 1536
    VLM_API_KEY: str = os.getenv("VLM_API_KEY", "")
    VLM_BASE_URL: str = os.getenv("VLM_BASE_URL", "")
    VLM_MODEL: str = os.getenv("VLM_MODEL", "autoglm-phone-9b")
    class Config:
        env_file = ".env"

settings = Settings()
```

- [ ] **Step 3: 编写docker-compose.yml（可选，用于快速启动PostgreSQL）**

```yaml
version: "3.8"
services:
  postgres:
    image: ankane/pgvector:latest
    container_name: competitor_pg
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: competitor_db
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d competitor_db"]
      interval: 5s
      timeout: 5s
      retries: 5
volumes:
  pgdata:
```

- [ ] **Step 4: 启动PostgreSQL并验证**

Run: `docker compose up -d`
Expected: `docker ps` 显示 `competitor_pg` 运行中

- [ ] **Step 5: 在PostgreSQL中启用pgvector扩展**

Run:
```bash
docker exec -it competitor_pg psql -U postgres -d competitor_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```
Expected: `CREATE EXTENSION` 成功

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/config.py docker-compose.yml
git commit -m "feat: add backend deps, config, and PostgreSQL docker setup"
```

---

## Task 2: 数据库模型与SQLAlchemy连接

**Files:**
- Create: `backend/app/database.py`
- Create: `backend/app/models.py`

- [ ] **Step 1: 编写 database.py**

```python
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 启用pgvector扩展
def _enable_pgvector(dbapi_conn, connection_record):
    with dbapi_conn.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")

event.listen(engine, "connect", _enable_pgvector)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 2: 编写 models.py**

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, ARRAY, Enum, Integer
from sqlalchemy.dialects.postgresql import UUID, ARRAY as PGArray
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.database import Base, settings

class Image(Base):
    __tablename__ = "images"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_path = Column(Text, nullable=False)
    source_app = Column(Text)
    scenario = Column(Text)
    captured_at = Column(DateTime)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    task = relationship("Task", back_populates="images")
    analysis = relationship("Analysis", back_populates="image", uselist=False)

class Analysis(Base):
    __tablename__ = "analysis"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), unique=True)
    design_analysis = Column(Text)
    ops_analysis = Column(Text)
    status = Column(String, default="pending")  # pending, success, failed, partial
    analyzed_at = Column(DateTime, nullable=True)
    image = relationship("Image", back_populates="analysis")
    embeddings = relationship("Embedding", back_populates="analysis")

class Request(Base):
    __tablename__ = "requests"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Text, default="anonymous")
    target_app = Column(Text)
    target_scenario = Column(Text)
    keywords = Column(PGArray(Text))
    description = Column(Text)
    status = Column(String, default="pending")  # pending, approved, rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    tasks = relationship("Task", back_populates="request")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("requests.id"), nullable=True)
    name = Column(Text)
    keyword = Column(Text)
    target_app = Column(Text)
    target_scenario = Column(Text)
    status = Column(String, default="pending")  # pending, running, completed, failed
    admin_id = Column(Text, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    request = relationship("Request", back_populates="tasks")
    images = relationship("Image", back_populates="task")

class Embedding(Base):
    __tablename__ = "embeddings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analysis.id"))
    embedding = Column(Vector(settings.EMBEDDING_DIM))
    content_type = Column(Text)  # design, ops, combined
    analysis = relationship("Analysis", back_populates="embeddings")
```

- [ ] **Step 3: 创建表**

Run:
```bash
cd backend && python -c "from app.database import engine, Base; Base.metadata.create_all(bind=engine)"
```
Expected: 无报错，PostgreSQL中创建 `images`, `analysis`, `requests`, `tasks`, `embeddings` 表

- [ ] **Step 4: Commit**

```bash
git add backend/app/database.py backend/app/models.py
git commit -m "feat: add SQLAlchemy models and database connection"
```

---

## Task 3: Pydantic Schemas

**Files:**
- Create: `backend/app/schemas.py`

- [ ] **Step 1: 编写 schemas.py**

```python
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID

class ImageBase(BaseModel):
    file_path: str
    source_app: Optional[str] = None
    scenario: Optional[str] = None
    captured_at: Optional[datetime] = None

class ImageCreate(ImageBase):
    task_id: Optional[UUID] = None

class ImageOut(ImageBase):
    id: UUID
    created_at: datetime
    class Config:
        from_attributes = True

class AnalysisOut(BaseModel):
    id: UUID
    image_id: UUID
    design_analysis: Optional[str] = None
    ops_analysis: Optional[str] = None
    status: str
    analyzed_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class RequestCreate(BaseModel):
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    keywords: List[str] = []
    description: Optional[str] = None

class RequestOut(BaseModel):
    id: UUID
    user_id: str
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    keywords: List[str]
    description: Optional[str] = None
    status: str
    created_at: datetime
    class Config:
        from_attributes = True

class TaskOut(BaseModel):
    id: UUID
    request_id: Optional[UUID] = None
    name: Optional[str] = None
    keyword: Optional[str] = None
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    status: str
    admin_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class SearchQuery(BaseModel):
    query: str
    limit: int = 20
    offset: int = 0

class SearchResult(BaseModel):
    image: ImageOut
    analysis: Optional[AnalysisOut] = None
    similarity: float

class ApproveRequest(BaseModel):
    admin_id: str
    keyword: Optional[str] = None
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None

class RejectRequest(BaseModel):
    admin_id: str
    reason: Optional[str] = None
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas.py
git commit -m "feat: add Pydantic schemas for API validation"
```

---

## Task 4: CRUD操作层

**Files:**
- Create: `backend/app/crud.py`

- [ ] **Step 1: 编写 crud.py**

```python
from uuid import UUID
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from pgvector.sqlalchemy import L2Distance
from app import models, schemas

def create_image(db: Session, image: schemas.ImageCreate) -> models.Image:
    db_image = models.Image(**image.model_dump())
    db.add(db_image)
    db.commit()
    db.refresh(db_image)
    return db_image

def get_image(db: Session, image_id: UUID) -> Optional[models.Image]:
    return db.query(models.Image).filter(models.Image.id == image_id).first()

def list_images(db: Session, skip: int = 0, limit: int = 100) -> List[models.Image]:
    return db.query(models.Image).offset(skip).limit(limit).all()

def create_analysis(db: Session, image_id: UUID, design: str, ops: str) -> models.Analysis:
    db_analysis = models.Analysis(
        image_id=image_id,
        design_analysis=design,
        ops_analysis=ops,
        status="success",
        analyzed_at=func.now()
    )
    db.add(db_analysis)
    db.commit()
    db.refresh(db_analysis)
    return db_analysis

def get_analysis_by_image(db: Session, image_id: UUID) -> Optional[models.Analysis]:
    return db.query(models.Analysis).filter(models.Analysis.image_id == image_id).first()

def create_request(db: Session, req: schemas.RequestCreate) -> models.Request:
    db_req = models.Request(**req.model_dump())
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    return db_req

def get_request(db: Session, request_id: UUID) -> Optional[models.Request]:
    return db.query(models.Request).filter(models.Request.id == request_id).first()

def list_requests(db: Session, status: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[models.Request]:
    q = db.query(models.Request)
    if status:
        q = q.filter(models.Request.status == status)
    return q.offset(skip).limit(limit).all()

def update_request_status(db: Session, request_id: UUID, status: str) -> Optional[models.Request]:
    req = db.query(models.Request).filter(models.Request.id == request_id).first()
    if req:
        req.status = status
        db.commit()
        db.refresh(req)
    return req

def create_task(db: Session, name: str, keyword: str, target_app: Optional[str], target_scenario: Optional[str], request_id: Optional[UUID] = None, admin_id: Optional[str] = None) -> models.Task:
    db_task = models.Task(
        name=name,
        keyword=keyword,
        target_app=target_app,
        target_scenario=target_scenario,
        request_id=request_id,
        admin_id=admin_id,
        status="pending",
        approved_at=func.now() if admin_id else None
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task

def get_task(db: Session, task_id: UUID) -> Optional[models.Task]:
    return db.query(models.Task).filter(models.Task.id == task_id).first()

def list_tasks(db: Session, status: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[models.Task]:
    q = db.query(models.Task)
    if status:
        q = q.filter(models.Task.status == status)
    return q.offset(skip).limit(limit).all()

def update_task_status(db: Session, task_id: UUID, status: str) -> Optional[models.Task]:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.status = status
        if status == "completed":
            task.completed_at = func.now()
        db.commit()
        db.refresh(task)
    return task

def create_embedding(db: Session, analysis_id: UUID, vector: List[float], content_type: str) -> models.Embedding:
    db_emb = models.Embedding(
        analysis_id=analysis_id,
        embedding=vector,
        content_type=content_type
    )
    db.add(db_emb)
    db.commit()
    db.refresh(db_emb)
    return db_emb

def search_by_embedding(db: Session, vector: List[float], limit: int = 20, offset: int = 0) -> List:
    """通过向量相似度搜索，返回 (embedding, analysis, image) 结果"""
    results = db.query(models.Embedding, models.Analysis, models.Image).join(
        models.Analysis, models.Embedding.analysis_id == models.Analysis.id
    ).join(
        models.Image, models.Analysis.image_id == models.Image.id
    ).order_by(
        L2Distance(models.Embedding.embedding, vector)
    ).offset(offset).limit(limit).all()
    return results
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/crud.py
git commit -m "feat: add CRUD layer for all models"
```

---

## Task 5: Embedding服务

**Files:**
- Create: `backend/app/services/embedder.py`

- [ ] **Step 1: 编写 embedder.py**

```python
import httpx
from typing import List
from app.config import settings

class Embedder:
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.base_url = settings.OPENAI_BASE_URL
        self.model = settings.EMBEDDING_MODEL
        self.dim = settings.EMBEDDING_DIM

    async def embed(self, texts: List[str]) -> List[List[float]]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"input": texts, "model": self.model},
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    async def embed_single(self, text: str) -> List[float]:
        results = await self.embed([text])
        return results[0]

embedder = Embedder()
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/embedder.py
git commit -m "feat: add OpenAI embedding service"
```

---

## Task 6: LLM分析服务

**Files:**
- Create: `backend/app/services/llm_analyzer.py`

- [ ] **Step 1: 编写 llm_analyzer.py**

```python
import json
import base64
import httpx
import re
from typing import Optional, Tuple
from app.config import settings

ANALYSIS_PROMPT = """你是一位电商竞品分析专家。请对以下截图进行双维度分析，输出为JSON格式：

{
  "design_analysis": "从UI设计角度分析（布局、配色、视觉层级、信息架构、交互细节等）",
  "ops_analysis": "从运营策略角度分析（促销手段、文案策略、价格策略、用户引导、转化漏斗等）"
}

要求：
- 每个维度200-500字
- 具体指出截图中的设计/运营亮点
- 如果是系列截图，请与前几张做对比分析（如有上下文）
"""

class LLMAnalyzer:
    def __init__(self):
        self.api_key = settings.VLM_API_KEY or settings.OPENAI_API_KEY
        self.base_url = settings.VLM_BASE_URL or settings.OPENAI_BASE_URL
        self.model = settings.VLM_MODEL

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _extract_json(self, text: str) -> Optional[dict]:
        try:
            # 尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 尝试提取markdown代码块中的json
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # 尝试提取花括号包裹的内容
        m = re.search(r'(\{.*"design_analysis".*"ops_analysis".*\})', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return None

    async def analyze(self, image_path: str) -> Tuple[Optional[str], Optional[str], str]:
        """返回 (design_analysis, ops_analysis, status)"""
        base64_image = self._encode_image(image_path)
        messages = [
            {"role": "system", "content": ANALYSIS_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请分析这张电商截图，按要求的JSON格式输出。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }
        ]
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.5,
                    "max_tokens": 2048
                },
                timeout=120.0
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

        parsed = self._extract_json(content)
        if parsed:
            return (
                parsed.get("design_analysis"),
                parsed.get("ops_analysis"),
                "success" if parsed.get("design_analysis") and parsed.get("ops_analysis") else "partial"
            )
        else:
            # 无法解析JSON，将全文作为design_analysis，标记partial
            return (content, None, "partial")

analyzer = LLMAnalyzer()
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/llm_analyzer.py
git commit -m "feat: add VLM-based design and ops analysis service"
```

---

## Task 7: FastAPI主应用与路由

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/app/routers/__init__.py`
- Create: `backend/app/routers/requests.py`
- Create: `backend/app/routers/search.py`
- Create: `backend/app/routers/admin.py`
- Create: `backend/app/routers/images.py`

- [ ] **Step 1: 编写 routers/requests.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app import crud, schemas

router = APIRouter(prefix="/requests", tags=["requests"])

@router.post("", response_model=schemas.RequestOut)
def create_request(req: schemas.RequestCreate, db: Session = Depends(get_db)):
    return crud.create_request(db, req)

@router.get("/{request_id}", response_model=schemas.RequestOut)
def get_request(request_id: UUID, db: Session = Depends(get_db)):
    r = crud.get_request(db, request_id)
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    return r
```

- [ ] **Step 2: 编写 routers/search.py**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app import schemas, crud
from app.services.embedder import embedder

router = APIRouter(prefix="/search", tags=["search"])

@router.post("", response_model=list[schemas.SearchResult])
async def search(query: schemas.SearchQuery, db: Session = Depends(get_db)):
    vector = await embedder.embed_single(query.query)
    rows = crud.search_by_embedding(db, vector, limit=query.limit, offset=query.offset)
    results = []
    for emb, analysis, image in rows:
        similarity = 1.0  # pgvector L2Distance需转换，此处简化
        results.append(schemas.SearchResult(
            image=schemas.ImageOut.model_validate(image),
            analysis=schemas.AnalysisOut.model_validate(analysis) if analysis else None,
            similarity=similarity
        ))
    return results
```

- [ ] **Step 3: 编写 routers/admin.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional
from app.database import get_db
from app import crud, schemas

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/requests", response_model=list[schemas.RequestOut])
def list_requests(status: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_requests(db, status=status, skip=skip, limit=limit)

@router.put("/requests/{request_id}/approve", response_model=schemas.TaskOut)
def approve_request(request_id: UUID, body: schemas.ApproveRequest, db: Session = Depends(get_db)):
    req = crud.get_request(db, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    crud.update_request_status(db, request_id, "approved")
    task = crud.create_task(
        db,
        name=f"Task from request {request_id}",
        keyword=body.keyword or (req.keywords[0] if req.keywords else ""),
        target_app=body.target_app or req.target_app,
        target_scenario=body.target_scenario or req.target_scenario,
        request_id=request_id,
        admin_id=body.admin_id
    )
    return task

@router.put("/requests/{request_id}/reject", response_model=schemas.RequestOut)
def reject_request(request_id: UUID, body: schemas.RejectRequest, db: Session = Depends(get_db)):
    req = crud.update_request_status(db, request_id, "rejected")
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req

@router.get("/tasks", response_model=list[schemas.TaskOut])
def list_tasks(status: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_tasks(db, status=status, skip=skip, limit=limit)

@router.post("/tasks/{task_id}/run", response_model=schemas.TaskOut)
def run_task(task_id: UUID, db: Session = Depends(get_db)):
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # TODO: trigger collector
    crud.update_task_status(db, task_id, "running")
    return task

@router.get("/tasks/{task_id}/progress")
def task_progress(task_id: UUID, db: Session = Depends(get_db)):
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    total = len(task.images)
    analyzed = sum(1 for img in task.images if img.analysis and img.analysis.status in ("success", "partial"))
    return {"task_id": task_id, "total_images": total, "analyzed": analyzed, "status": task.status}
```

- [ ] **Step 4: 编写 routers/images.py**

```python
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app import crud, schemas
from app.services.llm_analyzer import analyzer
from app.services.embedder import embedder

router = APIRouter(prefix="/images", tags=["images"])

async def _analyze_and_embed(image_id: UUID):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        image = crud.get_image(db, image_id)
        if not image:
            return
        design, ops, status = await analyzer.analyze(image.file_path)
        analysis = crud.create_analysis(db, image_id, design or "", ops or "")
        # Update status
        analysis.status = status
        db.commit()
        # Generate embeddings
        combined_text = f"{design or ''}\n{ops or ''}".strip()
        if combined_text:
            vector = await embedder.embed_single(combined_text)
            crud.create_embedding(db, analysis.id, vector, "combined")
        if design:
            v_design = await embedder.embed_single(design)
            crud.create_embedding(db, analysis.id, v_design, "design")
        if ops:
            v_ops = await embedder.embed_single(ops)
            crud.create_embedding(db, analysis.id, v_ops, "ops")
    finally:
        db.close()

@router.post("", response_model=schemas.ImageOut)
def create_image(image: schemas.ImageCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    db_image = crud.create_image(db, image)
    background_tasks.add_task(_analyze_and_embed, db_image.id)
    return db_image

@router.get("/{image_id}", response_model=schemas.ImageOut)
def get_image(image_id: UUID, db: Session = Depends(get_db)):
    img = crud.get_image(db, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    return img

@router.post("/{image_id}/analyze")
def trigger_analyze(image_id: UUID, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    img = crud.get_image(db, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    background_tasks.add_task(_analyze_and_embed, image_id)
    return {"message": "Analysis triggered", "image_id": image_id}
```

- [ ] **Step 5: 编写 main.py**

```python
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
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/app/routers/
git commit -m "feat: add FastAPI app, routers, and background analysis pipeline"
```

---

## Task 8: 存量图片批量入库脚本

**Files:**
- Create: `scripts/migrate_images.py`

- [ ] **Step 1: 编写 migrate_images.py**

```python
import os
import sys
import re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database import SessionLocal
from app import crud, schemas

def extract_app_and_scenario(path: str) -> tuple:
    """从路径推断 source_app 和 scenario"""
    parts = Path(path).parts
    app = "unknown"
    scenario = "unknown"
    for p in parts:
        p_lower = p.lower()
        if "taobao" in p_lower:
            app = "taobao"
        elif "pdd" in p_lower or "pinduoduo" in p_lower:
            app = "pdd"
        if "base" in p_lower:
            scenario = "base"
        elif "cropped" in p_lower or "crop" in p_lower:
            scenario = "cropped"
    return app, scenario

def migrate_folder(folder_path: str, task_id=None):
    db = SessionLocal()
    count = 0
    try:
        for root, _, files in os.walk(folder_path):
            for f in files:
                if not f.lower().endswith((".png", ".jpg", ".jpeg")):
                    continue
                full_path = os.path.join(root, f)
                app, scenario = extract_app_and_scenario(full_path)
                image_in = schemas.ImageCreate(
                    file_path=full_path,
                    source_app=app,
                    scenario=scenario,
                    captured_at=datetime.fromtimestamp(os.path.getmtime(full_path)),
                    task_id=task_id
                )
                crud.create_image(db, image_in)
                count += 1
                print(f"  已入库 [{count}]: {full_path}")
    finally:
        db.close()
    print(f"\n✅ 共入库 {count} 张图片")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        target = os.path.join(os.path.dirname(__file__), "..", "data")
    print(f"📁 开始扫描目录: {target}")
    migrate_folder(target)
```

- [ ] **Step 2: Commit**

```bash
git add scripts/migrate_images.py
git commit -m "feat: add script to batch migrate existing images into database"
```

---

## Task 9: 前端React项目初始化

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`

- [ ] **Step 1: 编写 package.json**

```json
{
  "name": "competitor-analysis-frontend",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.23.0",
    "axios": "^1.7.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0"
  }
}
```

- [ ] **Step 2: 编写 vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  }
})
```

- [ ] **Step 3: 编写 index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>竞品分析平台</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 4: 编写 tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 5: 安装依赖**

Run: `cd frontend && npm install`
Expected: 依赖安装成功

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "feat: initialize React + Vite frontend project"
```

---

## Task 10: 前端核心组件与页面

**Files:**
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/components/Layout.tsx`
- Create: `frontend/src/components/SearchBox.tsx`
- Create: `frontend/src/components/ImageCard.tsx`
- Create: `frontend/src/components/RequestForm.tsx`
- Create: `frontend/src/pages/HomePage.tsx`
- Create: `frontend/src/pages/SearchPage.tsx`
- Create: `frontend/src/pages/AdminRequests.tsx`
- Create: `frontend/src/pages/AdminTasks.tsx`
- Create: `frontend/src/pages/AdminDashboard.tsx`
- Create: `frontend/src/styles/index.css`

- [ ] **Step 1: 编写 api.ts**

```typescript
import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' }
});

export const createRequest = (data: any) => api.post('/requests', data);
export const getRequest = (id: string) => api.get(`/requests/${id}`);
export const searchImages = (data: any) => api.post('/search', data);
export const listAdminRequests = (params?: any) => api.get('/admin/requests', { params });
export const approveRequest = (id: string, data: any) => api.put(`/admin/requests/${id}/approve`, data);
export const rejectRequest = (id: string, data: any) => api.put(`/admin/requests/${id}/reject`, data);
export const listAdminTasks = (params?: any) => api.get('/admin/tasks', { params });
export const runTask = (id: string) => api.post(`/admin/tasks/${id}/run`);
export const getTaskProgress = (id: string) => api.get(`/admin/tasks/${id}/progress`);
export const createImage = (data: any) => api.post('/images', data);

export default api;
```

- [ ] **Step 2: 编写 components/RequestForm.tsx**

```tsx
import { useState } from 'react';
import { createRequest } from '../api';

export default function RequestForm() {
  const [targetApp, setTargetApp] = useState('');
  const [targetScenario, setTargetScenario] = useState('');
  const [keywords, setKeywords] = useState('');
  const [description, setDescription] = useState('');
  const [result, setResult] = useState<any>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const { data } = await createRequest({
      target_app: targetApp,
      target_scenario: targetScenario,
      keywords: keywords.split(',').map(k => k.trim()).filter(Boolean),
      description
    });
    setResult(data);
  };

  return (
    <div>
      <h2>提交竞品搜集需求</h2>
      <form onSubmit={handleSubmit}>
        <div><label>目标App: <input value={targetApp} onChange={e => setTargetApp(e.target.value)} /></label></div>
        <div><label>目标场景: <input value={targetScenario} onChange={e => setTargetScenario(e.target.value)} /></label></div>
        <div><label>关键词(逗号分隔): <input value={keywords} onChange={e => setKeywords(e.target.value)} /></label></div>
        <div><label>补充说明: <textarea value={description} onChange={e => setDescription(e.target.value)} /></label></div>
        <button type="submit">提交需求</button>
      </form>
      {result && <pre>需求ID: {result.id}, 状态: {result.status}</pre>}
    </div>
  );
}
```

- [ ] **Step 3: 编写 components/SearchBox.tsx**

```tsx
import { useState } from 'react';
import { searchImages } from '../api';
import ImageCard from './ImageCard';

export default function SearchBox() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);

  const handleSearch = async () => {
    const { data } = await searchImages({ query, limit: 20 });
    setResults(data);
  };

  return (
    <div>
      <h2>自然语言检索竞品图片</h2>
      <div>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="输入描述，如红色大促弹窗设计" />
        <button onClick={handleSearch}>搜索</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
        {results.map((r, i) => <ImageCard key={i} result={r} />)}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 编写 components/ImageCard.tsx**

```tsx
export default function ImageCard({ result }: { result: any }) {
  return (
    <div style={{ border: '1px solid #ccc', borderRadius: 8, padding: 12 }}>
      <img src={`file://${result.image.file_path}`} alt="竞品截图" style={{ width: '100%', borderRadius: 4 }} />
      <div><strong>App:</strong> {result.image.source_app} | <strong>场景:</strong> {result.image.scenario}</div>
      {result.analysis && (
        <>
          <div><strong>设计分析:</strong> {result.analysis.design_analysis?.slice(0, 200)}...</div>
          <div><strong>运营分析:</strong> {result.analysis.ops_analysis?.slice(0, 200)}...</div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 5: 编写 pages/HomePage.tsx**

```tsx
import RequestForm from '../components/RequestForm';

export default function HomePage() {
  return (
    <div>
      <h1>竞品分析平台 - 前台</h1>
      <RequestForm />
    </div>
  );
}
```

- [ ] **Step 6: 编写 pages/SearchPage.tsx**

```tsx
import SearchBox from '../components/SearchBox';

export default function SearchPage() {
  return (
    <div>
      <h1>检索竞品</h1>
      <SearchBox />
    </div>
  );
}
```

- [ ] **Step 7: 编写 pages/AdminRequests.tsx**

```tsx
import { useEffect, useState } from 'react';
import { listAdminRequests, approveRequest, rejectRequest } from '../api';

export default function AdminRequests() {
  const [requests, setRequests] = useState<any[]>([]);
  const [adminId, setAdminId] = useState('admin');

  const load = async () => {
    const { data } = await listAdminRequests();
    setRequests(data);
  };

  useEffect(() => { load(); }, []);

  const handleApprove = async (id: string) => {
    await approveRequest(id, { admin_id: adminId });
    load();
  };

  const handleReject = async (id: string) => {
    await rejectRequest(id, { admin_id: adminId });
    load();
  };

  return (
    <div>
      <h1>后台 - 需求汇总</h1>
      <table border={1} cellPadding={8}>
        <thead><tr><th>ID</th><th>App</th><th>场景</th><th>关键词</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          {requests.map(r => (
            <tr key={r.id}>
              <td>{r.id.slice(0, 8)}</td>
              <td>{r.target_app}</td>
              <td>{r.target_scenario}</td>
              <td>{r.keywords?.join(', ')}</td>
              <td>{r.status}</td>
              <td>
                {r.status === 'pending' && (
                  <>
                    <button onClick={() => handleApprove(r.id)}>通过</button>
                    <button onClick={() => handleReject(r.id)}>拒绝</button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 8: 编写 pages/AdminTasks.tsx**

```tsx
import { useEffect, useState } from 'react';
import { listAdminTasks, runTask, getTaskProgress } from '../api';

export default function AdminTasks() {
  const [tasks, setTasks] = useState<any[]>([]);

  const load = async () => {
    const { data } = await listAdminTasks();
    setTasks(data);
  };

  useEffect(() => { load(); }, []);

  const handleRun = async (id: string) => {
    await runTask(id);
    load();
  };

  return (
    <div>
      <h1>后台 - 任务管理</h1>
      <table border={1} cellPadding={8}>
        <thead><tr><th>ID</th><th>名称</th><th>关键词</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          {tasks.map(t => (
            <tr key={t.id}>
              <td>{t.id.slice(0, 8)}</td>
              <td>{t.name}</td>
              <td>{t.keyword}</td>
              <td>{t.status}</td>
              <td>
                {t.status === 'pending' && <button onClick={() => handleRun(t.id)}}>启动</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 9: 编写 pages/AdminDashboard.tsx**

```tsx
import { useEffect, useState } from 'react';
import { listAdminRequests, listAdminTasks } from '../api';

export default function AdminDashboard() {
  const [stats, setStats] = useState({ requests: 0, tasks: 0, pendingRequests: 0, pendingTasks: 0 });

  useEffect(() => {
    const load = async () => {
      const [{ data: reqs }, { data: tasks }] = await Promise.all([
        listAdminRequests(),
        listAdminTasks()
      ]);
      setStats({
        requests: reqs.length,
        tasks: tasks.length,
        pendingRequests: reqs.filter((r: any) => r.status === 'pending').length,
        pendingTasks: tasks.filter((t: any) => t.status === 'pending').length
      });
    };
    load();
  }, []);

  return (
    <div>
      <h1>后台 - 数据看板</h1>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <div style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8 }}>
          <h3>总需求数</h3><p>{stats.requests}</p>
        </div>
        <div style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8 }}>
          <h3>总任务数</h3><p>{stats.tasks}</p>
        </div>
        <div style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8 }}>
          <h3>待审核需求</h3><p>{stats.pendingRequests}</p>
        </div>
        <div style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8 }}>
          <h3>待执行任务</h3><p>{stats.pendingTasks}</p>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 10: 编写 App.tsx**

```tsx
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import HomePage from './pages/HomePage';
import SearchPage from './pages/SearchPage';
import AdminRequests from './pages/AdminRequests';
import AdminTasks from './pages/AdminTasks';
import AdminDashboard from './pages/AdminDashboard';

function App() {
  return (
    <BrowserRouter>
      <nav style={{ padding: 12, borderBottom: '1px solid #ccc' }}>
        <Link to="/" style={{ marginRight: 12 }}>前台-需求</Link>
        <Link to="/search" style={{ marginRight: 12 }}>前台-检索</Link>
        <Link to="/admin" style={{ marginRight: 12 }}>后台-看板</Link>
        <Link to="/admin/requests" style={{ marginRight: 12 }}>后台-需求</Link>
        <Link to="/admin/tasks">后台-任务</Link>
      </nav>
      <div style={{ padding: 16 }}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/admin" element={<AdminDashboard />} />
          <Route path="/admin/requests" element={<AdminRequests />} />
          <Route path="/admin/tasks" element={<AdminTasks />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;
```

- [ ] **Step 11: 编写 main.tsx**

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 12: 编写 styles/index.css**

```css
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #f5f5f5;
}
input, textarea, button {
  font-family: inherit;
  font-size: 1rem;
  padding: 8px 12px;
  margin: 4px 0;
  border: 1px solid #ccc;
  border-radius: 4px;
}
button {
  background: #1890ff;
  color: white;
  border: none;
  cursor: pointer;
}
button:hover {
  background: #40a9ff;
}
```

- [ ] **Step 13: Commit**

```bash
git add frontend/src/
git commit -m "feat: add React frontend pages and components"
```

---

## Task 11: 运行验证

- [ ] **Step 1: 启动后端**

Run: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
Expected: FastAPI启动成功，访问 http://localhost:8000/docs 显示Swagger文档

- [ ] **Step 2: 启动前端**

Run: `cd frontend && npm run dev`
Expected: Vite启动成功，访问 http://localhost:5173 显示前台界面

- [ ] **Step 3: 执行存量图片迁移**

Run: `cd scripts && python migrate_images.py ../data`
Expected: 扫描data目录，图片入库成功，可在后台看到记录

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: initial platform setup complete, ready for testing"
```

---

## Spec Coverage Check

| 设计文档章节 | 对应任务 |
|-------------|---------|
| 数据库设计 (§4) | Task 1-2 |
| LLM分析模块 (§5) | Task 6 |
| API设计 (§6) | Task 3-4, 7 |
| 前台界面 (§7.1) | Task 9-10 (HomePage, SearchPage) |
| 后台界面 (§7.2) | Task 10 (AdminRequests, AdminTasks, AdminDashboard) |
| 存量数据迁移 | Task 8 |

---

## 已知简化与后续TODO

1. **图片显示**: 前端使用 `file://` 协议显示本地图片，生产环境需配置静态文件服务或对象存储
2. **相似度计算**: `search.py` 中 similarity 硬编码为1.0，需根据L2Distance换算为真实相似度分数
3. **采集任务调度**: `admin.py` 的 `/tasks/{id}/run` 仅更新状态，实际采集调用需集成 `run_workflow.py`
4. **用户认证**: 当前无登录机制，admin_id由前端传入，生产环境需补充JWT/OAuth
5. **错误处理**: 部分API错误处理可细化，增加全局异常中间件
6. **CORS与安全性**: 当前 `allow_origins=["*"]`，生产环境需收紧
