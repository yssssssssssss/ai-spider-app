# 竞品分析平台 - 待办任务总览

> 最后更新：2026-05-27

---

## 一、已实现功能（✅）

### 1. 前端交互层
| 功能 | 文件 | 状态 |
|------|------|------|
| 需求提交表单 | `frontend/src/pages/HomePage.tsx` | ✅ |
| 图片检索页面 | `frontend/src/pages/SearchPage.tsx` | ✅ |
| 需求管理（审核/拒绝/指派设计师） | `frontend/src/pages/AdminRequests.tsx` | ✅ |
| 任务管理（启动/刷新/实时进度） | `frontend/src/pages/AdminTasks.tsx` | ✅ |
| 数据看板 | `frontend/src/pages/AdminDashboard.tsx` | ✅ |
| 全局 Toast 通知 | `frontend/src/components/Toast.tsx` | ✅ |
| 图片卡片展示 | `frontend/src/components/ImageCard.tsx` | ✅ |
| SSE 实时进度监听 | `frontend/src/pages/AdminTasks.tsx` | ✅ |

### 2. 后端 API 层
| 功能 | 文件 | 状态 |
|------|------|------|
| 需求 CRUD | `backend/app/routers/requests.py` | ✅ |
| 管理后台（审核/任务/进度） | `backend/app/routers/admin.py` | ✅ |
| 图片管理（入库/文件服务/分析） | `backend/app/routers/images.py` | ✅ |
| 向量检索 | `backend/app/routers/search.py` | ✅ |
| 指派设计师 | `backend/app/routers/admin.py` (PATCH /:id/assign) | ✅ |

### 3. 数据采集层
| 功能 | 文件 | 状态 |
|------|------|------|
| Appium 滚动截图（legacy） | `step1-down_img.py` | ✅ |
| OpenCV 图片裁剪 | `step2-cut_img.py` | ✅ |
| uiautomator2 规则采集 | `run_workflow.py` | ✅ |
| AutoGLM AI 采集 | `run_autoglm.py` | ✅ |
| 后台截图监控自动入库 | `backend/app/services/collector_bridge.py` | ✅ |
| SSE 事件推送 | `backend/app/services/task_events.py` | ✅ |

### 4. AI 分析层
| 功能 | 文件 | 状态 |
|------|------|------|
| 图片设计分析 + 运营分析 | `backend/app/services/llm_analyzer.py` | ✅ |
| 向量嵌入服务 | `backend/app/services/embedder.py` | ✅ |

### 5. 数据层
| 功能 | 文件 | 状态 |
|------|------|------|
| PostgreSQL + pgvector 连接 | `backend/app/database.py` | ✅ |
| Image / Task / Request / Analysis / User 模型 | `backend/app/models.py` | ✅ |
| Pydantic Schemas | `backend/app/schemas.py` | ✅ |
| CRUD 操作 | `backend/app/crud.py` | ✅ |

---

## 二、待办任务（🔴）

### 🔴 任务 1：LLM 需求理解 → 生成 AutoGLM 可执行指令

**问题描述：**
当前 `build_autoglm_prompt()` 只是简单的字符串模板拼接：
```python
"打开{app}App，搜索'{keyword}'，找到{scenario}，{description}，并截图保存到本地"
```
没有真正调用 LLM 分析用户需求的深层意图，无法处理复杂场景（如多步操作、筛选条件、特定时间段等）。

**验收标准：**
- [ ] `Task` 模型新增 `generated_instruction` 字段（TEXT，可空）
- [ ] 新建 `backend/app/services/task_planner.py`
  - 接收 `Request` 对象
  - 调用 LLM（OpenAI/GLM）分析用户需求的深层意图
  - 输出一条精确、可执行的 AutoGLM 自然语言指令
  - 返回指令字符串
- [ ] `approve_request` 审核通过时调用 `task_planner` 生成指令并存入 `task.generated_instruction`
- [ ] `run_task` 执行 AutoGLM 模式时优先使用 `task.generated_instruction`，回退到 `build_autoglm_prompt`
- [ ] 前端任务列表/详情页展示 AI 生成的指令

**参考实现思路：**
```python
# task_planner.py
async def plan_task(request) -> str:
    prompt = f"""
    你是移动端 App 自动化专家。请根据以下需求生成一条精确的指令，
    用于驱动 AI 自动操作手机 App 并截图：

    目标 App: {request.target_app}
    目标场景: {request.target_scenario}
    关键词: {', '.join(request.keywords)}
    补充说明: {request.description}

    要求：
    1. 指令必须包含"打开App → 搜索/导航 → 截图保存"三个步骤
    2. 如涉及筛选（价格区间、品牌、时间段），要精确描述
    3. 如有多页滚动需求，说明滚动次数和每次停留时间
    4. 输出只返回指令文本，不要解释
    """
    response = await openai_client.chat.completions.create(...)
    return response.choices[0].message.content
```

