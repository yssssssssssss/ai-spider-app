# 竞品分析平台 - TODO

> 最后更新：2026-06-03

## 已完成

- [x] LLM 需求理解并生成 AutoGLM 指令
- [x] 图片入库后自动触发 LLM 分析
- [x] 图片分析结果生成 embedding 并写入 pgvector
- [x] Doubao embedding 接入并通过 live health 验证
- [x] embedding 写入幂等化，按 `analysis_id + content_type` 去重
- [x] 向量搜索结果按 analysis 去重，避免同一图片重复展示
- [x] 历史 analysis 全量回填 embedding
- [x] 数据库清理孤儿 embedding，并增加唯一索引与非空约束

### 分析 skill 与自定义分析维度

- [x] 新增用户自定义分析 skill
- [x] 支持 Markdown 文本和 `.md` 上传
- [x] 支持官方 skill 和管理员管理
- [x] 任务与持续观察计划按创建时 skill 快照分析
- [x] 自定义维度结果可展示、搜索、导出

## P1 已完成

- [x] 任务列表展示 AI 生成指令
  - [x] `AdminTasks` 增加 AI 指令列
  - [x] 支持 hover 查看完整 `generated_instruction`

- [x] 展示 embedding 状态
  - [x] 图片卡片展示已向量化 / 待向量化 / 向量化失败
  - [x] 向量化失败时展示错误摘要

- [x] 统一 SSE 事件格式
  - [x] 将新图片 / 完成 / 错误事件改为 JSON 格式
  - [x] 前端按事件类型处理新图片、完成、失败

- [x] 图片接口分页和筛选；整体查看由图片检索承担，单任务查看由任务结果页承担
  - [x] 后端 `GET /api/images` 支持分页、`task_id`、分析状态、向量化状态筛选
  - [x] 独立图片管理页已移除；整体图片查看通过图片检索，单任务图片查看通过任务结果页

## P2 已完成

> 执行原则已落地：每个 P2 大项均补充了最小可验证用例或回归测试，并同步模型、schema、`ensure_schema`、接口、前端和文档。

### P2.1 用户权限和登录系统

#### 目标

已将 `anonymous` / 文本 `admin_id` 的松散身份记录升级为用户表、登录态、角色权限和任务归属关系。

#### 数据库与迁移

- [x] 新增 `users` 表
  - [x] `id UUID primary key`
  - [x] `username` 唯一，不允许空
  - [x] `display_name`
  - [x] `password_hash`，禁止保存明文密码
  - [x] `role`：`admin` / `operator` / `viewer`
  - [x] `status`：`active` / `disabled`
  - [x] `created_at`、`updated_at`、`last_login_at`
- [x] 会话方案评估
  - [x] 当前采用短期 HMAC JWT，不建 `user_sessions` / `refresh_tokens`，避免过度设计
  - [x] 登出由客户端清 token 完成；如后续需要踢人/在线审计，再增加 session 表
- [x] 修改现有归属字段
  - [x] `requests.user_id` 保留文本兼容，写入真实用户 UUID 字符串或系统用户
  - [x] `tasks.admin_id` 保留兼容，同时新增 `approved_by`
  - [x] `tasks` 新增 `created_by` / `run_by`
  - [x] `watch_plans` 新增 `created_by`、`updated_by`
- [x] 历史数据回填
  - [x] 创建系统用户 `system`，承接旧的 `anonymous`
  - [x] 创建默认管理员用户，承接已有文本 `admin_id`
  - [x] 回填后旧数据仍能在列表和详情页展示
- [x] 数据库初始化
  - [x] 更新 `models.py`
  - [x] 更新 `schemas.py`
  - [x] 更新 `crud.py`
  - [x] 更新 `database.ensure_schema()`

#### 后端认证与权限

