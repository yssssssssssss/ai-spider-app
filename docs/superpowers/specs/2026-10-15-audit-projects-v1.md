# 项目走查 v1：上线前后审核记录的归属、关联与比对

日期：2026-10-15
状态：已被 `2026-10-15-audit-workspace-v2.md` 取代（比对类别与 H5/App 解析逻辑在 v2 中沿用）
取代：`2026-10-14-project-lifecycle-audit.md` 中的对话式界面方案（该 demo 保留作参考）

## 1. 目标与边界

在产品中体现“针对一个项目的设计规范全周期审核”：同一项目下，上线前（H5）与上线后（App）的审核记录可以归属到同一页面、手动关联基线，并按规则比对出已修、未修、发布回归。

当前单人使用，审核仍在原处执行：H5 由 CLI 生成 `results.json`，App 由现有任务与规范巡查 Skill 生成。本功能只**收录、关联、比对**结果。

不做：从界面发起审核、自动识别截图对应的会场、对话式界面、规则跨 ID 映射、新增权限角色、修改既有表。

## 2. 数据模型（新增三表，`create_all` 自动建表）

```text
AuditProject  id, name, description, created_by, created_at, updated_at
AuditPage     id, project_id→AuditProject, name, business_key(可空，如会场ID),
              created_at；UNIQUE(project_id, business_key) 当 business_key 非空
AuditRecord   id, page_id→AuditPage, phase(pre|post), carrier(h5|app),
              source_kind(h5_import|app_task_run), source_ref_json,
              spec_key, spec_version, findings_json, summary_json,
              baseline_record_id→AuditRecord(可空), note, created_by, created_at
```

- `source_ref_json`：H5 为 `{file_name, sha256, generated_at, venue_id, project_id}`；App 为 `{task_run_id, skill_id}`。
- `spec_key`/`spec_version`：H5 取 `results.json` 的 `title`/`rule_version`；App 取所选 Skill 的 name/version。规范由用户在收录时选择（H5 随文件确定，App 选 Skill）。
- `baseline_record_id` 只允许指向**同一页面**的 `phase=pre` 记录，且只有 `phase=post` 记录可设置。可修改，修改不影响记录本身的 findings。
- 删除：删项目级联删除页面与记录；删除被引用的 pre 记录时，引用它的 post 记录基线置空。

### 统一 Finding

```json
{"rule_id": "OV-009", "title": "...", "status": "pass|fail|uncertain|not_applicable|disabled",
 "observed": "...", "reason": "...", "evidence": {"kind": "h5_report|app_images", "image_ids": []}}
```

只保存规范结论所需字段，不复制大体积证据。H5 原始 `evidence`、测量、来源等留在原报告。

## 3. 收录

**H5 导入**：上传 `results.json`（实测 30MB/408 会场，需支持）。对每个 `results[]`：按 `venue.venue_id` 在项目内匹配或创建页面（名称取 `venue_name`），创建 `phase=pre, carrier=h5` 记录；findings 取 `audit.checks[]`。同一文件（sha256）重复导入同一项目时跳过已存在的记录并报告数量。可选参数 `venue_ids` 只导入部分会场。

**App 收录**：用户在某页面选择 `task_run_id` 和 `skill_id`，`phase` 默认 `post`，可选择基线。汇总该运行所有图片对应 Skill 的 `Analysis.inspection_json` 检查项，同一 `rule_id` 跨图合并：任一 `fail`→fail；否则任一 `pass`→pass；否则任一 `uncertain`→uncertain；否则 not_applicable。`evidence.image_ids` 记录贡献该结论的图片。运行没有该 Skill 的巡查结果时拒绝收录。

## 4. 比对（纯函数，不落库）

`compare(pre, post)` 以 `rule_id` 对齐两条记录：

