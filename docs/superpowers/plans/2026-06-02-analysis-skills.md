# Analysis Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build configurable analysis skills so users can create Markdown-based dimensions, bind selected dimensions to new requests and watch plans, and analyze future screenshots with those exact skill snapshots.

**Architecture:** Add an `analysis_skills` table for reusable skill definitions, store immutable skill snapshots on requests/tasks/watch plans, and store dynamic per-skill results in `analysis.custom_analysis_json`. Keep `design_analysis` and `ops_analysis` as compatibility fields so existing search, exports, reports, and UI paths do not break while new results render dynamically.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL JSONB, Pydantic, React 18, TypeScript, Axios, existing unittest regression suite.

---

## File Structure

Backend model and schema changes:

- Modify `backend/app/models.py`: add `AnalysisSkill`, `custom_analysis_json`, and skill snapshot columns on `Request`, `Task`, and `WatchPlan`.
- Modify `backend/app/database.py`: add `ensure_schema` columns, indexes, and default official skills.
- Modify `backend/app/schemas.py`: add skill request/response schemas and expose dynamic analysis fields.
- Modify `backend/app/crud.py`: add skill CRUD helpers, snapshot builders, request/task/watch plan snapshot persistence, dynamic analysis helpers, and dynamic search text support.

Backend API and services:

- Create `backend/app/services/analysis_skills.py`: parse Markdown, validate selections, build snapshots, extract dynamic analysis text.
- Create `backend/app/routers/analysis_skills.py`: user and admin skill endpoints.
- Modify `backend/app/main.py`: include the analysis skill router.
- Modify `backend/app/routers/requests.py`: bind skill snapshots at request creation.
- Modify `backend/app/routers/watch_plans.py`: bind skill snapshots at watch plan creation.
- Modify `backend/app/routers/admin.py`: copy request snapshots to tasks and expose snapshots in task/request output.
- Modify `backend/app/services/llm_analyzer.py`: accept skill snapshots and return dynamic results.
- Modify `backend/app/routers/images.py`: analyze using task/watch plan snapshots, write dynamic JSON, embed all dynamic text.
- Modify `backend/app/backfill_embeddings.py`: use dynamic result text when present.
- Modify `backend/app/services/exporter.py`: export dynamic skill results.
- Modify `backend/app/services/watch_reporter.py`: include multi-dimensional analysis in watch summaries.
- Modify `backend/app/services/goal_validator.py`: use dynamic result text as evidence.

Frontend:

- Modify `frontend/src/api.ts`: add skill API client functions.
- Modify `frontend/src/App.tsx`: add “分析 skill” route and navigation entry.
- Create `frontend/src/components/AnalysisSkillSelector.tsx`: reusable selector for request and watch plan forms.
- Create `frontend/src/pages/AnalysisSkillsPage.tsx`: skill management page.
- Modify `frontend/src/components/RequestForm.tsx`: include selected `analysis_skill_ids`.
- Modify `frontend/src/components/WatchPlanForm.tsx`: include selected `analysis_skill_ids`.
- Modify `frontend/src/pages/AdminRequests.tsx`: display bound skill snapshot names for review.
- Modify `frontend/src/components/ImageCard.tsx`: render dynamic analysis results when present.
- Modify `frontend/src/styles/index.css`: add compact skill management and selector styles.

Tests:

- Modify `backend/tests/test_flow_regressions.py`: add backend regression tests for skill CRUD, permissions, snapshots, dynamic analysis parsing, search, exports, and embedding text.

---

### Task 1: Data Model, Schema, and Default Official Skills

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_flow_regressions.py`

- [ ] **Step 1: Write failing model/schema tests**

Append these tests inside `FlowRegressionTests` in `backend/tests/test_flow_regressions.py`:

```python
    def test_analysis_skill_model_and_snapshot_fields_exist(self):
        from app import models
        from app.schemas import AnalysisOut, RequestCreate, RequestOut, TaskOut, WatchPlanCreate, WatchPlanOut

        self.assertTrue(hasattr(models, "AnalysisSkill"))
        self.assertTrue(hasattr(models.Analysis, "custom_analysis_json"))
        self.assertTrue(hasattr(models.Request, "analysis_skill_snapshots_json"))
        self.assertTrue(hasattr(models.Task, "analysis_skill_snapshots_json"))
        self.assertTrue(hasattr(models.WatchPlan, "analysis_skill_snapshots_json"))
        self.assertIn("custom_analysis_json", AnalysisOut.model_fields)
        self.assertIn("analysis_skill_ids", RequestCreate.model_fields)
        self.assertIn("analysis_skill_snapshots_json", RequestOut.model_fields)
        self.assertIn("analysis_skill_snapshots_json", TaskOut.model_fields)
        self.assertIn("analysis_skill_ids", WatchPlanCreate.model_fields)
        self.assertIn("analysis_skill_snapshots_json", WatchPlanOut.model_fields)
```

- [ ] **Step 2: Run the targeted failing test**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py -k test_analysis_skill_model_and_snapshot_fields_exist
```

Expected: FAIL because `AnalysisSkill` and the new fields do not exist yet.

- [ ] **Step 3: Add model fields**

In `backend/app/models.py`, add the `AnalysisSkill` model after `AppSetting`:

```python
class AnalysisSkill(Base):
    __tablename__ = "analysis_skills"
    __table_args__ = (
        Index("ix_analysis_skills_owner_status", "owner_id", "status"),
        Index("ix_analysis_skills_official_status", "is_official", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    instruction_md = Column(Text, nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    is_official = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    owner = relationship("User")
```

In the existing `Analysis` model, add:

```python
    custom_analysis_json = Column(JSONB, default=dict)
```

In the existing `Request`, `Task`, and `WatchPlan` models, add:

```python
    analysis_skill_snapshots_json = Column(JSONB, default=list)
```

- [ ] **Step 4: Extend schemas**

In `backend/app/schemas.py`, add these classes after `RegistrationInviteCodeUpdate`:

```python
class AnalysisSkillBase(BaseModel):
    name: str
    instruction_md: str


class AnalysisSkillCreate(AnalysisSkillBase):
    pass


class AnalysisSkillUpdate(BaseModel):
    name: Optional[str] = None
    instruction_md: Optional[str] = None
    status: Optional[str] = None
    is_official: Optional[bool] = None


class AnalysisSkillOut(AnalysisSkillBase, OrmModel):
    id: UUID
    owner_id: Optional[UUID] = None
    owner_name: Optional[str] = None
    is_official: bool
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class AnalysisSkillUploadOut(BaseModel):
    name: str
    instruction_md: str


class AnalysisSkillOfficialUpdate(BaseModel):
    is_official: bool
```

Update `AnalysisOut` with:

```python
    custom_analysis_json: dict | list | None = None
```

Update `RequestCreate` with:

```python
    analysis_skill_ids: List[UUID] = Field(default_factory=list)
```

Update `RequestOut`, `TaskOut`, and `WatchPlanOut` with:

```python
    analysis_skill_snapshots_json: list | dict | None = None
```

Update `WatchPlanCreate` with:

```python
    analysis_skill_ids: List[UUID] = Field(default_factory=list)
```

- [ ] **Step 5: Add schema bootstrap and default official skills**

In `backend/app/database.py`, add constants near the top:

