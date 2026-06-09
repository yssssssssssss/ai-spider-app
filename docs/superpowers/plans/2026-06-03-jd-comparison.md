# JD Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first version of "对比JD" for one-off competitor collection, generating A-side tasks plus one reusable JD task and showing slot-based per-image AB analysis on task results.

**Architecture:** Extend requests with an optional JD comparison config, create comparison group tables during approval, and trigger slot matching plus pair analysis after normal single-image analysis. Keep ordinary request/task/image/analysis behavior unchanged when `compare_jd_enabled` is false.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, PostgreSQL JSONB, React, Vite, existing VLM analyzer and analysis skill snapshots.

---

## File Structure

- Modify `backend/app/models.py`: add comparison ORM models and request comparison columns.
- Modify `backend/app/database.py`: add compatibility schema creation for new request columns, comparison tables, indexes, and uniqueness constraints.
- Modify `backend/app/schemas.py`: add comparison input/output schemas and expose request comparison fields.
- Modify `backend/app/crud.py`: add comparison CRUD helpers and extend request creation.
- Modify `backend/app/services/request_interpreter.py`: return A apps, slots, and JD instruction from LLM or fallback.
- Create `backend/app/services/jd_comparison.py`: normalize config, build approval tasks, match slots, trigger pair analysis, and assemble result payloads.
- Modify `backend/app/services/llm_analyzer.py`: add slot matching and two-image AB skill analysis methods.
- Modify `backend/app/routers/admin.py`: create comparison group during request approval and start all generated tasks.
- Modify `backend/app/routers/images.py`: trigger comparison slot matching after successful single-image analysis.
- Create `backend/app/routers/comparison_groups.py`: expose `GET /api/comparison-groups/by-task/{task_id}`.
- Modify `backend/app/main.py`: register the comparison router.
- Modify `frontend/src/api.ts`: add comparison result API.
- Modify `frontend/src/components/RequestForm.tsx`: add compare-JD toggle and editable config controls.
- Modify `frontend/src/pages/AdminRequests.tsx`: show comparison summary in approval table.
- Modify `frontend/src/pages/AdminTaskResults.tsx`: load and render comparison result panels.
- Modify `frontend/src/styles/index.css`: add restrained operational UI styles for comparison panels.
- Modify `backend/tests/test_flow_regressions.py`: add backend contract tests.

---

### Task 1: Backend Contract Tests

**Files:**
- Modify: `backend/tests/test_flow_regressions.py`

- [ ] **Step 1: Add failing schema/model/request tests**

Add tests that assert:

```python
def test_jd_comparison_model_and_schema_fields_exist(self):
    from app import models
    from app.schemas import RequestCreate, RequestInterpretOut, RequestOut

    self.assertTrue(hasattr(models, "ComparisonGroup"))
    self.assertTrue(hasattr(models, "ComparisonGroupApp"))
    self.assertTrue(hasattr(models, "ComparisonSlot"))
    self.assertTrue(hasattr(models, "ComparisonSlotMatch"))
    self.assertTrue(hasattr(models, "ComparisonPairAnalysis"))
    self.assertTrue(hasattr(models.Request, "compare_jd_enabled"))
    self.assertTrue(hasattr(models.Request, "comparison_config_json"))
    self.assertIn("compare_jd_enabled", RequestCreate.model_fields)
    self.assertIn("comparison", RequestCreate.model_fields)
    self.assertIn("a_apps", RequestInterpretOut.model_fields)
    self.assertIn("comparison_slots", RequestInterpretOut.model_fields)
    self.assertIn("jd_instruction", RequestInterpretOut.model_fields)
    self.assertIn("compare_jd_enabled", RequestOut.model_fields)
    self.assertIn("comparison_config_json", RequestOut.model_fields)
```

- [ ] **Step 2: Run the schema/model test and verify RED**

Run:

```bash
python -m unittest backend.tests.test_flow_regressions.FlowRegressionTests.test_jd_comparison_model_and_schema_fields_exist
```

Expected: FAIL because comparison models and schema fields do not exist yet.

- [ ] **Step 3: Add failing validation and config normalization tests**

Add tests that assert enabled JD comparison rejects JD as an A-side app and stores normalized config for valid input:

```python
def test_request_api_rejects_jd_in_a_side_apps(self):
    from fastapi.testclient import TestClient
    from app import crud
    from app.database import SessionLocal
    from app.main import app
    from app.services.auth import create_access_token, hash_password

    db = SessionLocal()
    user = None
    try:
        user = crud.create_user(db, username=f"jd-compare-{uuid4().hex[:8]}", password_hash=hash_password("pass"), role="viewer")
        response = TestClient(app).post(
            "/api/requests",
            headers={"Authorization": f"Bearer {create_access_token(user)}"},
            json={
                "target_app": "京东",
                "target_scenario": "百亿补贴会场",
                "compare_jd_enabled": True,
                "comparison": {
                    "a_apps": ["京东"],
                    "jd_instruction": "打开京东App，进入百亿补贴会场并截图保存到本地",
                    "slots": [{"name": "会场首屏", "description": "活动会场首屏", "required": True}],
                },
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("京东", response.text)
    finally:
        if user:
            db.delete(user)
        db.commit()
        db.close()
```

- [ ] **Step 4: Run validation test and verify RED**

Run:

```bash
python -m unittest backend.tests.test_flow_regressions.FlowRegressionTests.test_request_api_rejects_jd_in_a_side_apps
```

Expected: FAIL because request schema does not accept/validate comparison config yet.

- [ ] **Step 5: Add failing approval and result API tests**

Add tests that assert one request with `a_apps=["淘宝", "拼多多"]` creates two A tasks, one JD task, one comparison group, two group app rows, and slots during approval. Stub task planner and executor so no process starts.

- [ ] **Step 6: Run approval test and verify RED**

Run:

```bash
python -m unittest backend.tests.test_flow_regressions.FlowRegressionTests.test_approve_jd_comparison_request_creates_group_tasks_and_slots
```

Expected: FAIL because comparison CRUD and approval flow do not exist yet.

---

### Task 2: Backend Models, Schemas, and CRUD

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/crud.py`

- [ ] **Step 1: Implement request fields and comparison ORM models**

Add `compare_jd_enabled` and `comparison_config_json` to `Request`. Add comparison models matching the design doc with relationships to requests, tasks, slots, images, and analyses.

- [ ] **Step 2: Add compatibility schema creation**

Update `ensure_schema()` to add request columns and create comparison table indexes/unique constraints. Use `Base.metadata.create_all()` for new tables and `CREATE INDEX IF NOT EXISTS` for indexes.

- [ ] **Step 3: Add Pydantic schemas**

Add `ComparisonSlotInput`, `ComparisonConfigInput`, `ComparisonMatchOut`, `ComparisonSlotResultOut`, `ComparisonGroupResultOut`, and expose comparison fields on `RequestCreate`, `RequestInterpretOut`, and `RequestOut`.

- [ ] **Step 4: Add CRUD helpers**

Add helpers to create comparison groups, apps, slots, slot matches, and pair analyses; find comparison group by task; list matches by group; and prevent duplicate high-confidence matches from replacing locked rows.

- [ ] **Step 5: Run model/schema test and verify GREEN**

Run:

```bash
python -m unittest backend.tests.test_flow_regressions.FlowRegressionTests.test_jd_comparison_model_and_schema_fields_exist
```

Expected: PASS.

---

### Task 3: Request Config and Interpreter

**Files:**
- Create: `backend/app/services/jd_comparison.py`
- Modify: `backend/app/services/request_interpreter.py`
- Modify: `backend/app/routers/requests.py`

- [ ] **Step 1: Add config normalization**

Implement `normalize_comparison_config(config)`:

```python
def normalize_comparison_config(config: dict | None) -> dict:
    # returns {"a_apps": [...], "jd_instruction": "...", "slots": [...]}
```

Rules: de-dupe A apps, reject `京东`, require JD instruction length 20-2000, require 1-5 slots, generate `slot_key` from name when missing, and require slot name/description.

- [ ] **Step 2: Extend request creation**

When `RequestCreate.compare_jd_enabled` is true, normalize and store config. When false, force `comparison_config_json={}` and keep old behavior.

- [ ] **Step 3: Extend interpreter fallback and LLM output**

Return `a_apps`, `comparison_slots`, and `jd_instruction` from `interpret_request_text`. If LLM fails, generate conservative slots from scenario terms and JD instruction from the target scenario/keywords.

- [ ] **Step 4: Run validation and interpreter tests**

Run:

```bash
python -m unittest backend.tests.test_flow_regressions.FlowRegressionTests.test_request_api_rejects_jd_in_a_side_apps
python -m unittest backend.tests.test_flow_regressions.FlowRegressionTests.test_request_interpret_endpoint_returns_structured_fields
```

Expected: PASS.

---

### Task 4: Approval Flow and Task Generation

**Files:**
- Modify: `backend/app/services/jd_comparison.py`
- Modify: `backend/app/routers/admin.py`

- [ ] **Step 1: Add comparison approval service**

Implement `create_comparison_for_request(db, req, body, user)` that creates one comparison group, slots, one task per A app, one JD task, group app rows, and stores generated instructions.

- [ ] **Step 2: Wire admin approval**

In `approve_request`, branch only when `req.compare_jd_enabled` is true and `req.schedule_enabled` is false. Return/start the first A task while all comparison tasks are queued/running via existing `_start_task`.

- [ ] **Step 3: Run approval test**

Run:

```bash
python -m unittest backend.tests.test_flow_regressions.FlowRegressionTests.test_approve_jd_comparison_request_creates_group_tasks_and_slots
```

Expected: PASS.

---

### Task 5: Slot Matching, Pair Analysis, and Result API

**Files:**
- Modify: `backend/app/services/llm_analyzer.py`
- Modify: `backend/app/services/jd_comparison.py`
- Modify: `backend/app/routers/images.py`
- Create: `backend/app/routers/comparison_groups.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add analyzer methods**