| pre → post | 类别 |
| --- | --- |
| fail → pass | `fixed` 已修 |
| fail → fail | `still_open` 未修 |
| pass → fail | `regressed` 发布回归 |
| 缺失/not_applicable/disabled → fail | `new_issue` 上线后新增 |
| pass → pass | `kept` 保持合规 |
| 任一侧 uncertain（且不属上列） | `needs_confirmation` 待确认 |
| 仅一侧存在、或两侧均不适用/未激活 | `not_comparable` 无法比对 |

返回每条规则的类别及两侧 status/observed，以及按类别计数。`spec_key` 或 `spec_version` 不同时照常按共同 rule_id 比对，并返回 `spec_mismatch: true` 供界面提示。

## 5. API（`/api/audit-projects`，沿用 `get_current_user`；写操作 `require_at_least("operator")`）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET/POST | `/api/audit-projects` | 列表（含页面数、各类记录数）/ 创建 |
| GET/PATCH/DELETE | `/api/audit-projects/{id}` | 详情（含页面矩阵行）/ 修改 / 删除 |
| POST | `/api/audit-projects/{id}/pages` | 手动新建页面 |
| GET | `/api/audit-pages/{page_id}` | 页面详情：记录时间线 + 最新 post 与其基线的比对 |
| POST | `/api/audit-projects/{id}/imports/h5` | 上传 results.json 导入 |
| POST | `/api/audit-pages/{page_id}/records/app` | 收录 App 运行 |
| PATCH/DELETE | `/api/audit-records/{id}` | 设置/修改基线、备注 / 删除 |
| GET | `/api/audit-records/{post_id}/compare?pre_id=` | 比对，默认使用其基线 |
| GET | `/api/audit-projects/app-candidates` | 可收录的已完成 TaskRun 及其规范 Skill |

页面矩阵行：页面名、business_key、最新 pre 状态摘要、最新 post 状态摘要、是否已设基线、比对计数（fixed/still_open/regressed/new_issue）。

## 6. 界面（现有前端，结构化页面）

导航新增“项目走查”，路由：

1. `/audit-projects`：项目列表，新建项目。
2. `/audit-projects/:id`：页面 × 上线前 / 上线后 / 比对 的状态表；搜索名称/会场 ID；筛选“有回归”“未设基线”；操作“导入 H5 结果”。
3. `/audit-pages/:id`：时间线（上线前记录 → 基线标记 → 上线后记录）；比对面板按类别分组，默认展开回归与未修，可展开每条规则两侧 observed；“收录 App 结果”对话框（选运行、选 Skill、选基线）；无基线时提示“未关联上线前记录，本轮为独立检查”。

沿用现有组件、样式与 API 封装，不引入新依赖。只展示问题与变化，不铺统计卡片。

## 7. 实施拆分（顺序执行，分支 `feat/audit-projects`）

| 任务 | 内容 | 验收 |
| --- | --- | --- |
| T1 | models、`services/audit_projects.py`（H5 解析、App 汇总、compare）、单元测试 | 第 8 节 1–4 全部通过 |
| T2 | schemas、router、注册、API 测试 | 第 8 节 5–7 通过，既有测试无新增失败 |
| T3 | 前端三页与导航、api.ts | `tsc`、构建通过；用真实 10 例导入走通流程，桌面与 375px 截图验证 |

## 8. 验收情境

1. compare 覆盖第 4 节每一类，含 disabled、not_applicable、仅一侧存在、规范不同。
2. H5 解析：用 `docs/examples/official-venue-pilot10-v3.json` 所选会场构造的小夹具，页面按 venue_id 去重，findings 字段完整，`disabled` 原样保留；重复导入跳过；`venue_ids` 子集导入。
3. App 汇总：多图合并规则（fail 优先等），无该 Skill 结果时报错。
4. 基线约束：不能指向其他页面、不能指向 post、pre 记录不能设基线；删除 pre 后引用置空。
5. API：未登录 401，viewer 不能写；跨项目的 page/record ID 返回 404。
6. 30MB 级 `results.json` 导入可完成（测试中用生成的大文件或标记为手动验证）。
7. 原有 `backend/tests` 除已知 `test_flow_regressions` 外无新增失败。