```python
DEFAULT_ANALYSIS_SKILLS = (
    (
        "设计维度",
        "# 设计维度\n从 UI 设计角度分析截图中的布局、配色、视觉层级、信息架构、组件密度、交互提示和可读性。请指出具体画面证据。",
    ),
    (
        "运营维度",
        "# 运营维度\n从运营策略角度分析截图中的促销机制、文案策略、价格策略、用户引导、转化路径、活动利益点和紧迫感营造。请指出具体画面证据。",
    ),
)
```

Add this helper before `ensure_schema()`:

```python
def _ensure_default_analysis_skills(conn):
    for name, instruction_md in DEFAULT_ANALYSIS_SKILLS:
        existing = conn.execute(
            text("""
                SELECT id FROM analysis_skills
                WHERE name = :name AND is_official = true
            """),
            {"name": name},
        ).first()
        if existing:
            continue
        conn.execute(
            text("""
                INSERT INTO analysis_skills
                    (id, name, instruction_md, owner_id, is_official, status, created_at, updated_at)
                VALUES
                    (:id, :name, :instruction_md, NULL, true, 'active', now(), now())
            """),
            {"id": str(uuid.uuid4()), "name": name, "instruction_md": instruction_md},
        )
```

Inside `ensure_schema()`, add:

```python
        if "analysis" in tables:
            _ensure_column(conn, inspector, "analysis", "custom_analysis_json", "JSONB DEFAULT '{}'::jsonb")
```

Add snapshot columns:

```python
        if "requests" in tables:
            _ensure_column(conn, inspector, "requests", "analysis_skill_snapshots_json", "JSONB DEFAULT '[]'::jsonb")
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requests_user_id ON requests(user_id)"))
        if "tasks" in tables:
            _ensure_column(conn, inspector, "tasks", "analysis_skill_snapshots_json", "JSONB DEFAULT '[]'::jsonb")
        if "watch_plans" in tables:
            _ensure_column(conn, inspector, "watch_plans", "analysis_skill_snapshots_json", "JSONB DEFAULT '[]'::jsonb")
```

After `if "app_settings" in tables:` block, add:

```python
        if "analysis_skills" in tables:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analysis_skills_owner_status ON analysis_skills(owner_id, status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analysis_skills_official_status ON analysis_skills(is_official, status)"))
            _ensure_default_analysis_skills(conn)
```

- [ ] **Step 6: Run the targeted test**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py -k test_analysis_skill_model_and_snapshot_fields_exist
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/database.py backend/app/schemas.py backend/tests/test_flow_regressions.py
git commit -m "feat: add analysis skill data model"
```

---

### Task 2: Skill Parsing, CRUD, Permissions, and API

**Files:**
- Create: `backend/app/services/analysis_skills.py`
- Create: `backend/app/routers/analysis_skills.py`
- Modify: `backend/app/crud.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_flow_regressions.py`

- [ ] **Step 1: Write failing service and API tests**

Append these tests to `FlowRegressionTests`:

```python
    def test_parse_analysis_skill_markdown_uses_h1_as_name(self):
        from app.services.analysis_skills import parse_skill_markdown

        parsed = parse_skill_markdown("# 价格策略\n\n分析价格锚点、补贴、满减。")

        self.assertEqual(parsed["name"], "价格策略")
        self.assertIn("分析价格锚点", parsed["instruction_md"])

    def test_parse_analysis_skill_markdown_requires_name_without_h1(self):
        from app.services.analysis_skills import parse_skill_markdown

        parsed = parse_skill_markdown("分析会员价和限时价。", fallback_name="价格策略")

        self.assertEqual(parsed["name"], "价格策略")
        self.assertEqual(parsed["instruction_md"], "分析会员价和限时价。")

    def test_user_can_create_and_list_own_analysis_skill(self):
        from app import crud, models
        from app.database import SessionLocal
        from app.services.auth import hash_password

        db = SessionLocal()
        username = f"skill-user-{uuid4().hex[:8]}"
        try:
            user = crud.create_user(db, username=username, password_hash=hash_password("pass"), role="viewer")
            skill = crud.create_analysis_skill(
                db,
                name="价格策略",
                instruction_md="# 价格策略\n分析价格。",
                owner_id=user.id,
            )

            rows = crud.list_visible_analysis_skills(db, user)

            self.assertIn(skill.id, [row.id for row in rows])
        finally:
            db.query(models.AnalysisSkill).filter(models.AnalysisSkill.name == "价格策略").delete()
            db.query(models.User).filter(models.User.username == username).delete()
            db.commit()
            db.close()

    def test_admin_can_mark_analysis_skill_official(self):
        from app import crud, models
        from app.database import SessionLocal
        from app.services.auth import hash_password

        db = SessionLocal()
        username = f"skill-admin-{uuid4().hex[:8]}"
        try:
            user = crud.create_user(db, username=username, password_hash=hash_password("pass"), role="admin")
            skill = crud.create_analysis_skill(
                db,
                name="价格策略",
                instruction_md="# 价格策略\n分析价格。",
                owner_id=user.id,
            )

            updated = crud.update_analysis_skill(db, skill.id, is_official=True)

            self.assertTrue(updated.is_official)
        finally:
            db.query(models.AnalysisSkill).filter(models.AnalysisSkill.name == "价格策略").delete()
            db.query(models.User).filter(models.User.username == username).delete()
            db.commit()
            db.close()
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py -k "analysis_skill"
```

Expected: FAIL because service and CRUD functions do not exist.

- [ ] **Step 3: Implement Markdown parsing and selection helpers**

Create `backend/app/services/analysis_skills.py`:

```python
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import crud, models

MAX_SKILL_MARKDOWN_LENGTH = 20_000
DEFAULT_SKILL_NAMES = {"设计维度", "运营维度"}