Add `match_comparison_slot(image_path, slots, context)` and `analyze_pair_with_skills(a_image_path, jd_image_path, skill_snapshots, context)` using existing provider fallback style.

- [ ] **Step 2: Add post-single-analysis hook**

After `_record_analysis()` succeeds in `_analyze_and_embed`, call `process_image_for_comparison(image.id)` only for `success` or `partial` single-image analyses.

- [ ] **Step 3: Implement pair analysis triggering**

Create matches for high/low/unmatched confidence; when A and JD both have high-confidence matches for the same slot, create one pair analysis and call the two-image analyzer.

- [ ] **Step 4: Add comparison result router**

Expose `GET /api/comparison-groups/by-task/{task_id}` with data-scope checks and response assembled from group, slots, matches, images, single analyses, and pair analyses.

- [ ] **Step 5: Run result API tests**

Run:

```bash
python -m unittest backend.tests.test_flow_regressions.FlowRegressionTests.test_comparison_result_api_returns_paired_missing_and_unmatched_slots
```

Expected: PASS.

---

### Task 6: Frontend Request and Admin UI

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/RequestForm.tsx`
- Modify: `frontend/src/pages/AdminRequests.tsx`
- Modify: `frontend/src/styles/index.css`

- [ ] **Step 1: Add request state and payload**

Add `compareJdEnabled`, `aApps`, `jdInstruction`, and `comparisonSlots` state to `RequestForm`, populate them from `interpretRequest`, validate before submit, and include the `comparison` payload only when enabled.

- [ ] **Step 2: Render editable compare-JD config**

Use compact operational controls: one toggle, plain list rows for A apps and slots, and one textarea for JD instruction. Keep density consistent with current form.

- [ ] **Step 3: Show admin summary**

In `AdminRequests`, add a concise comparison summary cell/line showing `对比JD`, A apps, and slot count without allowing edits.

- [ ] **Step 4: Add styles**

Add `.jd-compare-*` and `.comparison-*` classes with restrained spacing, neutral borders, no nested card clutter.

---

### Task 7: Frontend Result UI

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/AdminTaskResults.tsx`
- Modify: `frontend/src/styles/index.css`

- [ ] **Step 1: Add API wrapper**

Add:

```ts
export const getComparisonGroupByTask = (id: string) => api.get(`/comparison-groups/by-task/${id}`);
```

- [ ] **Step 2: Fetch comparison result**

In `AdminTaskResults`, fetch comparison data alongside task images. Treat 404 as no comparison and do not show an error toast.

- [ ] **Step 3: Render result panels**

Render each `app_name vs 京东` section, slot status, A/JD images, single analysis snippets, and pair skill results. Missing and unmatched states must not render fake AB text.

- [ ] **Step 4: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: build exits 0.

---

### Task 8: Final Verification

**Files:**
- Verify only

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
python -m unittest backend.tests.test_flow_regressions.FlowRegressionTests.test_jd_comparison_model_and_schema_fields_exist \
  backend.tests.test_flow_regressions.FlowRegressionTests.test_request_api_rejects_jd_in_a_side_apps \
  backend.tests.test_flow_regressions.FlowRegressionTests.test_approve_jd_comparison_request_creates_group_tasks_and_slots \
  backend.tests.test_flow_regressions.FlowRegressionTests.test_comparison_result_api_returns_paired_missing_and_unmatched_slots
```

Expected: all selected tests pass.

- [ ] **Step 2: Run broader backend regression test file**

Run:

```bash
python -m unittest backend.tests.test_flow_regressions
```

Expected: pass or report unrelated pre-existing failures with exact output.

- [ ] **Step 3: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: build exits 0.

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git diff --stat
git diff -- backend/app frontend/src backend/tests docs/superpowers/plans/2026-06-03-jd-comparison.md
```

Expected: changes match the JD comparison scope only.