---

### 🔴 任务 2：图片入库后自动触发 LLM 分析

**问题描述：**
当前 `collector_bridge.py` 发现新截图后会自动调用 `crud.create_image()` 入库，但**入库后不会自动触发 LLM 分析**。
`llm_analyzer.analyze_image()` 必须通过 `POST /api/images/{id}/analyze` 手动调用。

**验收标准：**
- [ ] `collector_bridge.py` 的 `_watch_and_upload()` 中，每成功入库一张图片后，异步触发 LLM 分析
- [ ] 分析完成后通过 `push_event()` 向前端推送 `"type": "analyzed"` 事件
- [ ] 前端 SSE 监听器接收 `"analyzed"` 事件后更新图片卡片的分析状态
- [ ] 添加开关配置（环境变量 `AUTO_ANALYZE=true/false`），允许关闭自动分析

**参考实现思路：**
```python
# collector_bridge.py
from app.services.llm_analyzer import analyzer
from app.services.task_events import push_event

for file_path in new_files:
    image = crud.create_image(db, image_in)
    push_event(task_id, json.dumps({"type": "new_image", "count": len(known_files)}))
    
    # 异步触发 LLM 分析
    if os.getenv("AUTO_ANALYZE", "true").lower() == "true":
        try:
            analyzer.analyze_image_sync(db, image.id)  # 或使用线程池异步
            push_event(task_id, json.dumps({"type": "analyzed", "image_id": str(image.id)}))
        except Exception as e:
            print(f"分析失败: {e}")
```

---

### 🔴 任务 3：前端展示 AI 生成指令和分析状态

**问题描述：**
- 任务列表没有展示 LLM 生成的指令，管理员无法预览 AI 要执行什么
- 图片卡片没有展示分析状态（是否已分析、分析中、失败）

**验收标准：**
- [ ] `AdminTasks.tsx` 任务列表增加"AI 指令"列（hover 显示完整指令）
- [ ] `AdminTasks.tsx` 任务详情弹窗展示完整 `generated_instruction`
- [ ] `ImageCard.tsx` 增加分析状态徽章：
  - `analyzing` → 分析中（黄色旋转图标）
  - `success` → 分析完成（绿色对勾）
  - `failed` → 分析失败（红色感叹号）
  - `pending` → 等待分析（灰色）

---

### 🔴 任务 4：数据库迁移

**问题描述：**
`Task` 表需要新增 `generated_instruction` 字段，已运行的数据库需要迁移。

**验收标准：**
- [ ] 提供 Alembic 迁移脚本或手动 SQL：
  ```sql
  ALTER TABLE tasks ADD COLUMN generated_instruction TEXT;
  ```
- [ ] `models.py` 中 `Task` 类增加 `generated_instruction = Column(Text, nullable=True)`
- [ ] `schemas.py` 中 `TaskOut` 增加 `generated_instruction` 字段

---

## 三、未来优化（💡）

| 优化项 | 优先级 | 说明 |
|--------|--------|------|
| 设计师工作台 | P2 | 被指派设计师可查看专属需求并提交方案 |
| 图片去重（感知哈希） | P2 | 采集时自动过滤重复截图 |
| 定时任务（Cron） | P2 | 支持周期性竞品监控 |
| 多设备并发采集 | P3 | 同时连接多台手机并行采集 |
| 结果导出（PDF/Excel） | P3 | 导出分析报告 |
| 用户权限系统 | P3 | RBAC 角色权限 |

---

## 四、快速启动命令

```bash
# 1. 安装依赖
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..

# 2. 数据库迁移（如需新增 generated_instruction 字段）
cd backend
python -c "
from app.database import engine
from app.models import Base
Base.metadata.create_all(bind=engine)
print('数据库表已同步')
"
# 或手动执行：ALTER TABLE tasks ADD COLUMN generated_instruction TEXT;

# 3. 启动后端
uvicorn app.main:app --reload --port 8000

# 4. 启动前端
cd frontend && npm run dev

# 5. 环境变量示例
cat > .env << 'EOF'
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/competitor_db
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://modelservice.jdcloud.com/v1/
PHONE_AGENT_BASE_URL=https://xxx
PHONE_AGENT_API_KEY=xxx
AUTO_ANALYZE=true
EOF
```
