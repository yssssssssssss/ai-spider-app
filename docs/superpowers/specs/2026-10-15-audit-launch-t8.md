# T8：从项目发起审核（审核任务与执行器）

日期：2026-10-15
状态：已确认，待实施（范围：T8a + T8b 全部；T8-0 排在 App 真机验收之前）
前置：`2026-10-15-audit-workspace-v2.md`（T4–T7 已完成，分支 `feat/audit-projects`）

## 0. 现状调研结论

v2 只负责收录、分析、比对。审核本身仍在系统外执行。项目页没有任何入口，空项目也只显示 0。

### 0.1 H5（官方会场）

现有链路由本机脚本组成，后端不能触发：

| 步骤 | 工具 | 约束 |
| --- | --- | --- |
| 1 目录 | `scripts/capture_venues.mjs` 的 `VENUE_MODE=catalog` | 必须在 Ego Lite 中运行，使用 `ego-browser nodejs`。提报列表需在同一 TaskSpace 的 `p1` 打开，**由人登录**。抓取会场身份与二维码，再由 `venue_identity.py` 解析出预览 URL。 |
| 2 采集 | `capture_venues.mjs` 的默认模式 | 同一 TaskSpace，每个会场截两屏（390×844），产出 `capture.json`。 |
| 3 审核 | `scripts/rerun_venue_audit.py` | **只能重审**：`prepare()` 必须读取 `source/results.json` 作为基线，并沿用其中的 `page_state`。仓库中**没有首轮审核脚本**。提示词和参考图写死为官方会场规则（OV-xxx，`audit_mode=h5_v2`）。 |
| 4 汇总 | `scripts/build_venue_recheck_report.py` | 产出 `results.json`，由 v2 的 `parse_h5_results` 导入。 |

结论：H5 可以由本机后端串起来执行（后端本来就运行在同一台 Mac 上），但要满足三点：
- 补一个首轮审核模式；
- 登录这一步交回给人处理；
- 执行器只支持 `audit_mode=h5_v2` 的规范。

### 0.2 App（真机）

现有链路完整，后端已经能触发：

`Task`（`analysis_skill_ids`）→ `POST /api/admin/tasks/{id}/run`（`start_or_enqueue_task`）→ Worker 领取 → 真机执行 → 逐张上传截图 → 每张截图异步触发 Skill 分析（`collector_bridge._trigger_analysis`）→ `Analysis.inspection_json` → v2 的 `create_app_run` 收录。

缺口：

1. **规范版本与 Skill 没有关联。** 开发库目前没有 active 的 inspection Skill。规范版本的规则需要转换成 `inspection.Specification`（字段为 id、clause、expected），生成一个 inspection Skill。
2. **完成时机。** `finish` 时截图分析可能还没跑完，收录需要等全部分析结束。
3. **执行质量。** `docs/round1-device-acceptance.md` 记录：通用 AutoGLM 导航**未通过验收**，到达目标页后不停止，未到达时也可能标为 completed。在这个问题修好之前，App 发起的审核可能把错误页面的截图当成审核对象。
4. **运行环境。** 设备和 Worker 最近一次活动是 2026-09-01，需要重新接机。

## 1. 目标与边界

- 引入 **审核任务 AuditJob**：从「发起」到「产出 AuditRun」的过程对象。完成后自动收录；如果发起时选了项目，同时自动归入项目。
- 项目页、审核列表都能发起审核。空项目显示引导：可以发起第一次审核，也可以把已有的独立审核归入进来。
- 执行器按载体分开实现，规范必须有对应的执行器才能发起；没有执行器时界面提示改用导入。

不做：
- 修复 AutoGLM 停止条件（单独立项 T8-0，见第 7 节）；
- H5 上线后（公开页）采集；
- 非官方会场的 H5 规范执行器；
- 自动重试；
- 并发调度多个 H5 任务（Ego 空间只有一个，H5 任务串行执行）；
- 定时巡检。

## 2. 数据模型（新增一张表；不改既有表）

```text
AuditJob  id, name, carrier(h5|app), phase(pre|post), spec_version_id→AuditSpecVersion,
          project_id→AuditProject(可空, ON DELETE SET NULL),
          status, status_detail(文字), input_json, executor_ref_json,
          audit_run_id→AuditRun(可空, ON DELETE SET NULL), error, created_by, created_at, updated_at, finished_at
```

