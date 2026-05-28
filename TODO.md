# 竞品分析平台 - 任务总览

> 最后更新：2026-05-27

---

## 一、已完成功能清单

### 1. 前端页面
| 页面 | 功能 | 状态 |
|------|------|------|
| **需求提交页** (`HomePage`) | 用户填写目标App、场景、关键词、描述，提交需求 | ✅ |
| **图片检索页** (`SearchPage`) | 关键词/语义检索竞品截图 | ✅ |
| **数据看板** (`AdminDashboard`) | 统计展示 | ✅ |
| **需求管理** (`AdminRequests`) | 管理员审核通过/拒绝，支持"规则采集"和"AI 采集" | ✅ |
| **任务管理** (`AdminTasks`) | 查看任务列表、启动任务、实时显示采集进度 | ✅ |

### 2. 后端 API
| 接口 | 功能 | 状态 |
|------|------|------|
| `POST /api/requests` | 创建需求 | ✅ |
| `PUT /api/admin/requests/:id/approve` | 审核通过，创建任务（支持选择模式） | ✅ |
| `PUT /api/admin/requests/:id/reject` | 拒绝需求 | ✅ |
| `GET /api/admin/tasks` | 任务列表 | ✅ |
| `POST /api/admin/tasks/:id/run` | 启动任务（启动子进程 + 后台监控） | ✅ |
| `GET /api/admin/tasks/:id/progress` | 获取任务进度 | ✅ |
| `GET /api/admin/tasks/:id/events` | SSE 实时进度推送 | ✅ |
| `POST /api/images` | 创建图片记录 | ✅ |
| `GET /api/images/:id/file` | 直接返回图片文件 | ✅ |
| `POST /api/images/:id/analyze` | 手动触发 LLM 分析 | ✅ |
| `POST /api/search` | 语义检索图片 | ✅ |

### 3. 采集与闭环
| 功能 | 实现 | 状态 |
|------|------|------|
| **uiautomator2 规则采集** | `run_workflow.py` 子进程启动 | ✅ |
| **AutoGLM AI 采集** | `run_autoglm.py` 子进程启动，支持自然语言指令 | ✅ |
| **后台监控入库** | `collector_bridge.py` 每 5 秒扫描 `data/` 目录新截图自动入库 | ✅ |
| **图片关联任务** | 入库时绑定 `task_id` | ✅ |
| **任务完成检测** | 60 秒无新文件自动标记 `completed` | ✅ |
| **SSE 实时推送** | 每发现新截图推送 `{"type":"new_image","count":N}` | ✅ |

### 4. 数据模型
| 实体 | 字段 | 状态 |
|------|------|------|
| **Request** (需求) | id, target_app, target_scenario, keywords, description, status, created_at | ✅ |
| **Task** (任务) | id, name, keyword, target_app, target_scenario, request_id, admin_id, mode, status, created_at | ✅ |
| **Image** (图片) | id, file_path, source_app, scenario, captured_at, task_id, created_at | ✅ |
| **Analysis** (分析) | id, image_id, design_analysis, ops_analysis, status, created_at | ✅ |

### 5. 前端体验
| 功能 | 实现 | 状态 |
|------|------|------|
| 全局 Toast 通知 | `Toast.tsx` + `ToastProvider` + Axios 拦截器 | ✅ |
| 按钮 Loading 状态 | 操作按钮显示"处理中..."防止重复提交 | ✅ |
| 骨架屏 | 列表加载时骨架屏占位 | ✅ |
| 实时进度显示 | 任务列表显示"已采集 N 张" | ✅ |

---

## 二、缺失功能清单（待办）

### 🔴 高优先级

#### TODO-1: LLM 理解需求并生成 AutoGLM 指令（功能2 完整实现）
**当前状态**：只有字符串拼接模板，没有真正调用 LLM 理解用户意图。

**需要实现**：
- [ ] 数据库：`Task` 表新增 `generated_instruction` 字段（存储 LLM 生成的指令）
- [ ] 服务层：新建 `app/services/task_planner.py`
  - 接收 `Request` 对象
  - 调用 LLM（`openai.chat.completions.create`）分析用户需求
  - 生成精确的 AutoGLM 自然语言指令
  - 返回指令文本
