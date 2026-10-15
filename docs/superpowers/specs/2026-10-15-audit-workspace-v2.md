# 审核工作台 v2：规范库、独立审核、可选项目与规模化驾驶舱

日期：2026-10-15
状态：已确认，待实施
取代：`2026-10-15-audit-projects-v1.md`（v1 在 `feat/audit-projects` 分支未合并，无线上数据，不做迁移）
视觉依据：设计画布「项目走查 · 全周期视觉方案」（https://claude.ai/artifact/TmTte5rWrjZBx9WjxZWCia），五个画面：①项目驾驶舱 ②规范矩阵 ③页面生命线 ④信息架构 ⑤大规模审核驾驶舱

## 1. 目标与边界

三层解耦：

- **规范库**：独立管理规范及其不可变版本；每条规则声明适用载体。
- **审核**：最小单位，H5 或 App 各自独立存在，快照所用规范版本；不属于任何项目时有自己的驾驶舱。
- **项目**（可选）：把多次审核按页面业务键串起来；同时具备上线前与上线后记录时才出现生命周期视图。

审核仍在原处执行（H5 由 CLI 生成 `results.json`，App 由现有任务与 Skill 生成），本功能负责收录、分析、关联与比对。

不做：从界面发起审核或重新采集、截图证据展示（保留观察文字，截图在后续版本接入）、复查/例外工作流按钮、规则跨 ID 映射、PDF 规范解析、新权限角色、修改既有表。

## 2. 数据模型（新增表，`create_all` 建表；删除 v1 的 AuditPage、AuditRecord）

```text
AuditSpec          id, key(唯一 slug), name, description, created_by, created_at, updated_at
AuditSpecVersion   id, spec_id→AuditSpec, version(int, spec 内递增), label, carrier_scope(h5|app|both),
                   rules_json, source_json, sha256, created_by, created_at
                   UNIQUE(spec_id, version)；UNIQUE(spec_id, sha256)；发布即不可变
AuditRun           id, name, carrier(h5|app), phase(pre|post), spec_version_id→AuditSpecVersion,
                   project_id→AuditProject(可空, ON DELETE SET NULL), source_kind(h5_import|app_task_run),
                   source_ref_json, summary_json, created_by, created_at
AuditTarget        id, run_id→AuditRun(CASCADE), business_key(可空), name, outcome, capture_reason(可空),
                   findings_json, summary_json, baseline_target_id→AuditTarget(可空, SET NULL)
                   INDEX(run_id, outcome)；INDEX(business_key)
AuditProject       id, name, description, created_by, created_at, updated_at
```

### 2.1 规则结构（`rules_json` 每项）

```json
{"rule_id": "OV-009", "title": "...", "clause": "四.2 楼层间距", "expected": "...", "strength": "mandatory|conditional|recommended",
 "enabled": true, "carriers": ["h5"], "method": "h5_dom", "duplicate_of": null}
```

导入两种现有格式：

- 官方会场格式（`docs/specifications/official-venue-review/h5-v*.json`）：`id→rule_id`，`title`、`strength`（`conditional_mandatory` 归为 conditional）、`enabled`、`verification_method→method`、`duplicate_of`、首个 `sources[].clause→clause`、`expected`。
- 公共格式（`docs/specifications/dual-entry-inspection.json`，`inspection.Specification`）：`id→rule_id`，`clause` 作为 title 与 clause，`expected`；strength 默认 mandatory，enabled 默认 true。
- `carriers` 取导入时指定的 `carrier_scope`（both 时为 `["h5","app"]`），规则级已有 carriers 时以规则为准。`label` 取原文件 version/rule_version 字段。同一 spec 重复导入相同 sha256 返回已有版本。

### 2.2 审核对象结果（AuditTarget）