`status` 的取值：
- `queued`：已排队
- `running`：执行中
- `needs_action`：需要人处理，例如登录
- `ingesting`：执行完成，正在收录
- `completed`：已完成
- `failed`：失败
- `cancelled`：已取消

状态转换：

```text
queued → running → ingesting → completed
running → needs_action → running（用户点「继续」）
任意未结束状态 → failed / cancelled
```

`completed`、`failed`、`cancelled` 为终态，进入后不能再变。

`input_json`：
- H5：`{record_ids?: [...], catalog_dir?: str}`，不填则使用最新目录中的全部会场；
- App：`{target_name, business_key?, target_app, scenario, description?, device_id?}`。

`executor_ref_json`：
- H5：`{work_dir, pid?, step}`；
- App：`{skill_id, task_id, task_run_id}`。

## 3. 执行器

### 3.1 App 执行器（T8a）

1. **规范转 Skill**：`ensure_inspection_skill(spec_version)`。
   - 只取 `carriers` 包含 app 的已启用规则，转换为 `Specification`（title=规范名，version=版本 label，source=`audit_spec_version:<id>`）。
   - 按 `specification_json.source` 查找已有 Skill，找到就复用，找不到才新建（`skill_type=inspection`、`is_system=true`）。
   - 规范版本不可变，所以每个版本对应唯一一个 Skill。
2. **建任务并运行**：沿用 `plan_task` 生成指令、`crud.create_task` 建任务（`analysis_skill_ids=[skill]`），再调用与 `run_task` 相同的 `start_or_enqueue_task`。
   - 把 `run_task` 中的启动逻辑抽成共用函数，避免复制。
   - 不经过 Request 审批：发起人本身就是 operator。
3. **对账 `reconcile_job`**：幂等，对 job 行加锁。触发时机有三个：job 读取时、项目页读取时、`finish_worker_run` 和 `fail_worker_run` 结束后。
   - TaskRun 为 `failed`：job 转为 `failed`，`error` 填 `failure_reason`。
   - TaskRun 为 `completed`，但该 run 的图片还有未产生 `Analysis` 的：保持 `ingesting`。
   - 全部分析结束后调用 `create_app_run`（带 `project`）：成功则转为 `completed` 并写入 `audit_run_id`；如果「没有检查结果」，转为 `failed`。
   - `goal_validation_json` 显示没有到达目标页时，转为 `failed`（「目标页未确认到达，未收录」），不收录错误页面。

### 3.2 H5 执行器（T8b，仅限 `audit_mode=h5_v2`）

由本机后端的后台线程依次执行。全局同一时间只跑一个 H5 job，其余排队。

1. **准备**：检查 Ego Lite 是否可用，以及 `p1` 是否停在已登录的提报列表。不满足时转为 `needs_action`，`status_detail` 写明要做什么，例如「在 Ego Lite 打开提报列表并登录后点继续」。
2. **目录**：在 `data/audit-jobs/<job_id>/` 下执行 catalog 模式和身份校验。如果 `input_json.catalog_dir` 指定了已有目录，就直接复用。
3. **采集**：capture 模式。用 `input_json.record_ids` 写成 `VENUE_RECORDS_FILE`，只采集选中的会场。
4. **首轮审核**：给 `rerun_venue_audit.py` 新增 `--fresh` 模式。
   - 不读基线，`page_state` 由模型给出。
   - 规范使用 job 所选版本的 `rules_json`，转换成脚本需要的 profile。
   - 原有重审路径行为不变，现有测试照常通过。
5. **汇总与收录**：先跑 `build_venue_recheck_report.py`，再 `parse_h5_results` → `create_h5_run`（带 project）→ 转为 `completed`。
6. 每一步把进度写入 `executor_ref_json.step` 和 `status_detail`，例如「采集 37/120」。
   - 子进程失败时，`error` 保存 stderr 的最后 2KB。
   - 用户取消时终止子进程，转为 `cancelled`。
   - 后端重启时，还在 `running` 的 H5 job 标为 `failed`（「执行中断」），不做续跑。

## 4. API（`/api/audit-jobs`；写操作需要 operator 权限）

