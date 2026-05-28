# 竞品分析平台 — 项目状态总览

> 生成时间：2026-05-27

---

## 一、已完成功能（✅）

### 1. 用户提交需求
- 前端表单页面（HomePage）收集：目标 App、场景、关键词、补充说明
- POST `/api/requests` 入库，状态为 `pending`

### 2. 管理员审核与任务创建
- 需求列表页（AdminRequests）展示所有待审核需求
- 管理员可选择：
  - **规则采集**（uiautomator2）
  - **AI 采集**（AutoGLM）
- 审核通过后自动生成 Task，状态为 `pending`

### 3. 任务启动与采集执行
- 任务列表页（AdminTasks）点击"启动"
- 后端根据 `task.mode` 分发执行：
  - `autoglm` → 调用 `run_autoglm.py`（传入拼接的 prompt）
  - `uiautomator2` → 调用 `run_workflow.py`（传入 TB_KEYWORD 环境变量）

### 4. 采集闭环（图片自动入库）
- 后台监控线程 `collector_bridge.py` 每 5 秒扫描 `data/` 目录
- 新截图自动调用 `crud.create_image()` 入库并关联 `task_id`
- 60 秒无新文件 → 自动标记任务 `completed`

### 5. 图片静态访问
- 新增 `GET /api/images/{id}/file` 直接返回图片文件
- 前端 `ImageCard` 通过该端点加载图片，避免静态路径问题

### 6. 实时进度推送（SSE）
- 后端 `GET /admin/tasks/{id}/events` SSE 端点
- 采集线程每发现新截图推送 `{"type":"new_image","count":N}`
- 前端 `AdminTasks` 自动监听 running 任务的事件流，实时更新截图数量

### 7. 图片检索与分析接口
- `POST /api/search`：支持关键词搜索 + 相似图搜索（pgvector）
- `POST /api/images/{id}/analyze`：手动触发 LLM 分析
- LLM 分析分为：设计分析（design_analysis）+ 运营分析（ops_analysis）

### 8. 全局 UI 体验
- Toast 通知系统（API 错误自动弹出、操作成功提示）
- Loading 状态（按钮禁用 + 文案变化）
- 骨架屏、空状态、hover 动效

---

## 二、待办功能（❌ / 🟡）

### P0 — 高优先级（阻塞完整闭环）

#### 1. LLM 理解需求并生成 AutoGLM 可执行指令
- **现状**：`build_autoglm_prompt()` 只是字符串拼接（"打开App→搜索→截图"），没有真正理解用户意图
- **缺失**：没有用 LLM 分析用户需求，生成精确的、可执行的自然语言指令
- **方案**：
  1. `Task` 表新增 `generated_instruction` 字段
  2. 新建 `app/services/task_planner.py`，调用 LLM 将需求转为 AutoGLM 指令
  3. `approve_request` 时调用 `task_planner` 生成指令并存入 task
  4. `run_task` 使用 `task.generated_instruction` 替代简单的字符串拼接
- **工作量**：约 2 小时

#### 2. 图片入库后自动触发 LLM 分析
- **现状**：图片入库后分析完全靠手动调用 `POST /images/{id}/analyze`，不会自动触发
- **缺失**：用户上传/采集的图片没有自动得到设计+运营分析
- **方案**：
  1. `collector_bridge.py` 中 `crud.create_image()` 成功后，异步调用 `llm_analyzer.analyze_image()`
  2. 或者改为前端轮询检测新图片后自动触发分析
- **工作量**：约 1 小时

### P1 — 中优先级（体验优化）

#### 3. 任务启动后自动将状态流转到 completed（当前靠 60 秒空闲推断）
- AutoGLM/uiautomator2 脚本执行完毕后没有回调通知后端
- 建议：脚本退出时调用 `POST /admin/tasks/{id}/complete`

#### 4. 前端展示 LLM 生成的指令文案
- 在 AdminTasks 任务详情/列表中展示 AI 生成的指令，让管理员知道 AutoGLM 会执行什么

#### 5. 图片分析状态可视化
- ImageCard 上显示分析状态（未分析 / 分析中 / 已完成）
- 分析完成后展示设计+运营分析的摘要卡片

### P2 — 低优先级（锦上添花）

#### 6. 批量操作
- 批量审核、批量启动任务

#### 7. 采集脚本异常处理
- 当前 `subprocess.Popen` 启动后完全不管，脚本崩溃/设备未连接无感知
- 建议增加进程监控和错误回调

#### 8. 数据看板（AdminDashboard）
- 当前 Dashboard 是空壳，应展示：总需求数、总图片数、待分析数、最近 7 天趋势

#### 9. 用户权限与登录
- 当前 admin_id 写死为 "admin"，无真实用户系统

#### 10. 图片裁剪后重新入库
- `step2-cut_img.py` 裁剪后的图片目前不入库，应该也关联 task_id 并入库

---

## 三、功能清单 vs 实现状态对照表

| # | 用户要求的功能 | 实现状态 | 备注 |
|---|-------------|---------|------|
| 1 | 用户通过前端页面提交任务 | ✅ 已实现 | HomePage 表单 |
| 2 | 任务通过 LLM 分析，生成 AutoGLM 可执行指令 | ❌ **未实现** | 当前只是字符串拼接，没有调 LLM |
| 3 | AutoGLM 执行后，任务+图片汇总到数据表 | ⚠️ 部分实现 | 图片自动入库，但任务完成靠空闲推断 |
| 4 | 前端展示任务相关信息 | ✅ 已实现 | AdminTasks 列表 + SSE 实时进度 |
| 5 | LLM 从设计和运营角度分析图片，汇总到数据表 | ⚠️ 部分实现 | 分析接口存在但不会自动触发 |
| 6 | 用户在前台看到任务、图片、分析内容 | ✅ 已实现 | ImageCard 展示图片+分析 |

---

## 四、下一步建议

1. **立即补齐 P0-1**：LLM 生成指令（缺口最大）
2. **紧接着补齐 P0-2**：自动触发 LLM 分析
3. 完成 P0 后，整个平台形成完整闭环：
   ```
   用户提交需求
     → LLM 理解并生成指令
     → 管理员审核并启动
     → AutoGLM 执行采集
     → 截图自动入库
     → LLM 自动分析（设计+运营）
     → 前端实时展示进度与结果
   ```