- `outcome`：`issues`（有不符合）、`needs_confirmation`（无不符合但有待确认）、`partial`（部分审核，可检项均符合）、`clean`、`capture_failed`。
- `findings_json` 沿用 v1 Finding 结构（rule_id、title、status、observed、reason、evidence）。`summary_json` 为按 status 计数；**`duplicate_of` 非空的规则不计入不符合/待确认计数**（如 OV-023 与 OV-005 共享证据）。
- H5 映射：`results.json` 每个 result 一个 target；`venue.venue_id→business_key`，`venue_name→name`；status 映射 `page_error→capture_failed`、`visible_issues→issues`、`needs_confirmation→needs_confirmation`、`partial_inspection→partial`，其余按 findings 推导。`capture_reason` 由 `audit.page_warnings`/`page_state` 归一：含“迷路”→`offline`，含“过期/已结束”→`expired`，含 login→`login_required`，其他→`other`（保留原文于 `summary_json.capture_detail`）。
- App 收录：选择 TaskRun + 执行 Skill + 规范版本（carrier_scope 含 app），并填写 business_key 与名称（人工对应，必填名称、业务键可空）。findings 按 v1 规则跨图合并；outcome 按 findings 推导。
- 每个 run 的 `summary_json`：targets 总数、按 outcome 计数、capture_reason 计数。

### 2.3 基线与项目

- run 归入项目：`project_id` 可设置/清除。归入时，对该 run 中每个 `phase=post` 且 business_key 非空的 target，若项目内存在同 business_key 的 pre target，自动把最新的一条设为 `baseline_target_id`；无匹配则保持空（界面显示“独立检查”）。
- 手动修改基线：只能指向同一项目内、同 business_key、`phase=pre` 的 target；只有 post target 可设基线。run 移出项目时清空其 targets 的基线及指向它们的基线。
- 页面不再建表：项目页面 = 项目内各 run 的 targets 按 business_key 分组（business_key 为空的 target 以 target 自身为一页）。

## 3. 分析（纯函数，按请求计算，不落库）

### 3.1 比对

沿用 v1 `compare` 的类别与优先级（fixed、still_open、regressed、new_issue、kept、needs_confirmation、not_comparable）。新增：只比对**两侧规范版本中都存在、均 enabled、且 carriers 覆盖各自载体**的规则，其余归 not_comparable；`duplicate_of` 规则不计数。返回 `spec_mismatch`（两侧 spec_version 不同）。

### 3.2 审核驾驶舱（单个 run，对应画面⑤）

- `composition`：按 outcome 计数 + capture_reason 计数。
- `pareto`：每条规则（规范版本内 enabled）的不符合 target 数与待确认数，按不符合降序；可按 outcome 过滤。
- `cooccurrence`：不符合规则两两共现前 5（排除 duplicate_of 对，单列一条“共享证据已合并”的说明）。
- `strips`：可审核 targets（非 capture_failed）的紧凑规则状态串，按严重度排序（不符合数降序、待确认数降序），每个元素 `{id, name, outcome, s}`，`s` 为按规范规则顺序的单字符串（F/U/P/-/x）。用于每格一个会场与热力条码；408 规模下单次响应需 < 200KB。
- `triage`：`focus`（不符合 ≥3 的 targets）、`batches`（恰 1 项不符合的 targets 按规则分组计数及 target id）、`evidence_gaps`（needs_confirmation targets 按规则统计待确认数，前 5）、`recapture`（capture_failed 按 reason 计数，offline 单列）。
- 明细列表：分页（默认 20）、按名称/业务键搜索、按 outcome 过滤、按不符合数/待确认数排序。

### 3.3 项目驾驶舱（对应画面①②③）

