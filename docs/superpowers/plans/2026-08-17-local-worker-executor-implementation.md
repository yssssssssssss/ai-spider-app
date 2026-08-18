# 本地 Worker 执行器 - Implementation Plan

> **执行规则**: 开发前必须先阅读 `docs/superpowers/specs/2026-08-17-local-worker-executor-design.md`。每个阶段必须保持系统可运行；不允许把 worker 做成可访问数据库或 OSS 的第二后端。

**Goal:** 让云端平台通过本地 worker 控制本地 USB/ADB 手机执行截图任务，并将截图、日志、状态安全回传云端。

**Architecture:** FastAPI worker API + PostgreSQL task_run lease + 本地 Python worker CLI + 现有 `run_workflow.py` / `run_autoglm.py` 的 `local_files` capture sink。

**Tech Stack:** Python, FastAPI, SQLAlchemy, PostgreSQL, httpx, adb/uiautomator2, existing Open-AutoGLM.

**Current status (2026-08-17):** Phase 1/2 cloud control loop, local worker CLI, and CAPTURE_SINK=local_files are implemented locally. Backend regression and frontend build pass. Remaining gate is real-device end-to-end validation and cloud deployment configuration.

---

## Phase 1: 云端 worker 调度合同

**目标:** 云端能识别 worker 设备，创建 worker queued run，并支持 worker claim。完成后旧的 Web、分析、对比功能保持可用；手机任务可以排队但还不要求本地执行完成。

**Files:**

- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/crud.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/routers/worker.py`
- Modify: `backend/app/services/task_queue.py`
- Create: `backend/app/services/worker_dispatch.py`
- Modify: `.env.example`

- [x] **Step 1: 扩展 TaskRun 模型**

  在 `backend/app/models.py` 的 `TaskRun` 增加：

  - `worker_node_key = Column(String, nullable=True)`
  - `worker_claimed_at = Column(DateTime, nullable=True)`
  - `worker_lease_expires_at = Column(DateTime, nullable=True)`
  - `worker_error = Column(Text, nullable=True)`
  - `artifact_count = Column(Integer, default=0)`

- [x] **Step 2: 启动迁移补列**

  在 `backend/app/database.py::ensure_schema()` 中对 `task_runs` 增加对应 `_ensure_column` 调用，并确保 `artifact_count` 默认 0。

- [x] **Step 3: 扩展 schemas**

  在 `backend/app/schemas.py` 增加 worker 请求/响应模型：

  - `WorkerClaimRequest`
  - `WorkerTaskRunOut`
  - `WorkerClaimOut`
  - `WorkerRunHeartbeatRequest`
  - `WorkerRunFinishRequest`
  - `WorkerRunFailRequest`
  - `WorkerArtifactOut`

- [x] **Step 4: 新建 worker_dispatch 深模块**

  创建 `backend/app/services/worker_dispatch.py`，对外只暴露这些函数：

  - `is_worker_device(device) -> bool`
  - `reap_expired_worker_runs(db) -> int`
  - `claim_next_run(db, node_key, device_serials, capabilities) -> WorkerClaimOut`
  - `extend_run_lease(db, run_id, node_key) -> datetime`
  - `finish_worker_run(db, run_id, node_key, exit_code, screenshot_count) -> TaskRun`
  - `fail_worker_run(db, run_id, node_key, exit_code, failure_reason) -> TaskRun`

  这些函数内部处理事务、状态变更、设备 busy/online 释放和启动下一条 queued task。

- [x] **Step 5: 完善 worker claim API**

  修改 `backend/app/routers/worker.py`：

  - `POST /worker/task-runs/claim` 返回 `WorkerClaimOut`
  - `POST /worker/task-runs/{run_id}/heartbeat`
  - `POST /worker/task-runs/{run_id}/finish`
  - `POST /worker/task-runs/{run_id}/fail`

- [x] **Step 6: 修改 task_queue 分流逻辑**

  修改 `backend/app/services/task_queue.py`：

  - worker 设备不在云端调用 `start_task_process()`
  - worker 设备任务创建 queued run
  - claim 时才把 task/run/device 标记 running/busy
  - 云端本机 ADB 设备继续走旧逻辑

- [x] **Step 7: 配置项**

  在 `backend/app/config.py` 和 `.env.example` 增加：

  - `WORKER_LEASE_SECONDS=300`
  - `WORKER_POLL_SECONDS=5`
  - `WORKER_DEVICE_STALE_SECONDS=30`

- [x] **Step 8: 单元测试 worker 调度**

  新增或扩展后端测试，覆盖：

  - token 缺失/错误
  - worker 上报设备
  - worker claim queued run
  - 非持有 worker 无法 finish/fail
  - lease 过期释放设备
  - worker 设备不会触发云端 `start_task_process()`

  已覆盖 token、设备上报、claim、非持有 worker 拒绝、非图片拒绝、重复 artifact 去重、finish 无图失败、worker 设备不触发云端子进程。lease 过期释放保留为 Phase 5 故障验收 gate。

- [x] **Step 9: 验证 Phase 1**

  Run:

  ```bash
  python3 -m unittest backend.tests.test_flow_regressions
  npm --prefix frontend run build
  ```

  Manual:

  ```bash
  curl -H "X-Worker-Token: $WORKER_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"node_key":"local-dev","devices":[{"serial":"demo-device","status":"online"}]}' \
    http://127.0.0.1:8000/api/worker/devices
  ```

  自动验证已完成：后端回归 129 个用例通过，前端 production build 通过。curl 手工模拟留到云端部署后执行。

---

## Phase 2: Artifact 上传和云端入库

**目标:** worker 能把本地截图上传给云端，云端保存文件、去重、入库、触发现有分析。完成后可以用 curl 手工模拟 worker 上传截图。

**Files:**

- Modify: `backend/app/routers/worker.py`
- Modify: `backend/app/services/worker_dispatch.py`
- Modify: `backend/app/crud.py`
- Modify: `backend/app/services/collector_bridge.py` if image finalization logic should be reused
- Modify: `backend/app/services/oss_uploader.py` only if upload result needs structured error reuse
- Add tests under `backend/tests/`

- [x] **Step 1: 增加 artifact 接收函数**

  在 `worker_dispatch.py` 增加：

  - `save_worker_artifact(db, run_id, node_key, file, metadata) -> WorkerArtifactOut`

  它负责校验 run 持有者、扩展名、sha256、保存路径、去重、创建 Image、触发分析。

- [x] **Step 2: 增加 artifact API**

  在 `worker.py` 增加：

  ```text
  POST /worker/task-runs/{run_id}/artifacts
  ```

  `multipart/form-data` 字段按设计文档执行。

- [x] **Step 3: 增加日志上传 API**

  在 `worker.py` 增加：

  ```text
  POST /worker/task-runs/{run_id}/logs
  ```

  `Content-Type: text/plain`，单次最大 256KB，追加到现有 run log 文件。

- [x] **Step 4: 去重规则**

  同一 `task_run_id + sha256` 的 artifact 只创建一张 Image。若当前没有独立 artifact 表，则用 `images.file_path` 中包含的 sha256 文件名查重。

- [x] **Step 5: OSS 失败降级**

  OSS 上传失败时仍创建 Image，`oss_url/oss_key` 为空，日志记录错误。采集任务不因为 OSS 单点失败而失败。

- [x] **Step 6: Artifact 测试**

  覆盖：

  - png 上传成功
  - 非图片扩展名拒绝
  - 其他 worker 上传被拒绝
  - 重复 sha256 不重复入库
  - finish 时 0 artifact 失败
  - finish 时有 artifact 完成并释放设备

- [ ] **Step 7: 验证 Phase 2**

  用 curl 模拟 worker 上传一张本地测试图片，确认：

  - `data/tasks/<task_id>/runs/<run_id>/worker_uploads/` 有文件
  - `images` 表有记录
  - 任务详情页能看到图片
  - 重复上传返回 `duplicate=true`

---

## Phase 3: 本地 worker CLI

**目标:** 本地 worker 能发现 ADB 设备、上报设备、领取任务、执行空任务/模拟任务、上传日志和截图。完成后不要求 AutoGLM 全链路，但 worker 主循环必须稳定。

**Files:**

- Create: `worker/__init__.py`
- Create: `worker/main.py`
- Create: `worker/client.py`
- Create: `worker/adb_devices.py`
- Create: `worker/executor.py`
- Create: `worker/artifacts.py`
- Create: `worker/requirements.txt`
- Create: `worker/README.md`
- Create: `scripts/start_local_worker.sh`

- [ ] **Step 1: 清理历史 pyc**

  删除 `worker/__pycache__`，新增真实源码。不要从 pyc 反编译逻辑。

  当前保留历史 pyc，已新增真实源码；删除 pyc 可在清理提交时单独处理。

- [x] **Step 2: WorkerClient**

  `worker/client.py` 实现：

  - `register()`
  - `heartbeat()`
  - `report_devices(devices)`
  - `claim(device_serials, capabilities)`
  - `extend_lease(run_id)`
  - `upload_artifact(run_id, path, metadata)`
  - `upload_log(run_id, text)`
  - `finish(run_id, exit_code, screenshot_count)`
  - `fail(run_id, exit_code, failure_reason)`

- [x] **Step 3: ADB 设备发现**

  `worker/adb_devices.py` 调用 `adb devices` 并返回：

  ```python
  [{"serial": "...", "status": "online" | "offline", "notes": "..."}]
  ```

  `adb` 不存在时返回空列表并打印明确错误。

- [x] **Step 4: Artifact 扫描**

  `worker/artifacts.py` 实现：

  - 扫描 png/jpg/jpeg/webp
  - 排除 `_temp_` 文件
  - 计算 sha256
  - 按 mtime + 文件名排序
  - 记录已上传 sha256，避免重复上传

- [x] **Step 5: Executor**

  `worker/executor.py` 根据 `mode` 生成命令：

  - `uiautomator2`: env + `python run_workflow.py`
  - `autoglm`: `python run_autoglm.py "<prompt>" ...`

  stdout/stderr 写入 `worker_runs/<run_id>/worker.log`。

- [x] **Step 6: 主循环**

  `worker/main.py` 实现：

  - 解析 CLI 参数
  - register until ready
  - 每轮 report devices
  - claim
  - claim 到任务后执行
  - 执行期间每 30 秒续租
  - 进程结束后上传 artifacts 和日志尾部
  - finish 或 fail

- [x] **Step 7: 本地 worker README**

  `worker/README.md` 写清楚：

  - ADB 安装和手机授权
  - worker 安装依赖
  - 环境变量
  - 启动命令
  - 常见错误：no device、unauthorized、token 401、server unreachable

- [x] **Step 8: start_local_worker 脚本**

  `scripts/start_local_worker.sh` 默认从 `.env.worker.local` 读取：

  - `WORKER_BASE_URL`
  - `WORKER_API_TOKEN`
  - `WORKER_NODE_KEY`

  并执行 `python -m worker.main`。

- [ ] **Step 9: 验证 Phase 3**

  本地执行：

  ```bash
  python -m worker.main --base-url http://127.0.0.1:8000 --token "$WORKER_API_TOKEN" --node-key local-dev --repo-root .
  ```

  预期：

  - 云端设备页出现本地设备
  - 无任务时 claim 返回空并继续轮询
  - 手动 queued 任务后 worker 能 claim
  - 模拟截图文件能上传为 Image

---

## Phase 4: 采集脚本 capture_sink 解耦

**目标:** `run_workflow.py` 和 `run_autoglm.py` 在 worker 模式下只保存本地截图，不直接上传 OSS 或写数据库。默认行为保持不变。

**Files:**

- Modify: `run_workflow.py`
- Modify: `run_autoglm.py`
- Modify: `backend/app/services/long_screenshot.py`
- Modify: `backend/app/scripts_common.py` if a shared helper is needed
- Add/modify tests under `backend/tests/`

- [x] **Step 1: 定义 capture sink helper**

  新增轻量 helper：

  ```python
  def capture_sink() -> str:
      return os.getenv("CAPTURE_SINK", "cloud").replace("-", "_")
  ```

  有效值只有 `cloud` 和 `local_files`。其他值直接 raise。

- [x] **Step 2: run_workflow.py 改造**

  在 `_screenshot()` 中：

  - `cloud`: 保留 `oss_uploader.upload()`
  - `local_files`: 保存截图后返回，不上传 OSS

- [x] **Step 3: run_autoglm.py 改造**

  在 `_process_screenshot_bytes()`、`_capture_and_save()` 中：

  - `cloud`: 保留上传和 `save_image_to_db`
  - `local_files`: 只写文件并返回路径

- [x] **Step 4: 长图截图改造**

  `capture_product_detail_long_image()` 支持 worker 模式：

  - 输入仍是 device_id、output_dir、screen_count
  - 输出最终长图文件路径
  - 不直接上传 OSS 或写 DB

- [x] **Step 5: CLI 参数**

  `run_autoglm.py` 增加：

  ```text
  --capture-sink cloud|local-files
  ```

  CLI 参数优先级高于环境变量。

- [ ] **Step 6: 回归测试**

  覆盖：

  - 默认不设置 `CAPTURE_SINK` 时仍为 `cloud`
  - `local_files` 不调用 OSS 上传
  - 无效 sink 抛错
  - worker 输出目录存在截图

- [ ] **Step 7: 验证 Phase 4**

  本地手机连接后执行：

  ```bash
  CAPTURE_SINK=local_files TASK_OUTPUT_DIR=/tmp/ai-spider-worker-test PHONE_AGENT_DEVICE_ID=<serial> python run_workflow.py
  ```

  预期：`/tmp/ai-spider-worker-test` 有截图文件，云端数据库不被本地脚本直接写入。

---

## Phase 5: 端到端联调与云端部署

**目标:** 用户从云端页面启动任务，本地 worker 控制本地手机截图，云端展示结果。

**Files:**

- Modify: `scripts/sync_to_cloud.sh` only if deploy verification should check worker API
- Modify: `docs/TODO.md` to link this plan
- Modify: `docs/TASK_STATUS.md` with final status after verification
- Modify: `.env.example`

- [ ] **Step 1: 云端配置 worker token**

  在云端 `backend/.env` 设置：

  ```text
  WORKER_API_TOKEN=<random-strong-token>
  WORKER_LEASE_SECONDS=300
  WORKER_POLL_SECONDS=5
  WORKER_DEVICE_STALE_SECONDS=30
  ```

- [ ] **Step 2: 部署云端**

  Run:

  ```bash
  AI_SPIDER_SSH_TARGET='root@xy1-gcs.jdcloud.com -p 20033' scripts/sync_to_cloud.sh --skip-tests
  ```

  如果现有部署脚本不支持带端口 target，使用当前已验证的 scp/ssh release 流程部署。

- [ ] **Step 3: 启动本地 worker**

  Run:

  ```bash
  scripts/start_local_worker.sh
  ```

- [ ] **Step 4: 设备页验收**

  在云端页面打开设备管理：

  - 本地手机显示 online
  - notes 包含 `worker:<node_key>`
  - 手动断开手机后下一轮上报显示 offline

- [ ] **Step 5: 普通任务验收**

  创建 `uiautomator2` 任务：

  - 选择本地 worker 设备
  - 点击运行
  - 手机真实操作
  - 云端任务状态 running -> completed
  - 云端结果页出现截图
  - 后端日志无 traceback

- [ ] **Step 6: AutoGLM 任务验收**

  创建 `autoglm` 任务：

  - worker 本地配置 `PHONE_AGENT_BASE_URL`
  - 手机真实操作
  - 截图上传云端
  - 任务 completed 或在登录页安全停止并按规则入库截图/失败原因

- [ ] **Step 7: 故障验收**

  覆盖：

  - worker token 错误
  - worker 执行中断
  - 手机 unauthorized
  - worker 上传重复图片
  - worker finish 但 0 张图
  - 云端重启后旧 lease 过期释放

- [ ] **Step 8: 更新状态文档**

  更新：

  - `docs/TODO.md`: 链接本计划，标记 worker 执行器状态
  - `docs/TASK_STATUS.md`: 记录端到端验收结果
  - `worker/README.md`: 补充真实启动命令和排障记录

---

## Final acceptance checklist

- [ ] 云端不安装 adb 也能运行手机采集任务
- [x] 本地 worker 不持有数据库连接串
- [x] 本地 worker 不持有 OSS key
- [x] worker 设备在云端设备页可见
- [x] worker claim 后任务状态变 running
- [ ] 本地手机真实执行
- [x] 截图回传云端并入库
- [ ] 截图触发 LLM 分析
- [ ] worker 中断后任务不会永久 running
- [x] 重复上传不会重复入库
- [x] 现有云端页面、搜索、分析、对比功能不回退
- [x] `npm --prefix frontend run build` 通过
- [x] 后端回归测试通过
