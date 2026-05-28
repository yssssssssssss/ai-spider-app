# 竞品分析平台 - 任务状态总览

> 生成时间：2026-05-27

---

## 一、已实现功能（✅ 已完成）

### 1. 用户前端提交任务
- **页面**：`HomePage.tsx`（需求提交表单）
- **接口**：`POST /api/requests`
- **字段**：目标 App、目标场景、关键词列表、详细描述、设计师 ID
- **状态**：✅ 已实现，可正常使用

### 2. 管理员审核与任务创建
- **页面**：`AdminRequests.tsx`（需求管理）
- **操作**：
  - 「规则采集」→ 创建 uiautomator2 模式任务
  - 「AI 采集」→ 创建 AutoGLM 模式任务
  - 「拒绝」→ 标记需求为 rejected
- **接口**：`PUT /admin/requests/:id/approve`
- **状态**：✅ 已实现

### 3. 任务执行引擎
- **模式 A（规则）**：启动 `run_workflow.py`（uiautomator2 滚动截图）
- **模式 B（AI）**：启动 `run_autoglm.py`（AutoGLM 执行自然语言指令）
- **状态**：✅ 已实现，支持两种模式分发

### 4. 采集闭环（自动入库）
- **机制**：后台线程每 5 秒扫描 `data/` 目录，发现新截图自动入库
- **关联**：自动关联 `task_id`
- **触发**：任务启动后自动创建监控线程
- **状态**：✅ 已实现

### 5. 图片访问与展示
- **后端**：`GET /api/images/:id/file` 直接返回图片文件
- **前端**：`ImageCard.tsx` 展示图片 + 设计分析 + 运营分析
- **状态**：✅ 已实现

### 6. LLM 分析（设计与运营）
- **服务**：`llm_analyzer.py`（调用 LLM 生成设计分析 + 运营分析）
- **接口**：`POST /api/images/:id/analyze`
- **前端**：`ImageCard.tsx` 展示分析结果摘要
- **状态**：✅ 接口已实现，但不会自动触发

### 7. 实时进度推送（SSE）
- **后端**：`GET /admin/tasks/:id/events` SSE 端点
- **前端**：`AdminTasks.tsx` 自动对 running 任务建立 EventSource
- **状态**：✅ 已实现，实时显示已采集数量

### 8. 全局 Toast + Loading 状态
- **组件**：`Toast.tsx` 全局通知系统
- **API**：`api.ts` Axios 拦截器自动捕获错误并弹出 Toast
- **状态**：✅ 已实现

---

## 二、缺失功能（❌ 待补齐）

### ❌ 缺口 1：LLM 理解需求生成 AutoGLM 指令（功能 2）

**当前问题：**
- `build_autoglm_prompt()` 只是简单的字符串拼接（模板：打开App → 搜索关键词 → 找到场景 → 截图）
- 没有真正调用 LLM 分析用户需求的深层意图
- 生成的指令可能不符合用户真实需求

**需要实现：**
1. 数据库：`Task` 表新增 `generated_instruction` 字段（LLM 生成的指令）
2. 服务层：新建 `app/services/task_planner.py`
   - 调用 LLM 分析用户需求（目标App、场景、关键词、描述）
   - 生成精确的 AutoGLM 自然语言指令
3. API 层：`approve_request` 审核时调用 `task_planner` 生成指令并存入 task
4. 前端层：任务列表展示 AI 生成的指令

**示例：**
```
输入：目标App=淘宝, 场景=大促弹窗, 关键词=智能手表, 描述=关注红色主题
当前输出：打开淘宝App，搜索'智能手表'，找到大促弹窗，关注红色主题，并截图保存到本地
期望输出（LLM生成）：打开淘宝App，首页搜索"智能手表"，浏览搜索结果页面并关注带有红色背景的大促限时优惠弹窗，对弹窗区域进行截图并保存
```

---

### ❌ 缺口 2：图片入库后自动触发 LLM 分析（功能 5）

**当前问题：**
- 图片入库和分析是完全脱节的两个步骤
- 用户需要手动调用 `POST /api/images/:id/analyze` 才能触发分析
- 无法实现"采集完成即分析完成"的自动化体验

**需要实现：**
1. `collector_bridge.py` 中每发现新截图入库后：
   - 调用 `llm_analyzer.analyze_image()` 自动触发分析
   - 分析结果自动写入 `analysis` 表
2. 前端展示分析状态：
   - 图片卡片显示"分析中..."或"分析完成"
   - 任务列表显示已分析数量 / 总数量

**当前流程 vs 期望流程：**
```
当前：截图入库 → [手动触发] → LLM分析 → 前端展示
期望：截图入库 → [自动触发] → LLM分析 → 前端自动展示
```

---

## 三、功能清单验证

| # | 功能要求 | 当前状态 | 缺失说明 |
|---|---------|---------|---------|
| 1 | 用户通过前端页面提交任务 | ✅ | 无 |
| 2 | LLM 分析需求，生成 AutoGLM 可执行指令 | ❌ | 只有字符串拼接，未调用 LLM |
| 3 | AutoGLM 执行后将任务和图片汇总到数据表 | ⚠️ | 图片自动入库，但任务完成靠"60秒无新文件"推断 |
| 4 | 前端页面生成任务相关信息 | ✅ | 任务列表 + 实时进度 |
| 5 | LLM 从设计和运营角度分析图片，汇总到数据表 | ⚠️ | 分析接口存在，但不会自动触发 |
| 6 | 用户在前台看到任务、图片、分析内容 | ✅ | 无 |

---

## 四、下一步实施计划

### Phase 1：补齐缺口 1（LLM 指令生成）
- [ ] 数据库：`Task` 表新增 `generated_instruction` 字段
- [ ] 服务：新建 `task_planner.py`，调用 LLM 生成指令
- [ ] API：`approve_request` 审核时生成指令并存入 task
- [ ] 前端：任务列表展示 AI 生成指令

### Phase 2：补齐缺口 2（自动分析）
- [ ] `collector_bridge.py` 入库后异步调用 LLM 分析
- [ ] 前端图片卡片展示分析状态（分析中/已完成）
- [ ] 任务列表显示分析进度（已分析 N / 总图片 M）

### Phase 3：验证与收尾
- [ ] 完整走通一次：提交需求 → 审核 → 启动 → 采集 → 自动分析 → 前端展示
- [ ] TypeScript 编译检查
- [ ] Python 模块加载测试

---

## 五、相关文件路径

### 前端
- `frontend/src/pages/HomePage.tsx` — 需求提交页
- `frontend/src/pages/AdminRequests.tsx` — 需求管理页
- `frontend/src/pages/AdminTasks.tsx` — 任务管理页
- `frontend/src/components/ImageCard.tsx` — 图片展示卡片
- `frontend/src/components/Toast.tsx` — 全局 Toast
- `frontend/src/api.ts` — API 封装

### 后端
- `backend/app/models.py` — 数据库模型
- `backend/app/schemas.py` — Pydantic Schema
- `backend/app/crud.py` — CRUD 操作
- `backend/app/routers/admin.py` — 管理接口
- `backend/app/routers/images.py` — 图片接口
- `backend/app/services/collector_bridge.py` — 采集监控
- `backend/app/services/task_events.py` — SSE 事件
- `backend/app/services/llm_analyzer.py` — LLM 分析
- `backend/app/services/task_planner.py` — **待创建**（缺口1）

### 采集脚本
- `run_workflow.py` — uiautomator2 规则采集
- `run_autoglm.py` — AutoGLM AI 采集