- 页面阶段（派生）：`review`（最新 pre 有不符合或待确认且只有一次 pre）、`recheck`（多次 pre 且最新仍有问题）、`baseline`（最新 pre 无不符合）、`post`（存在 post target）、`closed`（最新 post 已关联基线且无不符合、无待确认）。另返回规范阶段信息（项目内 pre/post 所用规范版本）。
- `stages`：各阶段页面数与页面列表（id、名称、点颜色所需的 outcome）。
- `clusters`：`regressed`（含规则、页面、两侧状态）、`systemic`（同一规则在项目内 ≥3 个页面或 ≥30% 页面的最新记录不符合）、`carried`（still_open，按规则聚合并列出同规则已修页面）、`evidence_gaps`（待确认总数与按页面分布）。
- `flow`：所有已关联基线的 post target 的比对汇总，左侧按 pre 状态分组（fail/pass/uncertain/未覆盖），右侧按类别，返回 `{from, to, count}` 边列表。
- `matrix`：页面 × 规则（项目所用 pre 规范版本的 enabled 规则，按 clause 分组），三种模式数据：pre 状态串、post 状态串、变化类别串；以及每条规则在该项目的 pre 分布。
- 页面生命线：该 business_key 下全部 targets 时间线（含 run 名、phase、规范版本、日期、summary），最新 post 与其基线的比对（规则按 需要处理 / 待确认 / 已闭环 分组），每条规则两侧 observed。

## 4. API（`/api/audit-*`，路由级 `get_current_user`；写操作 `require_at_least("operator")`）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET/POST | `/api/audit-specs` | 规范列表（含最新版本、各版本被引用 run 数）/ 新建规范 |
| GET | `/api/audit-specs/{id}` | 规范详情及版本列表 |
| POST | `/api/audit-specs/{id}/versions` | 上传 JSON 导入新版本（multipart `file`，`carrier_scope`） |
| GET | `/api/audit-spec-versions/{id}` | 版本详情含规则 |
| GET | `/api/audit-runs?carrier=&project_id=&unassigned=` | 审核列表 |
| POST | `/api/audit-runs/h5` | 上传 results.json 创建 H5 run（`file`、`spec_version_id`、`name`、可选 `venue_ids`、可选 `project_id`、`phase` 默认 pre） |
| POST | `/api/audit-runs/app` | 收录 App（task_run_id、skill_id、spec_version_id、name、business_key、target_name、phase 默认 post、可选 project_id） |
| GET/PATCH/DELETE | `/api/audit-runs/{id}` | 详情（含 3.2 驾驶舱数据）/ 改名、归入或移出项目 / 删除 |
| GET | `/api/audit-runs/{id}/targets` | 3.2 明细列表 |
| GET | `/api/audit-targets/{id}` | 单个对象结果（findings 全量） |
| PATCH | `/api/audit-targets/{id}` | 设置/清除基线 |
| GET/POST | `/api/audit-projects` | 项目列表（页面数、run 数、当前阶段分布）/ 新建 |
| GET/PATCH/DELETE | `/api/audit-projects/{id}` | 详情（含 3.3 驾驶舱数据）/ 修改 / 删除（runs 保留，project_id 置空） |
| GET | `/api/audit-projects/{id}/matrix` | 3.3 矩阵 |
| GET | `/api/audit-projects/{id}/pages/{page_key}` | 3.3 页面生命线（page_key 为 business_key，或 `t:<target_id>`） |
| GET | `/api/audit-app-candidates` | 可收录的已完成 TaskRun 及 Skill（沿用 v1） |

## 5. 界面（现有前端；视觉以设计画布为准）

导航：“审核”（列表）、“规范库”、“项目走查”。

1. `/specs`、`/specs/:id`：规范列表（载体标签、当前版本、启用规则数、被引用数），版本时间线，规则表（ID、标题、条款、强度、载体、启用、测量方式），导入新版本。
2. `/audits`：H5 / App 分栏的独立审核列表（名称、日期、规范版本、对象数、outcome 构成迷你条、是否归入项目），导入 H5、收录 App。
3. `/audits/:runId`：画面⑤——结果构成条（可点击筛选全页）、每格一个对象（waffle）、规则帕累托 + 共现说明、规则 × 对象热力条码（CSS 渐变绘制，不逐格渲染 DOM）、处理顺序四栏、明细表（分页）。头部：规范版本链接、归入项目。
4. `/audit-targets/:id`：单对象结果，按 需要处理 / 待确认 / 符合 / 不适用 分组的规则列表，可展开 observed 与 reason。
5. `/audit-projects`、`/audit-projects/:id`：画面①——生命周期轨道（阶段可点击筛选）、问题聚类四类、规则流向（SVG Sankey，由 flow 边计算）、页面生命线卡片（上线前/上线后状态条）。页内切换到“规范矩阵”（画面②，三模式 + 列选中侧栏）。
6. `/audit-projects/:id/pages/:pageKey`：画面③——审核轨迹、规则轨迹（上线前 ● — ● 上线后）分组与选中详情（observed 文字，无截图）。