- [x] 新增认证服务
  - [x] 标准库 PBKDF2 密码哈希与校验
  - [x] HMAC-SHA256 JWT 签发与校验，`JWT_SECRET` 来自环境变量或开发默认值
  - [x] 当前用户依赖 `get_current_user`
  - [x] 角色依赖 `require_roles(...)` / `require_at_least(...)`
- [x] 新增认证接口
  - [x] `POST /api/auth/login`
  - [x] `POST /api/auth/logout`
  - [x] `GET /api/auth/me`
  - [x] `POST /api/admin/users`
  - [x] `GET /api/admin/users`
  - [x] `PATCH /api/admin/users/{user_id}`
- [x] 接口权限矩阵
  - [x] 未登录：只能提交公开需求或访问登录接口
  - [x] `viewer`：可查看结果、搜索、持续观察报告，不可启动任务、审批、导出 ZIP、管理用户
  - [x] `operator`：可审批需求、启动任务、管理持续观察，不可管理用户
  - [x] `admin`：拥有全部权限，包括用户管理
- [x] 接入现有接口
  - [x] `POST /api/requests` 写入当前用户 ID；未登录时写入系统用户/历史兼容值
  - [x] 审批需求时写入 `approved_by`
  - [x] 启动任务时写入 `run_by`
  - [x] 持续观察创建/更新/暂停/恢复/立即运行均校验权限并记录用户
  - [x] 导出接口校验登录和角色，ZIP 对 viewer 禁用

#### 前端页面与交互

- [x] 新增登录页
  - [x] 用户名输入
  - [x] 密码输入
  - [x] 登录失败提示
  - [x] 登录中禁用按钮
- [x] 登录态管理
  - [x] API 自动附带 token
  - [x] 401 自动跳转登录页
  - [x] 页面刷新后恢复当前用户
  - [x] 退出登录清空 token
- [x] 路由守卫
  - [x] 后台页面要求登录
  - [x] 管理页面按角色限制
  - [x] 权限不足展示明确提示
- [x] 导航与页面显示
  - [x] 导航栏展示当前用户并提供退出入口
  - [x] 根据角色隐藏或禁用按钮
  - [x] 任务列表展示创建人/审批人/执行人
  - [x] 需求列表展示提交人
  - [x] 持续观察列表展示创建人

#### 测试与验收

- [x] 后端测试
  - [x] 密码不会明文保存
  - [x] 登录 token 可解析用户身份
  - [x] 禁用用户状态可更新
  - [x] 未登录访问后台接口返回 401
  - [x] 低权限访问管理用户接口返回 403
  - [x] 需求、任务、观察计划可记录用户 ID
  - [x] 历史数据迁移后仍可查询
- [x] 前端验证
  - [x] 登录页可访问
  - [x] 登录后进入后台
  - [x] 退出后无法访问后台
  - [x] 角色不同按钮可见性正确
  - [x] `npm --prefix frontend run build` 通过

### P2.2 任务失败重试机制

#### 目标

任务失败现在可诊断、可重试、可追踪。重试不会覆盖旧结果，也不会把旧截图混入新结果。

#### 数据库与运行模型

- [x] 新增 `task_runs` 表
  - [x] `id UUID primary key`
  - [x] `task_id`
  - [x] `attempt_no`
  - [x] `status`：`pending` / `running` / `completed` / `failed` / `timeout` / `cancelled`
  - [x] `started_at`、`completed_at`
  - [x] `exit_code`
  - [x] `failure_reason`
  - [x] `log_path`
  - [x] `output_dir`
  - [x] `device_id`
  - [x] `created_by`
- [x] 修改 `images`
  - [x] 增加 `task_run_id`，图片归属到具体运行
  - [x] 保留 `task_id` 作为查询冗余，便于现有列表和搜索兼容
- [x] 迁移历史数据
  - [x] 为已有 task 创建一个 `task_run`
  - [x] 旧图片关联到该 run

#### 后端执行逻辑