```text
GET  /audit-jobs?project_id=&status=active|all   列表（读取时对进行中的任务对账）
POST /audit-jobs        {name, carrier, phase, spec_version_id, project_id?, input}
GET  /audit-jobs/{id}
POST /audit-jobs/{id}/continue    needs_action → running
POST /audit-jobs/{id}/cancel
GET  /audit-specs/versions/{id}/executor   → {available: bool, reason}  前端用来决定能否发起
```

校验规则：
- 载体必须在规范版本的 `carrier_scope` 内；
- H5 要求规范版本的 `source_json.audit_mode == "h5_v2"`；
- 项目必须存在。

现有的收录 API 保持不变。

## 5. 界面

- **项目驾驶舱**：标题区加「发起审核」按钮。
  - 弹窗依次选择：载体 → 阶段 → 规范版本（默认取项目已绑定的版本）→ 对应载体的输入。
  - 版本不支持自动执行时，显示原因，并提供「改为导入结果」的入口。
- **进行中的任务**：生命周期轨道上方显示进行中的 job 卡片，内容包括状态、`status_detail`、继续和取消按钮。
  - 有进行中的 job 时，每 5 秒轮询一次；job 完成后刷新驾驶舱数据。
- **空项目**：显示两个入口：「发起第一次审核」和「归入已有审核」。后者列出未归入项目的审核，可以多选后批量归入（复用 `assign_run`）。
- **审核列表** `/audits`：加「发起审核」按钮（不带项目），并加「进行中」分区。
- **H5 会场选择**：有目录时，按会场名或 ID 搜索后多选；没有目录时，先跑目录，跑完后进入 `needs_action`，让用户选择会场，再继续。

## 6. 实施拆分

| 任务 | 内容 | 依赖 |
| --- | --- | --- |
| T8a-1 | AuditJob 模型、状态机、API 骨架、`reconcile_job`、项目页的发起入口、空状态、批量归入、进行中卡片 | — |
| T8a-2 | App 执行器：规范转 Skill、抽出共用启动函数、`finish` 和 `fail` 后的对账 hook | T8a-1 |
| T8b-1 | `rerun_venue_audit.py --fresh`，以及规范版本转 profile | — |
| T8b-2 | H5 执行器：后台线程、`needs_action` 交接、取消、重启后标记中断 | T8a-1, T8b-1 |

## 7. 风险与前置

- **T8-0（建议在 T8a-2 真机验收前完成）**：修复 AutoGLM「到达后不停」「错误地标为完成」，在完成前校验最终截图，参见 round1 验收文档。不修的话，App 发起链路可以打通，但收录的数据不可信。
- **H5 依赖人工登录**：Ego 会话过期时，任务会停在 `needs_action`。这是设计行为，不算失败。
- **H5 首轮审核成本**：408 个会场按 6 并发调用模型，要先在小样本上确认耗时和费用；界面在会场数超过 50 时提示预计规模。
- 本机线程模型只适合单人、单机使用。日后部署到服务器时，H5 执行器需要改成 Worker 领取的模式，届时另立 spec。

## 8. 验收情境

1. 在空项目中「归入已有审核」，选 2 个独立 H5 审核 → 驾驶舱出现上线前页面，基线按 business_key 关联。
2. App job（测试中用假 Worker 走 claim → 上传截图 → finish）：截图分析未完成时状态为 `ingesting`，完成后自动出现 AuditRun 并归入项目；TaskRun 失败时 job 为 `failed`，并显示原因；目标未到达时 job 为 `failed`，且不产生 AuditRun。
3. 同一规范版本发起两次 App job，只生成一个 inspection Skill。
4. H5 job：执行器检查不通过时进入 `needs_action`，点「继续」后往下执行；取消时子进程被终止；在 3 个会场的样本上，`--fresh` 的结果能被 `parse_h5_results` 导入，数字和单独导入一致。
5. 规范版本没有对应执行器时，`POST /audit-jobs` 返回 400，界面显示原因和导入入口。
6. 处于终态的 job 再调用 `continue` 或 `cancel` 返回 409。
7. 后端测试全部使用临时库。现有 297 项测试照常通过；新增的状态机测试覆盖第 2 节列出的每一种状态转换。