视觉令牌（与画布一致）：底 #0A0C11，面 #11141B/#0E1117，线 #242A36，正文 #E9ECF2，次要 #9AA3B5；上线前 #7AA2FF，上线后 #C49BFF；不符合 #FF6A3D，待确认 #F2C14E，符合 #34D399/#2F9E73，不适用 #2A303C；类别：回归 #FF5A36、未修 #E8875A、新增 #D96BFF、已修 #34D399、保持 #2F7D62。状态必须同时有文字或形状，不只靠颜色。字体沿用现有，不新增依赖。408 规模下页面首屏渲染流畅：热力条码与 waffle 不得为每个规则格创建独立组件。

模拟数据只能来自演示种子脚本，并在界面显示“演示数据”标记（run 的 `source_ref_json.demo=true`）。

## 6. 实施拆分（顺序执行，分支 `feat/audit-projects`）

| 任务 | 内容 | 验收 |
| --- | --- | --- |
| T4 | 模型替换；规范库导入（两种格式）；H5 run 导入（outcome、capture_reason、venue_ids）；App 收录；基线规则；比对的规范适用性；演示种子脚本改写；单元与 DB 测试 | 第 7 节 1–6 |
| T5 | 3.2 / 3.3 分析函数；全部 API；API 测试 | 第 7 节 7–10 |
| T6 | 规范库、审核列表、审核驾驶舱、单对象页 | tsc、build；用真实 408 会场 results.json 浏览器验收 |
| T7 | 项目驾驶舱、规范矩阵、页面生命线 | tsc、build；用种子项目浏览器验收，桌面与 375px |

## 7. 验收情境

1. 导入 `h5-v2..v5.json` 为同一规范的 4 个版本（label、enabled 数 14/13/13/13 正确，`duplicate_of` 保留）；导入 `dual-entry-inspection.json`（carrier app，1 条规则）；重复导入同 sha256 返回已有版本；版本不可修改。
2. H5 导入：用真实结构的小夹具覆盖四种 status 映射与 capture_reason 归一；`venue_ids` 子集；spec_version 的 carrier_scope 不含 h5 时拒绝。
3. 408 规模：真实 `results.json`（约 30MB）导入完成，targets=408，outcome 计数 issues 95 / needs_confirmation 78 / partial 29 / capture_failed 206，offline 195（测试中可标记为手动验证并在报告给出结果）。
4. App 收录：多图合并、无该 Skill 结果拒绝、spec carrier 不含 app 拒绝。
5. 基线：归入项目时按 business_key 自动关联最新 pre；无匹配保持空；手动设置的约束；移出项目清理基线。
6. 比对：v1 全部类别情境保留；规则在一侧版本未启用或载体不适用 → not_comparable；duplicate_of 不计数；spec_mismatch。
7. 审核驾驶舱：composition、pareto、cooccurrence（OV-005/OV-023 作为共享证据单列）、strips 排序与体积、triage 四类、明细分页搜索过滤排序。
8. 项目驾驶舱：五种阶段派生各至少一例；systemic 阈值边界（2 页 vs 3 页）；clusters、flow 边与比对汇总一致；matrix 三模式；页面生命线分组。
9. 权限：未登录 401，viewer 只读，跨对象 ID 404。
10. 既有 `backend/tests` 除已知失败外无新增失败。