- [x] `start_task_process` 接收 `task_run`
- [x] 每次运行创建独立输出目录：`data/tasks/{task_id}/runs/{run_id}/`，有设备时追加 `devices/{serial}`
- [x] collector 只扫描本次 `output_dir`
- [x] 采集进程退出码写入 `task_runs.exit_code`
- [x] 无截图、进程失败、超时都写入明确 `failure_reason`
- [x] 任务总状态由最近一次 run 汇总，历史 run 不删除

#### 后端接口

- [x] `POST /api/admin/tasks/{task_id}/retry`
  - [x] 禁止 running 重试
  - [x] 超过最大重试次数时返回 400
  - [x] 支持可选 `device_id`
- [x] `GET /api/admin/tasks/{task_id}/runs`
- [x] `GET /api/admin/task-runs/{run_id}`
- [x] `GET /api/admin/task-runs/{run_id}/logs`
  - [x] 返回日志尾部，避免一次返回超大日志

#### 前端交互

- [x] 任务列表
  - [x] 失败任务展示“重试”
  - [x] 展示最近失败原因
  - [x] 展示尝试次数
- [x] 任务结果页
  - [x] 支持按 run 查看结果
  - [x] 失败时展示日志摘要
  - [x] 重试中实时刷新状态
- [x] Toast/SSE
  - [x] 重试启动提示
  - [x] 重试完成/失败提示

#### 测试与验收

- [x] 进程非 0 退出会创建 failed run
- [x] 无截图会创建 failed run
- [x] 超时会创建 timeout run
- [x] 重试创建新的 run，不覆盖旧 run
- [x] 新旧 run 图片不会混入
- [x] running 任务不能重试
- [x] 超过最大重试次数会被拒绝
- [x] 前端构建通过

### P2.3 结果导出 JSON / Excel / ZIP

#### 目标

任务和持续观察结果现在可以离线交付、归档和二次分析。导出可打开、可追溯，不导出密钥或内部不安全路径。

#### 导出范围

- [x] 任务结果导出
  - [x] 任务基本信息
  - [x] 每次 run 信息
  - [x] 图片元数据
  - [x] 分析文本
  - [x] 分析状态与向量化状态
  - [x] 图片文件或 OSS URL
- [x] 持续观察导出
  - [x] 观察计划信息
  - [x] 运行记录
  - [x] 快照列表
  - [x] 日摘要
  - [x] 周期报告
- [x] 默认不导出 embedding 原始向量
  - [x] 如后续确实需要，应单独加开关和权限

#### 后端实现

- [x] 新增导出服务
  - [x] 任务 JSON payload
  - [x] 任务 Excel
  - [x] 任务 ZIP
  - [x] 持续观察 JSON payload
  - [x] 持续观察 Excel
- [x] 文件格式
  - [x] JSON 使用 UTF-8，字段稳定
  - [x] Excel 使用多 Sheet：概览、运行记录、图片清单、分析、失败项、周期报告
  - [x] ZIP 包含 `metadata.json`、Excel、图片目录
- [x] 路径安全
  - [x] 图片路径必须解析在项目允许目录内
  - [x] 缺失文件写入 `missing_files.json`，不静默跳过
  - [x] ZIP 内文件名防止路径穿越
- [x] 后端接口
  - [x] `GET /api/admin/tasks/{task_id}/export?format=json|xlsx|zip`
  - [x] `GET /api/admin/watch-plans/{plan_id}/export?format=json|xlsx`
  - [x] 导出接口需要登录和权限

#### 前端交互

- [x] 任务结果页增加导出按钮组
  - [x] JSON
  - [x] Excel
  - [x] ZIP
- [x] 持续观察详情页增加导出按钮组
  - [x] JSON
  - [x] Excel
- [x] 下载中状态
- [x] 导出失败 Toast
- [x] 空结果时明确提示

#### 测试与验收