- [ ] API 层：`approve_request` 审核通过时调用 `task_planner` 生成指令
  - 将生成结果存入 `task.generated_instruction`
  - `run_task` 时优先使用 `generated_instruction`，回退到 `build_autoglm_prompt`
- [ ] 前端：任务列表/详情展示 AI 生成的指令内容

**LLM Prompt 示例**：
```
你是移动端App自动化专家。请根据以下需求生成一条精确的自然语言指令，
用于驱动AI自动操作手机App并截图：

目标App: {target_app}
目标场景: {target_scenario}
关键词: {keywords}
补充说明: {description}

要求：
1. 指令必须包含"打开App、搜索/导航、截图保存"三个步骤
2. 如果涉及筛选条件（如价格、品牌），要精确描述点击位置
3. 输出只返回指令文本，不要解释
```

#### TODO-2: 图片入库后自动触发 LLM 分析（功能5 完整实现）
**当前状态**：`POST /api/images/:id/analyze` 接口已存在，但图片入库后不会自动触发，需要手动调用。

**需要实现**：
- [ ] `collector_bridge.py` 中 `crud.create_image()` 成功后，异步触发 LLM 分析
  - 方案A：在 bridge 线程中直接调用 `analyzer.analyze_image()`
  - 方案B：新增 Celery/RQ 异步任务队列（更健壮）
- [ ] 前端：图片卡片显示分析状态（分析中 / 已完成 / 失败）
- [ ] 数据库：`Image` 表或 `Analysis` 表新增 `analysis_status` 字段

---

### 🟡 中优先级

#### TODO-3: 任务完成后自动标记并推送完成事件
**当前状态**：60 秒无新文件标记 `completed`，但不会向 SSE 推送完成通知。

**需要实现**：
- [ ] `collector_bridge.py` 任务完成时调用 `push_event(task_id, json.dumps({"type":"completed"}))`
- [ ] 前端 EventSource 监听到 `completed` 事件后自动刷新任务列表

#### TODO-4: 采集脚本与后端的状态同步
**当前状态**：采集脚本（`run_workflow.py` / `run_autoglm.py`）完成后不会主动通知后端。

**需要实现**：
- [ ] 采集脚本退出时通过某种机制通知后端（如写入标记文件，或调用 API）
- [ ] 后端检测到采集结束后停止 `collector_bridge` 监控线程

#### TODO-5: 图片展示页支持分页和筛选
**当前状态**：前端只是简单展示，没有分页。

**需要实现**：
- [ ] 后端 `GET /api/images` 支持分页和按 `task_id` 筛选
- [ ] 前端图片展示页增加分页器和筛选条件

---

### 🟢 低优先级

#### TODO-6: 结果导出功能
- [ ] 支持导出任务结果为 JSON/Excel
- [ ] 支持批量下载图片 ZIP

#### TODO-7: 任务重试机制
- [ ] 任务失败后支持一键重试
- [ ] 自动重试（最多3次）

#### TODO-8: 多设备并发采集
- [ ] 支持同时启动多个设备并行采集
- [ ] 设备管理和选择界面

---

## 三、当前已验证通过

- [x] TypeScript 编译通过（`tsc --noEmit`）
- [x] Python 后端模块加载正常
- [x] 数据库模型定义完整
- [x] API 路由全部注册
- [x] SSE 实时推送正常

---

## 四、下一步建议

**立即执行（补齐功能2和功能5）**：
1. 修改数据库模型，新增 `Task.generated_instruction`
2. 新建 `task_planner.py`，接入 LLM 生成指令
3. 修改 `approve_request` 和 `run_task` 流程
4. 修改 `collector_bridge.py`，入库后自动触发分析
5. 前端增加指令展示和分析状态展示

完成以上后，6 大功能（用户提交 → LLM理解 → AutoGLM执行 → 入库 → LLM分析 → 前台展示）将完整闭环。