def parse_skill_markdown(content: str, fallback_name: str | None = None) -> dict[str, str]:
    text = (content or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Skill markdown is required")
    if len(text) > MAX_SKILL_MARKDOWN_LENGTH:
        raise HTTPException(status_code=400, detail="Skill markdown is too long")
    name = (fallback_name or "").strip()
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        name = lines[0][2:].strip()
    if not name:
        raise HTTPException(status_code=400, detail="Skill name is required")
    return {"name": name, "instruction_md": text}


def is_custom_skill_snapshot(snapshot: dict) -> bool:
    return not snapshot.get("is_official") and snapshot.get("name") not in DEFAULT_SKILL_NAMES


def validate_skill_selection(snapshots: list[dict]):
    if not snapshots:
        raise HTTPException(status_code=400, detail="Select at least one analysis skill")
    has_custom = any(is_custom_skill_snapshot(snapshot) for snapshot in snapshots)
    if has_custom:
        return
    has_default = any(snapshot.get("name") in DEFAULT_SKILL_NAMES for snapshot in snapshots)
    if not has_default:
        raise HTTPException(status_code=400, detail="Select at least one default analysis skill")


def build_skill_snapshots(db: Session, skill_ids: list[UUID], user: models.User) -> list[dict]:
    skills = crud.get_selectable_analysis_skills(db, skill_ids, user)
    found_ids = {skill.id for skill in skills}
    missing = [skill_id for skill_id in skill_ids if skill_id not in found_ids]
    if missing:
        raise HTTPException(status_code=400, detail="Analysis skill is unavailable")
    snapshots = [
        {
            "skill_id": str(skill.id),
            "name": skill.name,
            "instruction_md": skill.instruction_md,
            "is_official": bool(skill.is_official),
        }
        for skill in skills
    ]
    validate_skill_selection(snapshots)
    return snapshots
```

- [ ] **Step 4: Add CRUD helpers**

In `backend/app/crud.py`, add:

```python
def create_analysis_skill(
    db: Session,
    *,
    name: str,
    instruction_md: str,
    owner_id: Optional[UUID],
    is_official: bool = False,
    status: str = "active",
) -> models.AnalysisSkill:
    skill = models.AnalysisSkill(
        name=name.strip(),
        instruction_md=instruction_md.strip(),
        owner_id=owner_id,
        is_official=is_official,
        status=status,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def get_analysis_skill(db: Session, skill_id: UUID) -> Optional[models.AnalysisSkill]:
    return db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill_id).first()


def list_visible_analysis_skills(db: Session, user: models.User) -> List[models.AnalysisSkill]:
    return (
        db.query(models.AnalysisSkill)
        .filter(models.AnalysisSkill.status == "active")
        .filter(or_(models.AnalysisSkill.owner_id == user.id, models.AnalysisSkill.is_official.is_(True)))
        .order_by(models.AnalysisSkill.is_official.desc(), models.AnalysisSkill.updated_at.desc().nullslast())
        .all()
    )


def list_all_analysis_skills(db: Session) -> List[models.AnalysisSkill]:
    return db.query(models.AnalysisSkill).order_by(models.AnalysisSkill.updated_at.desc().nullslast()).all()


def get_selectable_analysis_skills(db: Session, skill_ids: list[UUID], user: models.User) -> List[models.AnalysisSkill]:
    if not skill_ids:
        return []
    return (
        db.query(models.AnalysisSkill)
        .filter(models.AnalysisSkill.id.in_(skill_ids))
        .filter(models.AnalysisSkill.status == "active")
        .filter(or_(models.AnalysisSkill.owner_id == user.id, models.AnalysisSkill.is_official.is_(True)))
        .all()
    )


def update_analysis_skill(
    db: Session,
    skill_id: UUID,
    *,
    name: Optional[str] = None,
    instruction_md: Optional[str] = None,
    status: Optional[str] = None,
    is_official: Optional[bool] = None,
) -> Optional[models.AnalysisSkill]:
    skill = get_analysis_skill(db, skill_id)
    if not skill:
        return None
    if name is not None:
        skill.name = name.strip()
    if instruction_md is not None:
        skill.instruction_md = instruction_md.strip()
    if status is not None:
        skill.status = status
    if is_official is not None:
        skill.is_official = is_official
    skill.updated_at = datetime.now()
    db.commit()
    db.refresh(skill)
    return skill
```

- [ ] **Step 5: Add skill router**

Create `backend/app/routers/analysis_skills.py`:

```python
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.services.analysis_skills import parse_skill_markdown
from app.services.auth import get_current_user, require_roles

router = APIRouter(tags=["analysis-skills"])


def _skill_out(db: Session, skill: models.AnalysisSkill) -> schemas.AnalysisSkillOut:
    data = schemas.AnalysisSkillOut.model_validate(skill).model_dump()
    owner = crud.get_user(db, skill.owner_id) if skill.owner_id else None
    data["owner_name"] = (owner.display_name or owner.username) if owner else None
    return schemas.AnalysisSkillOut.model_validate(data)


def _own_editable_skill(db: Session, skill_id: UUID, user: models.User) -> models.AnalysisSkill:
    skill = crud.get_analysis_skill(db, skill_id)
    if not skill or skill.owner_id != user.id or skill.is_official:
        raise HTTPException(status_code=404, detail="Analysis skill not found")
    return skill


@router.get("/analysis-skills", response_model=list[schemas.AnalysisSkillOut])
def list_analysis_skills(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return [_skill_out(db, skill) for skill in crud.list_visible_analysis_skills(db, user)]


@router.post("/analysis-skills", response_model=schemas.AnalysisSkillOut)
def create_analysis_skill(body: schemas.AnalysisSkillCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    parsed = parse_skill_markdown(body.instruction_md, fallback_name=body.name)
    skill = crud.create_analysis_skill(db, name=parsed["name"], instruction_md=parsed["instruction_md"], owner_id=user.id)
    return _skill_out(db, skill)


@router.post("/analysis-skills/upload-md", response_model=schemas.AnalysisSkillUploadOut)
async def upload_analysis_skill_md(file: UploadFile = File(...), user: models.User = Depends(get_current_user)):
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="Only .md files are supported")
    data = await file.read(20_001)
    text = data.decode("utf-8")
    parsed = parse_skill_markdown(text)
    return schemas.AnalysisSkillUploadOut(**parsed)


@router.patch("/analysis-skills/{skill_id}", response_model=schemas.AnalysisSkillOut)
def update_analysis_skill(skill_id: UUID, body: schemas.AnalysisSkillUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _own_editable_skill(db, skill_id, user)
    parsed = None
    if body.instruction_md is not None or body.name is not None:
        current = crud.get_analysis_skill(db, skill_id)
        parsed = parse_skill_markdown(body.instruction_md or current.instruction_md, fallback_name=body.name or current.name)
    skill = crud.update_analysis_skill(
        db,
        skill_id,
        name=parsed["name"] if parsed else None,
        instruction_md=parsed["instruction_md"] if parsed else None,
        status=body.status,
    )
    return _skill_out(db, skill)


@router.delete("/analysis-skills/{skill_id}", response_model=schemas.AnalysisSkillOut)
def delete_analysis_skill(skill_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _own_editable_skill(db, skill_id, user)
    skill = crud.update_analysis_skill(db, skill_id, status="disabled")
    return _skill_out(db, skill)


@router.get("/admin/analysis-skills", response_model=list[schemas.AnalysisSkillOut])
def list_admin_analysis_skills(db: Session = Depends(get_db), _: models.User = Depends(require_roles("admin"))):
    return [_skill_out(db, skill) for skill in crud.list_all_analysis_skills(db)]


@router.patch("/admin/analysis-skills/{skill_id}", response_model=schemas.AnalysisSkillOut)
def admin_update_analysis_skill(skill_id: UUID, body: schemas.AnalysisSkillUpdate, db: Session = Depends(get_db), _: models.User = Depends(require_roles("admin"))):
    current = crud.get_analysis_skill(db, skill_id)
    if not current:
        raise HTTPException(status_code=404, detail="Analysis skill not found")
    parsed = None
    if body.instruction_md is not None or body.name is not None:
        parsed = parse_skill_markdown(body.instruction_md or current.instruction_md, fallback_name=body.name or current.name)
    skill = crud.update_analysis_skill(
        db,
        skill_id,
        name=parsed["name"] if parsed else None,
        instruction_md=parsed["instruction_md"] if parsed else None,
        status=body.status,
        is_official=body.is_official,
    )
    return _skill_out(db, skill)


@router.delete("/admin/analysis-skills/{skill_id}", response_model=schemas.AnalysisSkillOut)
def admin_delete_analysis_skill(skill_id: UUID, db: Session = Depends(get_db), _: models.User = Depends(require_roles("admin"))):
    skill = crud.update_analysis_skill(db, skill_id, status="disabled")
    if not skill:
        raise HTTPException(status_code=404, detail="Analysis skill not found")
    return _skill_out(db, skill)


@router.patch("/admin/analysis-skills/{skill_id}/official", response_model=schemas.AnalysisSkillOut)
def admin_set_analysis_skill_official(skill_id: UUID, body: schemas.AnalysisSkillOfficialUpdate, db: Session = Depends(get_db), _: models.User = Depends(require_roles("admin"))):
    skill = crud.update_analysis_skill(db, skill_id, is_official=body.is_official)
    if not skill:
        raise HTTPException(status_code=404, detail="Analysis skill not found")
    return _skill_out(db, skill)
```

- [ ] **Step 6: Include the router**

In `backend/app/main.py`, import and include:

```python
from app.routers import analysis_skills

app.include_router(analysis_skills.router, prefix="/api")
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py -k "analysis_skill"
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/analysis_skills.py backend/app/routers/analysis_skills.py backend/app/crud.py backend/app/main.py backend/tests/test_flow_regressions.py
git commit -m "feat: add analysis skill API"
```

---

### Task 3: Bind Skill Snapshots to Requests, Tasks, and Watch Plans

**Files:**
- Modify: `backend/app/crud.py`
- Modify: `backend/app/routers/requests.py`
- Modify: `backend/app/routers/admin.py`
- Modify: `backend/app/routers/watch_plans.py`
- Modify: `backend/tests/test_flow_regressions.py`

- [ ] **Step 1: Write failing snapshot tests**

Append:

```python
    def test_request_creation_stores_analysis_skill_snapshots(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services.auth import hash_password
        from app.services.analysis_skills import build_skill_snapshots

        db = SessionLocal()
        username = f"snapshot-user-{uuid4().hex[:8]}"
        try:
            user = crud.create_user(db, username=username, password_hash=hash_password("pass"), role="viewer")
            skill = crud.create_analysis_skill(db, name="价格策略", instruction_md="# 价格策略\n分析价格。", owner_id=user.id)
            snapshots = build_skill_snapshots(db, [skill.id], user)
            req = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="搜索页", keywords=[], description="", analysis_skill_ids=[skill.id]),
                user_id=str(user.id),
                analysis_skill_snapshots=snapshots,
            )

            self.assertEqual(req.analysis_skill_snapshots_json[0]["name"], "价格策略")
        finally:
            db.query(models.Request).filter(models.Request.user_id == str(user.id)).delete()
            db.query(models.AnalysisSkill).filter(models.AnalysisSkill.name == "价格策略").delete()
            db.query(models.User).filter(models.User.username == username).delete()
            db.commit()
            db.close()

    def test_approve_request_copies_analysis_skill_snapshots_to_task(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services.auth import hash_password

        db = SessionLocal()
        username = f"copy-snapshot-{uuid4().hex[:8]}"
        try:
            user = crud.create_user(db, username=username, password_hash=hash_password("pass"), role="viewer")
            req = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="搜索页", keywords=[], description=""),
                user_id=str(user.id),
                analysis_skill_snapshots=[{"skill_id": "x", "name": "价格策略", "instruction_md": "# 价格策略", "is_official": False}],
            )
            task = crud.create_task(
                db,
                name="Task",
                keyword="",
                target_app="淘宝",
                target_scenario="搜索页",
                request_id=req.id,
                analysis_skill_snapshots=req.analysis_skill_snapshots_json,
            )

            self.assertEqual(task.analysis_skill_snapshots_json[0]["name"], "价格策略")
        finally:
            db.query(models.Task).delete()
            db.query(models.Request).filter(models.Request.user_id == str(user.id)).delete()
            db.query(models.User).filter(models.User.username == username).delete()
            db.commit()
            db.close()
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py -k "snapshot"
```

Expected: FAIL because `create_request` and `create_task` do not accept `analysis_skill_snapshots`.

- [ ] **Step 3: Persist snapshots in CRUD**

Update `crud.create_request` signature:

```python
def create_request(
    db: Session,
    req: schemas.RequestCreate,
    user_id: Optional[str] = None,
    analysis_skill_snapshots: Optional[list[dict]] = None,
) -> models.Request:
```

Inside it, after `data = req.model_dump()`, add:

```python
    data.pop("analysis_skill_ids", None)
    data["analysis_skill_snapshots_json"] = analysis_skill_snapshots or []
```

Update `crud.create_task` signature:

```python
    analysis_skill_snapshots: Optional[list[dict]] = None,
```

When constructing `models.Task`, add:

```python
        analysis_skill_snapshots_json=analysis_skill_snapshots or [],
```

Update `crud.create_watch_plan` signature and body to accept `analysis_skill_snapshots`:

```python
def create_watch_plan(
    db: Session,
    plan: schemas.WatchPlanCreate,
    created_by: Optional[UUID] = None,
    analysis_skill_snapshots: Optional[list[dict]] = None,
) -> models.WatchPlan:
```

Use:

```python
    data = plan.model_dump()
    data.pop("analysis_skill_ids", None)
    db_plan = models.WatchPlan(**data, created_by=created_by, analysis_skill_snapshots_json=analysis_skill_snapshots or [])
```

- [ ] **Step 4: Build snapshots in request and watch plan routers**

In `backend/app/routers/requests.py`, import:

```python
from app.services.analysis_skills import build_skill_snapshots
```

Update `create_request`:

```python
@router.post("", response_model=schemas.RequestOut)
def create_request(req: schemas.RequestCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    snapshots = build_skill_snapshots(db, req.analysis_skill_ids, user)
    return crud.create_request(db, req, user_id=str(user.id), analysis_skill_snapshots=snapshots)
```

In `backend/app/routers/watch_plans.py`, import `build_skill_snapshots` and update `create_watch_plan`:

```python
@router.post("/watch-plans", response_model=schemas.WatchPlanOut)
def create_watch_plan(body: schemas.WatchPlanCreate, db: Session = Depends(get_db), user: models.User = Depends(require_at_least("operator"))):
    snapshots = build_skill_snapshots(db, body.analysis_skill_ids, user)
    return crud.create_watch_plan(db, body, created_by=user.id, analysis_skill_snapshots=snapshots)
```

- [ ] **Step 5: Copy request snapshots to tasks**

In `backend/app/routers/admin.py`, update `crud.create_task(...)` inside `approve_request`:

```python
        analysis_skill_snapshots=req.analysis_skill_snapshots_json or [],
```

- [ ] **Step 6: Run snapshot tests**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py -k "snapshot"
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/crud.py backend/app/routers/requests.py backend/app/routers/admin.py backend/app/routers/watch_plans.py backend/tests/test_flow_regressions.py
git commit -m "feat: bind analysis skill snapshots"
```

---

### Task 4: Dynamic LLM Analysis and Embedding Text

**Files:**
- Modify: `backend/app/services/llm_analyzer.py`
- Modify: `backend/app/routers/images.py`
- Modify: `backend/app/backfill_embeddings.py`
- Modify: `backend/app/services/goal_validator.py`
- Modify: `backend/app/services/watch_reporter.py`
- Modify: `backend/tests/test_flow_regressions.py`

- [ ] **Step 1: Write failing dynamic analysis tests**

Append:

```python
    def test_dynamic_analysis_prompt_mentions_each_skill(self):
        from app.services.llm_analyzer import LLMAnalyzer

        snapshots = [
            {"skill_id": "a", "name": "设计维度", "instruction_md": "# 设计维度\n分析布局。", "is_official": True},
            {"skill_id": "b", "name": "价格策略", "instruction_md": "# 价格策略\n分析价格。", "is_official": False},
        ]

        prompt = LLMAnalyzer()._build_dynamic_analysis_prompt(snapshots, {"target_app": "淘宝"})

        self.assertIn("设计维度", prompt)
        self.assertIn("价格策略", prompt)
        self.assertIn('"results"', prompt)

    def test_dynamic_analysis_result_syncs_default_fields(self):
        from app.services.llm_analyzer import normalize_dynamic_analysis_result

        normalized = normalize_dynamic_analysis_result(
            {"results": [
                {"skill_name": "设计维度", "analysis": "布局清晰"},
                {"skill_name": "运营维度", "analysis": "促销明显"},
                {"skill_name": "价格策略", "analysis": "补贴突出"},
            ]},
            [{"name": "设计维度"}, {"name": "运营维度"}, {"name": "价格策略"}],
        )

        self.assertEqual(normalized["design_analysis"], "布局清晰")
        self.assertEqual(normalized["ops_analysis"], "促销明显")
        self.assertEqual(normalized["status"], "success")
        self.assertEqual(len(normalized["custom_analysis_json"]["results"]), 3)
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py -k "dynamic_analysis"
```

Expected: FAIL because dynamic prompt and normalizer do not exist.

- [ ] **Step 3: Add dynamic analysis normalizer**

In `backend/app/services/llm_analyzer.py`, add:

```python
def normalize_dynamic_analysis_result(parsed: dict | None, skill_snapshots: list[dict]) -> dict:
    expected_names = [snapshot.get("name") for snapshot in skill_snapshots if snapshot.get("name")]
    rows = parsed.get("results", []) if isinstance(parsed, dict) else []
    results = []
    errors = []
    by_name = {str(row.get("skill_name") or row.get("name") or ""): row for row in rows if isinstance(row, dict)}
    for snapshot in skill_snapshots:
        name = str(snapshot.get("name") or "")
        row = by_name.get(name)
        analysis = str((row or {}).get("analysis") or "").strip()
        item = {
            "skill_id": str(snapshot.get("skill_id") or ""),
            "skill_name": name,
            "analysis": analysis,
        }
        if analysis:
            results.append(item)
        else:
            item["error"] = "模型未返回该维度"
            errors.append(item)
    design = next((row["analysis"] for row in results if row["skill_name"] == "设计维度"), "")
    ops = next((row["analysis"] for row in results if row["skill_name"] == "运营维度"), "")
    status = "success" if len(results) == len(expected_names) else ("partial" if results else "failed")
    return {
        "design_analysis": design,
        "ops_analysis": ops,
        "custom_analysis_json": {"results": results, "errors": errors},
        "status": status,
    }
```

- [ ] **Step 4: Add dynamic prompt and analyzer method**

In `LLMAnalyzer`, add:

```python
    def _build_dynamic_analysis_prompt(self, skill_snapshots: list[dict], context: Optional[dict] = None) -> str:
        skill_lines = []
        for index, snapshot in enumerate(skill_snapshots, start=1):
            skill_lines.append(
                f"{index}. {snapshot.get('name')}\n{snapshot.get('instruction_md')}"
            )
        context_lines = self._context_lines(context)
        context_block = "\n".join(context_lines) if context_lines else "无"
        return """你现在只是一名电商截图分析器，不要操作手机，不要输出[finish]或finish(...)，不要解释你的思考。
请根据每个分析 skill 分别观察图片，并只输出一个JSON对象：
{
  "results": [
    {"skill_name": "技能名称", "analysis": "该技能对应的120-250字分析内容"}
  ]
}
要求：
1. 每个输入 skill 都必须返回一条 results。
2. skill_name 必须与输入名称完全一致。
3. 不要输出 Markdown，不要输出解释。
4. 如果截图信息不足，也要说明无法判断的原因。

用户需求上下文：
""" + context_block + "\n\n分析 skill：\n" + "\n\n".join(skill_lines)

    async def analyze_with_skills(self, image_path: str, skill_snapshots: list[dict], context: Optional[dict] = None) -> dict:
        if not skill_snapshots:
            design, ops, status = await self.analyze(image_path, context=context)
            return {
                "design_analysis": design or "",
                "ops_analysis": ops or "",
                "custom_analysis_json": {},
                "status": status,
            }
        if not self.providers:
            raise RuntimeError("VLM_API_KEY, PHONE_AGENT_API_KEY or OPENAI_API_KEY not configured")
        base64_image = self._encode_image(image_path)
        content = await self._complete_with_fallback(self._build_dynamic_analysis_prompt(skill_snapshots, context), base64_image)
        content = self._strip_finish_wrapper(content)
        parsed = self._extract_json(content)
        if not parsed:
            parsed = {"results": [{"skill_name": skill_snapshots[0].get("name"), "analysis": content}]}
        return normalize_dynamic_analysis_result(parsed, skill_snapshots)
```

- [ ] **Step 5: Store dynamic JSON and embed dynamic text**

In `backend/app/crud.py`, update `create_analysis` signature:

```python
def create_analysis(
    db: Session,
    image_id: UUID,
    design: str,
    ops: str,
    status: str = "success",
    custom_analysis_json: Optional[dict] = None,
) -> models.Analysis:
```

Set `db_analysis.custom_analysis_json = custom_analysis_json or {}` in both update and create paths.

In `backend/app/routers/images.py`, change `_record_analysis` signature:

```python
def _record_analysis(db: Session, image: models.Image, design: str, ops: str, status: str = "success", custom_analysis_json: dict | None = None):
    analysis = crud.create_analysis(db, image.id, design, ops, status=status, custom_analysis_json=custom_analysis_json)
```

Add helpers:

```python
def _skill_snapshots_for_image(image) -> list[dict]:
    task = image.task
    if task and task.analysis_skill_snapshots_json:
        return task.analysis_skill_snapshots_json
    if task and task.watch_runs:
        for watch_run in task.watch_runs:
            if watch_run.plan and watch_run.plan.analysis_skill_snapshots_json:
                return watch_run.plan.analysis_skill_snapshots_json
    return []


def _analysis_texts(design: str, ops: str, custom_analysis_json: dict | None) -> dict[str, str]:
    results = (custom_analysis_json or {}).get("results") if isinstance(custom_analysis_json, dict) else None
    dynamic_text = "\n".join(row.get("analysis", "") for row in (results or []) if row.get("analysis")).strip()
    combined = dynamic_text or f"{design or ''}\n{ops or ''}".strip()
    texts = {"combined": combined} if combined else {}
    if design:
        texts["design"] = design
    if ops:
        texts["ops"] = ops
    return texts
```

Inside `_analyze_and_embed`, replace fixed `analyzer.analyze(...)` with:

```python
            skill_snapshots = _skill_snapshots_for_image(image)
            result = await analyzer.analyze_with_skills(image.file_path, skill_snapshots, context=context)
            design = result["design_analysis"]
            ops = result["ops_analysis"]
            status = result["status"]
            custom_analysis_json = result["custom_analysis_json"]
```

Pass `custom_analysis_json` to `_record_analysis`, then create embeddings from `_analysis_texts(design, ops, custom_analysis_json)`.

- [ ] **Step 6: Update dynamic text consumers**

In `backend/app/backfill_embeddings.py`, change `_analysis_text` to prefer dynamic results:

```python
def _dynamic_analysis_text(analysis: models.Analysis) -> str:
    data = analysis.custom_analysis_json if isinstance(analysis.custom_analysis_json, dict) else {}
    return "\n".join(
        row.get("analysis", "")
        for row in data.get("results", [])
        if isinstance(row, dict) and row.get("analysis")
    ).strip()
```

Use `combined = _dynamic_analysis_text(analysis) or f"{analysis.design_analysis or ''}\n{analysis.ops_analysis or ''}".strip()`.

In `backend/app/services/goal_validator.py`, update `_analysis_text` to include dynamic results before old fields.

In `backend/app/services/watch_reporter.py`, add `multi = _dynamic_analysis_text(analysis)` and include it in the daily prompt payload as `"今日多维分析": multi`.

- [ ] **Step 7: Run dynamic analysis tests**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py -k "dynamic_analysis"
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/llm_analyzer.py backend/app/routers/images.py backend/app/crud.py backend/app/backfill_embeddings.py backend/app/services/goal_validator.py backend/app/services/watch_reporter.py backend/tests/test_flow_regressions.py
git commit -m "feat: analyze images with selected skills"
```

---

### Task 5: Search and Export Dynamic Skill Results

**Files:**
- Modify: `backend/app/crud.py`
- Modify: `backend/app/services/exporter.py`
- Modify: `backend/tests/test_flow_regressions.py`

- [ ] **Step 1: Write failing search/export tests**

Append:

```python
    def test_text_search_finds_custom_analysis_json_result(self):
        from app import crud, schemas
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            image = crud.create_image(db, schemas.ImageCreate(file_path=f"data/custom-{uuid4().hex}.png"))
            crud.create_analysis(
                db,
                image.id,
                "",
                "",
                custom_analysis_json={"results": [{"skill_name": "价格策略", "analysis": "会员价补贴非常突出"}]},
            )

            rows = crud.text_search_analyses(db, "会员价补贴", limit=10)

            self.assertIn(image.id, [row_image.id for _, row_image in rows])
        finally:
            analysis = crud.get_analysis_by_image(db, image.id)
            if analysis:
                db.delete(analysis)
            db.delete(image)
            db.commit()
            db.close()

    def test_export_flattens_custom_analysis_results(self):
        from app.services.exporter import _flatten_analysis

        rows = _flatten_analysis({
            "id": "image-1",
            "file_path": "data/a.png",
            "analysis": {
                "id": "analysis-1",
                "custom_analysis_json": {
                    "results": [{"skill_name": "价格策略", "analysis": "补贴突出"}]
                }
            }
        })

        self.assertEqual(rows[0]["skill_name"], "价格策略")
        self.assertEqual(rows[0]["analysis_text"], "补贴突出")
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py -k "custom_analysis"
```

Expected: FAIL because search and export only use old fields.

- [ ] **Step 3: Include JSONB text in fallback search**

In `backend/app/crud.py`, inside `text_search_analyses`, add this filter clause:

```python
            func.cast(models.Analysis.custom_analysis_json, String).ilike(pattern),
```

Add `String` to the SQLAlchemy imports:

```python
from sqlalchemy import func, or_, String
```

- [ ] **Step 4: Export dynamic rows**

In `backend/app/services/exporter.py`, update `_analysis_dict`:

```python
        "custom_analysis_json": analysis.custom_analysis_json,
```

Change `_flatten_analysis` to return a list of rows:

```python
def _flatten_analysis(row: dict) -> list[dict]:
    analysis = dict(row.get("analysis") or {})
    base = {
        "image_id": row.get("id"),
        "image_path": row.get("file_path"),
        "analysis_id": analysis.get("id"),
        "status": analysis.get("status"),
        "embedding_status": analysis.get("embedding_status"),
    }
    custom = analysis.get("custom_analysis_json") or {}
    results = custom.get("results") if isinstance(custom, dict) else None
    if results:
        return [
            {
                **base,
                "skill_name": item.get("skill_name"),
                "analysis_text": item.get("analysis"),
            }
            for item in results
        ]
    return [
        {**base, "skill_name": "设计维度", "analysis_text": analysis.get("design_analysis")},
        {**base, "skill_name": "运营维度", "analysis_text": analysis.get("ops_analysis")},
    ]
```

Update `excel_bytes` analysis sheet row building:

```python
    analysis_rows = []
    for row in image_rows:
        if row.get("analysis"):
            analysis_rows.extend(_flatten_analysis(row))
    _append_dict_rows(analyses, analysis_rows)
```

- [ ] **Step 5: Run custom analysis tests**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py -k "custom_analysis"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/crud.py backend/app/services/exporter.py backend/tests/test_flow_regressions.py
git commit -m "feat: search and export custom analysis results"
```

---

### Task 6: Frontend Skill APIs, Skill Page, and Navigation

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/pages/AnalysisSkillsPage.tsx`
- Modify: `frontend/src/styles/index.css`

- [ ] **Step 1: Add API functions**

In `frontend/src/api.ts`, add:

```ts
export const listAnalysisSkills = () => api.get('/analysis-skills');
export const createAnalysisSkill = (data: any) => api.post('/analysis-skills', data);
export const updateAnalysisSkill = (id: string, data: any) => api.patch(`/analysis-skills/${id}`, data);
export const deleteAnalysisSkill = (id: string) => api.delete(`/analysis-skills/${id}`);
export const uploadAnalysisSkillMd = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return api.post('/analysis-skills/upload-md', form, { headers: { 'Content-Type': 'multipart/form-data' } });
};
export const listAdminAnalysisSkills = () => api.get('/admin/analysis-skills');
export const adminUpdateAnalysisSkill = (id: string, data: any) => api.patch(`/admin/analysis-skills/${id}`, data);
export const adminDeleteAnalysisSkill = (id: string) => api.delete(`/admin/analysis-skills/${id}`);
export const setAnalysisSkillOfficial = (id: string, is_official: boolean) => api.patch(`/admin/analysis-skills/${id}/official`, { is_official });
```

- [ ] **Step 2: Create the skill management page**

Create `frontend/src/pages/AnalysisSkillsPage.tsx`:

```tsx
import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from 'react';
import {
  adminDeleteAnalysisSkill,
  adminUpdateAnalysisSkill,
  createAnalysisSkill,
  deleteAnalysisSkill,
  listAdminAnalysisSkills,
  listAnalysisSkills,
  setAnalysisSkillOfficial,
  updateAnalysisSkill,
  uploadAnalysisSkillMd,
} from '../api';
import { useAuth } from '../auth';
import { useToast } from '../components/Toast';

const emptyForm = { id: '', name: '', instruction_md: '' };

export default function AnalysisSkillsPage() {
  const { hasRole, user } = useAuth();
  const { showToast } = useToast();
  const [skills, setSkills] = useState<any[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [loading, setLoading] = useState(true);
  const isAdmin = hasRole('admin');
  const official = useMemo(() => skills.filter(skill => skill.is_official), [skills]);
  const mine = useMemo(() => skills.filter(skill => skill.owner_id === user?.id && !skill.is_official), [skills, user?.id]);
  const managed = isAdmin ? skills : [...official, ...mine];

  const load = async () => {
    setLoading(true);
    try {
      const { data } = isAdmin ? await listAdminAnalysisSkills() : await listAnalysisSkills();
      setSkills(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [isAdmin]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.name.trim() || !form.instruction_md.trim()) {
      showToast('名称和分析指令不能为空', 'warning');
      return;
    }
    if (form.instruction_md.length > 20000) {
      showToast('分析指令不能超过 20000 字符', 'warning');
      return;
    }
    if (form.id) {
      const updater = isAdmin ? adminUpdateAnalysisSkill : updateAnalysisSkill;
      await updater(form.id, { name: form.name, instruction_md: form.instruction_md });
      showToast('分析 skill 已更新', 'success');
    } else {
      await createAnalysisSkill({ name: form.name, instruction_md: form.instruction_md });
      showToast('分析 skill 已创建', 'success');
    }
    setForm(emptyForm);
    load();
  };

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const { data } = await uploadAnalysisSkillMd(file);
    setForm({ id: '', name: data.name, instruction_md: data.instruction_md });
    event.target.value = '';
  };

  const remove = async (skill: any) => {
    if (isAdmin) await adminDeleteAnalysisSkill(skill.id);
    else await deleteAnalysisSkill(skill.id);
    showToast('分析 skill 已禁用', 'success');
    load();
  };

  return (
    <div className="animate-fade-in analysis-skills-page">
      <div className="page-header">
        <h1>分析 skill</h1>
        <p>创建和管理截图分析维度，后续任务会按选择的 skill 执行分析</p>
      </div>

      <form className="analysis-skill-editor" onSubmit={submit}>
        <label>
          <span>名称</span>
          <input value={form.name} onChange={event => setForm(prev => ({ ...prev, name: event.target.value }))} placeholder="价格策略" />
        </label>
        <label>
          <span>Markdown 指令</span>
          <textarea value={form.instruction_md} onChange={event => setForm(prev => ({ ...prev, instruction_md: event.target.value }))} placeholder="# 价格策略&#10;分析价格锚点、补贴、满减、会员价。" />
        </label>
        <div className="analysis-skill-actions">
          <input type="file" accept=".md" onChange={handleUpload} />
          <button type="submit">{form.id ? '保存修改' : '创建 skill'}</button>
          {form.id && <button type="button" className="btn-secondary" onClick={() => setForm(emptyForm)}>取消编辑</button>}
        </div>
      </form>

      {loading ? <div className="skeleton" style={{ height: 160 }} /> : (
        <div className="analysis-skill-list">
          {managed.map(skill => (
            <div key={skill.id} className="analysis-skill-row">
              <div>
                <div className="analysis-skill-title">
                  <strong>{skill.name}</strong>
                  {skill.is_official && <span>官方</span>}
                  {skill.status !== 'active' && <span>已禁用</span>}
                </div>
                <p>{skill.instruction_md.slice(0, 180)}{skill.instruction_md.length > 180 ? '...' : ''}</p>
                {isAdmin && <small>{skill.owner_name || '系统'} · {skill.owner_id || 'system'}</small>}
              </div>
              <div className="analysis-skill-row-actions">
                <button className="btn-secondary btn-sm" onClick={() => setForm({ id: skill.id, name: skill.name, instruction_md: skill.instruction_md })}>编辑</button>
                {isAdmin && <button className="btn-secondary btn-sm" onClick={() => setAnalysisSkillOfficial(skill.id, !skill.is_official).then(load)}>{skill.is_official ? '取消官方' : '设为官方'}</button>}
                <button className="btn-secondary btn-sm" onClick={() => remove(skill)}>禁用</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add navigation and route**

In `frontend/src/App.tsx`, import:

```ts
import AnalysisSkillsPage from './pages/AnalysisSkillsPage';
```

Add nav item inside the authenticated block:

```tsx
<NavLink to="/analysis-skills">分析 skill</NavLink>
```

Add route:

```tsx
<Route path="/analysis-skills" element={<RequireAuth><AnalysisSkillsPage /></RequireAuth>} />
```

- [ ] **Step 4: Add styles**

In `frontend/src/styles/index.css`, add:

```css
.analysis-skills-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.analysis-skill-editor,
.analysis-skill-row {
  border: 1px solid var(--border);
  background: var(--bg-card);
  border-radius: var(--radius-md);
  padding: 20px;
}

.analysis-skill-editor {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.analysis-skill-editor textarea {
  min-height: 220px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.analysis-skill-actions,
.analysis-skill-row-actions,
.analysis-skill-title {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.analysis-skill-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.analysis-skill-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
}

.analysis-skill-title span {
  font-size: 0.75rem;
  border-radius: var(--radius-pill);
  padding: 2px 8px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}
```

- [ ] **Step 5: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: `tsc && vite build` completes successfully.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/App.tsx frontend/src/pages/AnalysisSkillsPage.tsx frontend/src/styles/index.css
git commit -m "feat: add analysis skill management UI"
```

---

### Task 7: Skill Selector in Request and Watch Forms

**Files:**
- Create: `frontend/src/components/AnalysisSkillSelector.tsx`
- Modify: `frontend/src/components/RequestForm.tsx`
- Modify: `frontend/src/components/WatchPlanForm.tsx`
- Modify: `frontend/src/pages/AdminRequests.tsx`
- Modify: `frontend/src/styles/index.css`

- [ ] **Step 1: Create reusable selector**

Create `frontend/src/components/AnalysisSkillSelector.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { listAnalysisSkills } from '../api';

export default function AnalysisSkillSelector({ value, onChange }: { value: string[]; onChange: (ids: string[]) => void }) {
  const [skills, setSkills] = useState<any[]>([]);
  const official = useMemo(() => skills.filter(skill => skill.is_official && skill.status === 'active'), [skills]);
  const custom = useMemo(() => skills.filter(skill => !skill.is_official && skill.status === 'active'), [skills]);

  useEffect(() => {
    listAnalysisSkills().then(({ data }) => {
      setSkills(data);
      if (value.length === 0) {
        onChange(data.filter((skill: any) => skill.is_official && skill.status === 'active').map((skill: any) => skill.id));
      }
    }).catch(() => setSkills([]));
  }, []);

  const toggle = (id: string) => {
    const next = value.includes(id) ? value.filter(item => item !== id) : [...value, id];
    onChange(next);
  };

  const selectedCustomCount = custom.filter(skill => value.includes(skill.id)).length;
  const selectedDefaultCount = official.filter(skill => value.includes(skill.id) && ['设计维度', '运营维度'].includes(skill.name)).length;
  const invalid = value.length === 0 || (selectedCustomCount === 0 && selectedDefaultCount === 0);

  return (
    <section className="analysis-skill-selector">
      <div className="analysis-skill-selector-head">
        <span>分析 skill</span>
        {invalid && <small>至少选择一个分析 skill</small>}
      </div>
      {[...official, ...custom].map(skill => (
        <label key={skill.id} className="analysis-skill-option">
          <input type="checkbox" checked={value.includes(skill.id)} onChange={() => toggle(skill.id)} />
          <span>{skill.name}</span>
          {skill.is_official && <em>官方</em>}
        </label>
      ))}
    </section>
  );
}
```

- [ ] **Step 2: Wire selector into request form**

In `frontend/src/components/RequestForm.tsx`, import:

```ts
import AnalysisSkillSelector from './AnalysisSkillSelector';
```

Add state:

```ts
  const [analysisSkillIds, setAnalysisSkillIds] = useState<string[]>([]);
```

Include in payload:

```ts
        analysis_skill_ids: analysisSkillIds,
```

Reset after success:

```ts
      setAnalysisSkillIds([]);
```

Render before submit button:

```tsx
        <AnalysisSkillSelector value={analysisSkillIds} onChange={setAnalysisSkillIds} />
```

- [ ] **Step 3: Wire selector into watch plan form**

In `frontend/src/components/WatchPlanForm.tsx`, import the selector and add state:

```ts
import AnalysisSkillSelector from './AnalysisSkillSelector';

const [analysisSkillIds, setAnalysisSkillIds] = useState<string[]>([]);
```

Include in payload:

```ts
        analysis_skill_ids: analysisSkillIds,
```

Render before form actions:

```tsx
        <AnalysisSkillSelector value={analysisSkillIds} onChange={setAnalysisSkillIds} />
```

- [ ] **Step 4: Show snapshots on admin requests page**

In `frontend/src/pages/AdminRequests.tsx`, add a compact column or secondary text block:

```tsx
<td title={(r.analysis_skill_snapshots_json || []).map((skill: any) => skill.instruction_md).join('\n\n')}>
  {(r.analysis_skill_snapshots_json || []).map((skill: any) => skill.name).join('、') || '-'}
</td>
```

Add a matching `<th>分析 skill</th>`.

- [ ] **Step 5: Add selector styles**

In `frontend/src/styles/index.css`, add:

```css
.analysis-skill-selector {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px;
  background: rgba(255, 255, 255, 0.03);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.analysis-skill-selector-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-secondary);
  font-weight: 600;
}

.analysis-skill-selector-head small {
  color: #ff9f0a;
}

.analysis-skill-option {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
}

.analysis-skill-option em {
  font-style: normal;
  font-size: 0.75rem;
  color: var(--text-tertiary);
}
```

- [ ] **Step 6: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/AnalysisSkillSelector.tsx frontend/src/components/RequestForm.tsx frontend/src/components/WatchPlanForm.tsx frontend/src/pages/AdminRequests.tsx frontend/src/styles/index.css
git commit -m "feat: select analysis skills for new work"
```

---

### Task 8: Dynamic Result Rendering in Image Cards

**Files:**
- Modify: `frontend/src/components/ImageCard.tsx`
- Modify: `frontend/src/styles/index.css`

- [ ] **Step 1: Add helper to normalize analysis blocks**

In `frontend/src/components/ImageCard.tsx`, add above the component:

```tsx
function analysisBlocks(analysis: any) {
  const results = analysis?.custom_analysis_json?.results;
  if (Array.isArray(results) && results.length > 0) {
    return results
      .filter((row: any) => row?.analysis)
      .map((row: any) => ({ title: row.skill_name || '分析维度', text: row.analysis }));
  }
  const blocks = [];
  if (analysis?.design_analysis) blocks.push({ title: '设计分析', text: analysis.design_analysis });
  if (analysis?.ops_analysis) blocks.push({ title: '运营分析', text: analysis.ops_analysis });
  return blocks;
}
```

Inside `ImageCard`, add:

```tsx
  const blocks = analysisBlocks(analysis);
```

- [ ] **Step 2: Render modal blocks dynamically**

Replace the two hard-coded modal `<section>` blocks with:

```tsx
            {blocks.length === 0 ? (
              <section>
                <div style={{ color: 'var(--text-secondary)', fontWeight: 600, marginBottom: 8 }}>分析结果</div>
                <p style={{ lineHeight: 1.8 }}>暂无分析结果</p>
              </section>
            ) : blocks.map((block, index) => (
              <section key={`${block.title}-${index}`}>
                <div style={{ color: index === 0 ? 'var(--accent)' : '#0a84ff', fontWeight: 600, marginBottom: 8 }}>{block.title}</div>
                <p style={{ lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                  {block.text}
                </p>
              </section>
            ))}
```

- [ ] **Step 3: Render card summaries dynamically**

Replace hard-coded summary rendering with:

```tsx
          {analysis && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {blocks.map((block, index) => (
                <div key={`${block.title}-${index}`}>
                  <div
                    style={{
                      fontSize: '0.75rem',
                      fontWeight: 500,
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                      color: index === 0 ? 'var(--accent)' : '#0a84ff',
                      marginBottom: 4,
                    }}
                  >
                    {block.title}
                  </div>
                  <p style={{ fontSize: '0.875rem', lineHeight: 1.6 }}>
                    {block.text.slice(0, 120)}
                    {block.text.length > 120 ? '...' : ''}
                  </p>
                </div>
              ))}
            </div>
          )}
```

- [ ] **Step 4: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ImageCard.tsx frontend/src/styles/index.css
git commit -m "feat: render dynamic analysis results"
```

---

### Task 9: Full Verification and Documentation Update

**Files:**
- Modify: `docs/TODO.md`
- Modify: `backend/tests/test_flow_regressions.py`

- [ ] **Step 1: Run backend regression suite**

Run:

```bash
python3 -m unittest backend/tests/test_flow_regressions.py
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: `✓ built` output and no TypeScript errors.

- [ ] **Step 3: Run secret check**

Run:

```bash
python3 scripts/pre-commit-secret-check.py
```

Expected: exit code `0` and no output.

- [ ] **Step 4: Update project TODO status**

In `docs/TODO.md`, add a completed section:

```md
### 分析 skill 与自定义分析维度

- [x] 新增用户自定义分析 skill
- [x] 支持 Markdown 文本和 `.md` 上传
- [x] 支持官方 skill 和管理员管理
- [x] 任务与持续观察计划按创建时 skill 快照分析
- [x] 自定义维度结果可展示、搜索、导出
```

- [ ] **Step 5: Commit final docs and test updates**

```bash
git add docs/TODO.md backend/tests/test_flow_regressions.py
git commit -m "docs: record analysis skill rollout"
```

---

## Self-Review

Spec coverage:

- Custom skill creation via text and Markdown upload is covered by Tasks 2 and 6.
- Per-request and per-watch-plan selection is covered by Tasks 3 and 7.
- Admin visibility and official skill management is covered by Tasks 2 and 6.
- Snapshot stability is covered by Task 3.
- Dynamic analysis execution is covered by Task 4.
- Backward-compatible design and ops fields are covered by Tasks 1, 4, and 8.
- Search, embedding, exports, and watch reports are covered by Tasks 4 and 5.
- Only future analysis is affected because the plan adds new snapshot and result fields without migrating or re-running existing analysis.

Placeholder scan:

- The plan contains no open implementation placeholders.
- Each code-changing task includes exact file paths, commands, and expected results.

Type consistency:

- Skill identifiers use `analysis_skill_ids` in request bodies.
- Immutable snapshots use `analysis_skill_snapshots_json` on `requests`, `tasks`, and `watch_plans`.
- Dynamic results use `custom_analysis_json` on `analysis`.