- [x] 空任务导出成功且结构完整
- [x] 有图片和分析的任务导出成功
- [x] 缺失图片不会导致 ZIP 失败
- [x] 中文文件名和中文内容正常
- [x] Excel 可被读取并包含预期 Sheet
- [x] 权限不足不能导出敏感 ZIP
- [x] 大量图片导出保留后续流式优化空间；当前 ZIP 已避免一次性读取不存在文件

### P2.4 多设备并发采集

#### 目标

支持多台 Android 设备并行执行任务，任务和截图按设备隔离，避免多个采集进程抢同一台设备或污染同一个输出目录。

#### 设备数据模型

- [x] 新增 `devices` 表
  - [x] `id UUID primary key`
  - [x] `serial` 唯一，对应 adb serial
  - [x] `name`
  - [x] `status`：`online` / `offline` / `busy` / `disabled`
  - [x] `last_seen_at`
  - [x] `current_task_run_id`
  - [x] `notes`
- [x] `task_runs` 增加 `device_id`
- [x] 启动任务时写入设备占用关系

#### 设备发现与锁定

- [x] 封装 `adb devices`
  - [x] 在线设备
  - [x] offline 设备
  - [x] unauthorized 设备
- [x] 设备心跳
  - [x] 刷新设备时更新 `last_seen_at`
  - [x] 设备断开时标记 offline
- [x] 调度规则
  - [x] 用户可手动选择设备
  - [x] 未指定设备时自动选择空闲设备
  - [x] busy 设备不能分配新任务
  - [x] 任务结束必须释放设备锁

#### 脚本与采集适配

- [x] `run_autoglm.py`
  - [x] 支持 `--device-id`
  - [x] ADB 命令使用 `adb -s {device_id}`
  - [x] 输出目录包含 task/run/device
- [x] `run_workflow.py`
  - [x] 支持环境变量 `PHONE_AGENT_DEVICE_ID`
  - [x] uiautomator2 连接指定设备
  - [x] 输出目录包含 task/run/device
- [x] `task_runner.py`
  - [x] 启动进程时传入 device id
  - [x] 每个 task_run 使用独立日志文件
- [x] `collector_bridge.py`
  - [x] 只扫描当前 run 的输出目录
  - [x] 图片记录写入 device/run 信息

#### 前端交互

- [x] 新增设备管理页
  - [x] 设备列表
  - [x] 在线/离线/占用状态
  - [x] 当前任务
  - [x] 最近心跳
- [x] 任务启动控件
  - [x] 选择设备
  - [x] 自动分配选项
  - [x] 无空闲设备时后端明确拒绝
- [x] 任务列表显示设备信息

#### 测试与验收

- [x] 无设备时启动任务返回明确错误
- [x] 单设备可正常分配
- [x] 两个任务不能抢同一设备
- [x] 两台设备可并发分配两个任务
- [x] 设备中途断开时任务失败并释放锁
- [x] 任务完成后设备回到 online
- [x] 输出目录互不污染

### P2.5 清理日志、构建产物和敏感配置

#### 目标

清理工作区噪音，降低误提交密钥和生成文件的风险，但不误删业务数据、数据库内容和仍需追溯的任务结果。

#### Git 与配置

- [x] 更新 `.gitignore`
  - [x] `.env`
  - [x] `backend/.env`
  - [x] `.backend.log`
  - [x] `.frontend.log`
  - [x] `.service_pids`
  - [x] `.frontend_pids`
  - [x] `__pycache__/`
  - [x] `*.pyc`
  - [x] `logs/`
  - [x] 临时截图目录
  - [x] 导出产物目录
  - [x] `frontend/dist/`
  - [x] `frontend/node_modules/`
- [x] 新增或更新 `.env.example`
  - [x] 数据库变量
  - [x] LLM 变量
  - [x] embedding 变量
  - [x] OSS 变量
  - [x] JWT/Auth 变量
  - [x] 不包含任何真实密钥
- [x] 明确 `frontend/dist` 策略
  - [x] 不提交构建产物，加入 ignore 并清理已跟踪旧文件

#### 清理命令

- [x] 新增清理脚本或 `manage.py clean`
  - [x] `--dry-run` 默认模式，只列出将删除内容
  - [x] `--apply` 实际删除
  - [x] `--logs` 清理日志
  - [x] `--pycache` 清理 Python 缓存
  - [x] `--dist` 清理前端构建产物
  - [x] `--exports` 清理导出产物
- [x] 明确禁止清理
  - [x] 不删除数据库
  - [x] 不删除业务截图数据
  - [x] 不删除 `.env`，只检查敏感配置风险
  - [x] 运行中的 PID 文件不列入清理目标
- [x] 日志治理
  - [x] 任务日志按 `logs/tasks/{task_id}/{run_id}.log` 归档
  - [x] `python3 manage.py task-logs` 查看最近任务日志
  - [x] `python3 manage.py prune-task-logs --days N` 按天数清理过期任务日志，默认 dry-run

#### 安全检查

- [x] 新增密钥泄露检查
  - [x] 检查常见 key pattern
  - [x] 输出只展示路径、行号、变量名，不展示密钥值
  - [x] 检查 `.env` 是否被 Git 跟踪
  - [x] 检查输出日志中是否包含 API key
- [x] 可选 pre-commit
  - [x] 阻断 `.env`
  - [x] 阻断 `sk-`、AK/SK 等明显密钥
  - [x] 阻断大体积生成产物路径

#### 测试与验收

- [x] dry-run 不删除文件
- [x] apply 只删除允许范围内文件
- [x] 清理后 `python3 manage.py status` 仍可运行
- [x] 清理命令相关后端测试通过
- [x] 清理后前端构建通过
- [x] 敏感文件不会出现在 Git 已跟踪忽略文件列表中

### P2.6 多目标截图覆盖校验

#### 目标

截图任务不再只依赖一句自然语言判断完成，而是生成明确的目标清单，并在结果入库后校验每个必达目标是否真的有截图证据。

#### 后端执行逻辑

- [x] 新增 `target_goals_json`，任务审核时记录必达目标
- [x] 新增 `goal_validation_json`，每次运行记录目标覆盖校验结果
- [x] AutoGLM 指令追加目标截图清单、自动截图说明和完成后停止规则
- [x] 完成 run 时基于已有分析文本校验目标覆盖，缺失必达目标则 run/task 标记失败
- [x] 负向语境不计为命中证据，例如“未出现百亿补贴”不会被判定为已覆盖
- [x] 图片分析异步完成后复核已完成 run，避免分析滞后造成误判

#### 前端交互

- [x] 任务结果页展示目标覆盖总状态
- [x] 展示每个目标的已覆盖、缺失、待确认状态
- [x] 缺失目标时展示失败原因

#### 测试与验收

- [x] 多页面场景可拆出多个必达目标
- [x] AutoGLM 指令包含目标清单和自动截图停止规则
- [x] 只有“限时秒杀”证据时能识别缺少“百亿补贴”
- [x] “未出现百亿补贴”这类负向文本不会误判为命中
- [x] run 完成时缺少必达目标会失败
- [x] 分析完成后的复核可以把误完成 run 改为失败

### P2.7 云端任务队列与本地 Worker

#### 目标

项目支持“云端平台 + 本地设备 Worker”模式：云端负责任务、权限、分析、搜索和结果展示，本地 Worker 负责连接安卓手机并执行采集。

#### 配置与数据模型

- [x] 新增 `EXECUTION_MODE=local|worker`，默认保留 `local`
- [x] 新增 `WORKER_API_TOKEN`，Worker API 通过 `X-Worker-Token` 校验
- [x] 新增 `workers` 表，记录节点、状态、版本、最近心跳
- [x] 扩展 `devices`，记录 `source`、`worker_id`
- [x] 扩展 `task_runs`，记录 `execution_mode`、`worker_id`、`claimed_at`、`heartbeat_at`

#### 后端执行逻辑

- [x] 新增 `TaskExecutor` 执行适配器
- [x] `LocalTaskExecutor` 继续使用原本后端本机执行链路
- [x] `WorkerTaskExecutor` 创建 queued run，等待 Worker 领取
- [x] Worker 领取 run 后将 task/run 标记为 running，并占用对应设备
- [x] Worker 完成后复用现有 `_finish_run`，释放设备并触发目标覆盖校验

#### Worker API

- [x] `POST /api/worker/register`
- [x] `POST /api/worker/heartbeat`
- [x] `POST /api/worker/devices`
- [x] `POST /api/worker/task-runs/claim`
- [x] `POST /api/worker/task-runs/{run_id}/images`
- [x] `POST /api/worker/task-runs/{run_id}/logs`
- [x] `POST /api/worker/task-runs/{run_id}/finish`

#### 本地 Worker 程序

- [x] 新增 `worker/main.py`
- [x] 启动参数支持 `--server`、`--token`、`--node-key`、`--work-dir`
- [x] 使用本机 `adb devices` 上报设备
- [x] 领取任务后执行 `run_autoglm.py` 或 `run_workflow.py`
- [x] 上传截图、日志、完成状态

#### 前端与部署

- [x] 任务列表展示执行模式和 Worker 信息
- [x] 设备管理页展示本机 / Worker 来源
- [x] `.env.example` 补充 Worker 配置
- [x] `.gitignore` 忽略本地 `worker_runs/`
- [x] 当前 local 模式继续可用

### P2.8 对比 JD 终态截图与配对质量

#### 目标

对比 JD 不再把入口、模块、搜索中间页或加载页误判为最终截图；当同一槽位出现更高质量终态截图时，可替换早期低质量占坑，缺失配对时只保留单图分析。

#### 后端执行逻辑

- [x] PageEvidence 增加 `page_state`、`target_role`、`is_terminal_target`、`needs_more_wait`
- [x] 目标覆盖校验只采信终态页面证据；有页面证据时不再用零散分析文本兜底命中
- [x] 多目标校验按 `captured_at/created_at` 稳定排序，截图顺序错误会标记缺失
- [x] JD 对比槽位匹配忽略非终态页面证据
- [x] 同槽位同 App 允许更高置信截图替换旧匹配，并清理基于旧图的 AB 分析
- [x] `run_autoglm.py` 支持 `--source-app`，任务启动时传入 `task.target_app`
- [x] 无自定义 skill 时，AB 对比使用默认设计/运营维度生成结果

#### 测试与验收

- [x] 非终态首页关键词不会命中首页目标
- [x] 多目标截图顺序错误会失败
- [x] 非终态页面证据不会直接进入对比槽位
- [x] 更高质量终态截图可替换同槽位旧匹配
- [x] AutoGLM 启动参数包含正确 `--source-app`
- [x] 空 skill 的 AB 分析仍返回默认维度

## P2 执行结果

1. [x] P2.5 清理日志、构建产物和敏感配置
2. [x] P2.1 用户权限和登录系统
3. [x] P2.2 任务失败重试机制
4. [x] P2.4 多设备并发采集
5. [x] P2.3 结果导出 JSON / Excel / ZIP
6. [x] P2.6 多目标截图覆盖校验
7. [x] P2.7 云端任务队列与本地 Worker
8. [x] P2.8 对比 JD 终态截图与配对质量

## 当前验证快照

- 本轮后端回归测试：133 个通过
- Python 编译检查：通过
- embedding provider：Doubao
- embedding 维度：2048
- `embeddings` 重复组：0
- `embeddings` 孤儿记录：0
- 向量搜索返回：`search_mode=vector`
