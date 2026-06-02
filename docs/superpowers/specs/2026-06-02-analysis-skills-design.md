# 分析 skill 与自定义分析维度 - 设计文档

**日期**: 2026-06-02
**项目**: ai-taobao-app 竞品截图分析能力升级
**阶段**: 方案 B 设计稿

---

## 1. 背景与目标

当前竞品截图分析固定输出两个字段：`design_analysis` 和 `ops_analysis`。这两个维度分别对应设计维度和运营维度，已被数据库、API、搜索、导出、持续观察日报和前端卡片展示直接依赖。

新的目标是把分析维度从固定双字段升级为可由用户自定义的“分析 skill”。用户可以通过文本块或上传 Markdown 文件创建自己的分析维度，并在提交一次性任务或创建持续观察计划时选择要应用的维度。后续截图分析只按该任务或观察计划绑定的维度执行。

本设计采用“分析 skill 库 + 创建时快照 + 动态分析结果 JSONB”的方案，在不破坏现有双字段链路的前提下支持更多分析维度。

---

## 2. 已确认产品决策

| 决策项 | 方案 |
| --- | --- |
| 维度选择粒度 | 按任务 / 持续观察计划选择 |
| skill 创建方式 | 文本块输入 Markdown，或上传 `.md` 文件 |
| Markdown 规则 | 一个文本块或一个 `.md` 文件对应一个分析 skill；一级标题作为名称，正文作为分析指令 |
| 默认维度 | 系统内置官方 skill：设计维度、运营维度 |
| 用户选择规则 | 新任务或新观察计划至少选择 1 个 skill |
| 默认 skill 可取消性 | 官方 skill 默认选中，但用户可以取消 |
| 无自定义 skill 时 | 设计维度 / 运营维度至少选择一个 |
| 有自定义 skill 时 | 可以取消设计维度和运营维度，只保留自定义 skill |
| 管理员权限 | 查看全部 skill 内容，对全部 skill 增删改查，设置或取消官方 skill |
| 用户权限 | 创建、编辑、删除自己的 skill；读取官方 skill；选择自己的 skill 和官方 skill |
| 管理员审批职责 | 只审批任务是否执行，不替用户选择分析维度 |
| 历史数据 | 不迁移、不自动重跑；新能力只影响后续新分析 |
| 任务口径稳定性 | 创建请求 / 观察计划时保存所选 skill 快照，后续 skill 修改不影响已创建对象 |

---

## 3. 不包含范围

1. 不做历史截图批量重分析。
2. 不做 skill 版本树、回滚、审批流。
3. 不做复杂 Markdown DSL，只解析标题和正文。
4. 不做富文本编辑器，文本框和 `.md` 上传足够。
5. 不允许普通用户修改官方 skill。
6. 不让管理员在审批时替用户改选分析维度。

---

## 4. 数据模型

### 4.1 `analysis_skills`

新增分析 skill 主表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 主键 |
| `name` | TEXT, NOT NULL | skill 名称 |
| `instruction_md` | TEXT, NOT NULL | Markdown 分析指令 |
| `owner_id` | UUID, FK -> users | 创建用户；系统内置 skill 可为空或指向 system 用户 |
| `is_official` | BOOLEAN | 是否官方 skill |
| `status` | TEXT | `active` / `disabled` |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

约束与索引：

1. `status` 默认 `active`。
2. `is_official` 默认 `false`。
3. 建议对 `(owner_id, name, status)` 建索引，便于用户自己的 skill 列表查询。
4. 删除采用软删除：`status = disabled`。

### 4.2 `requests.analysis_skill_snapshots_json`

一次性需求提交时保存用户选择的 skill 快照。

示例：

```json
[
  {
    "skill_id": "uuid",
    "name": "设计维度",
    "instruction_md": "# 设计维度\n分析布局、配色、视觉层级、信息架构、交互细节。",
    "is_official": true
  },
  {
    "skill_id": "uuid",
    "name": "价格策略",
    "instruction_md": "# 价格策略\n分析价格锚点、补贴、满减、限时价、会员价。",
    "is_official": false
  }
]
```

### 4.3 `tasks.analysis_skill_snapshots_json`

管理员审批需求生成任务时，从 `requests.analysis_skill_snapshots_json` 复制到任务。后续该任务下所有新截图分析都使用任务上的快照。

### 4.4 `watch_plans.analysis_skill_snapshots_json`

持续观察计划创建时保存用户选择的 skill 快照。后续该观察计划的每日截图分析使用计划上的快照。

### 4.5 `analysis.custom_analysis_json`

分析结果新增动态 JSONB 字段。

示例：

```json
{
  "results": [
    {
      "skill_id": "uuid",
      "skill_name": "设计维度",
      "analysis": "页面采用高密度信息流布局，顶部利益点突出..."
    },
    {
      "skill_id": "uuid",
      "skill_name": "价格策略",
      "analysis": "截图中强化了限时价和补贴心智..."
    }
  ],
  "errors": []
}
```

兼容规则：

1. 如果结果中存在 `设计维度`，同步写入 `analysis.design_analysis`。
2. 如果结果中存在 `运营维度`，同步写入 `analysis.ops_analysis`。
3. 如果用户未选择设计维度或运营维度，对应旧字段允许为空。
4. 旧数据没有 `custom_analysis_json` 时，前端和导出继续使用旧字段。

---

## 5. 后端 API

### 5.1 用户 skill API

```text
GET    /api/analysis-skills
POST   /api/analysis-skills
PATCH  /api/analysis-skills/{id}
DELETE /api/analysis-skills/{id}
POST   /api/analysis-skills/upload-md
```

权限：

1. 登录用户可读取自己的 active skill 和官方 active skill。
2. 登录用户只能编辑、删除自己创建的非官方 skill。
3. `DELETE` 为软删除。
4. `upload-md` 只接受 `.md` 文本内容，服务端按 Markdown 规则解析后创建 skill。

### 5.2 管理员 skill API

```text
GET    /api/admin/analysis-skills
POST   /api/admin/analysis-skills
PATCH  /api/admin/analysis-skills/{id}
DELETE /api/admin/analysis-skills/{id}
PATCH  /api/admin/analysis-skills/{id}/official
```

权限：

1. 仅 admin 可访问。
2. admin 可查看所有用户 skill 的完整内容。
3. admin 可编辑、禁用、恢复任意 skill。
4. admin 可设置或取消 `is_official`。

### 5.3 请求与观察计划 API 扩展

`POST /api/requests` 增加：

```json
{
  "analysis_skill_ids": ["uuid"]
}
```

`POST /api/admin/watch-plans` 增加同名字段：

```json
{
  "analysis_skill_ids": ["uuid"]
}
```

后端校验：

1. 至少选择 1 个 active skill。
2. 用户只能选择自己的 skill 和官方 skill。
3. 若用户没有选择任何自定义 skill，必须至少选择 `设计维度` 或 `运营维度`。
4. 若选择了至少一个自定义 skill，可以不选择设计维度和运营维度。
5. 保存时把 skill 内容转为快照，不只保存 id。

---

## 6. 前端交互

### 6.1 新增 tab：分析 skill

导航新增 “分析 skill”。

页面内容：

1. `我的 skill` 列表：展示当前用户创建的 skill。
2. `官方 skill` 列表：展示官方 skill。
3. 创建区：支持 Markdown 文本块和 `.md` 上传。
4. 编辑区：名称和 Markdown 指令可编辑。
5. 管理员额外能力：查看所有用户 skill、编辑任意 skill、禁用/恢复、设为官方/取消官方。

保存校验：

1. 名称不能为空。
2. 指令正文不能为空。
3. Markdown 内容长度限制为 20,000 字符以内。
4. 上传文件必须是 `.md`，读取后填入编辑框，用户确认后保存。

Markdown 解析：

1. 第一行一级标题 `# 标题` 作为默认名称。
2. 如果没有一级标题，用户必须手动输入名称。
3. 正文作为 `instruction_md` 保存，不做复杂结构解析。

### 6.2 任务提交页

用户提交一次性需求时增加 “分析 skill” 选择区。

交互规则：

1. 官方 skill 默认选中。
2. 用户自己的 active skill 可勾选。
3. 用户可以取消官方 skill。
4. 最终至少保留 1 个 skill。
5. 如果用户没有自定义 skill，设计维度 / 运营维度至少选择一个。

### 6.3 持续观察计划创建页

新增同样的 skill 选择区。观察计划创建成功后，所选 skill 快照固定到计划上。

### 6.4 管理员审批页

管理员审批时展示用户绑定的 skill 快照摘要：

1. skill 名称。
2. 是否官方。
3. 指令内容摘要。

管理员不在审批页替用户选择或修改 skill。

### 6.5 图片结果展示

如果 `analysis.custom_analysis_json.results` 存在，按结果顺序动态渲染多个分析块。

如果不存在，则回退展示旧字段：

1. 设计分析：`design_analysis`
2. 运营分析：`ops_analysis`

---

## 7. 分析执行流程

### 7.1 Prompt 构造

图片入库后，分析服务从任务或观察计划读取 `analysis_skill_snapshots_json`，构造动态 prompt。

输出格式要求：

```json
{
  "results": [
    {
      "skill_name": "设计维度",
      "analysis": "120-250字分析内容"
    },
    {
      "skill_name": "价格策略",
      "analysis": "120-250字分析内容"
    }
  ]
}
```

Prompt 要求模型：

1. 只输出 JSON。
2. 每个输入 skill 都必须返回一条 result。
3. 不输出 Markdown。
4. 若截图信息不足，也要说明“无法判断”的原因。

### 7.2 解析与状态

解析策略：

1. 优先解析 JSON。
2. 如果缺少某个 skill 的结果，保留其他结果，并在 `errors` 中记录缺失项。
3. 至少一个 skill 成功时，`analysis.status = partial` 或 `success`。
4. 所有 skill 都失败时，`analysis.status = failed`。
5. 所有所选 skill 都有结果时，`analysis.status = success`。

### 7.3 旧字段同步

结果入库时：

1. `设计维度` -> `design_analysis`
2. `运营维度` -> `ops_analysis`
3. 其他维度只进入 `custom_analysis_json`

---

## 8. 搜索、embedding、导出与持续观察兼容

### 8.1 搜索与 embedding

embedding 文本来源调整为：

1. 优先使用 `custom_analysis_json.results[*].analysis` 拼接。
2. 如果没有动态结果，使用旧的 `design_analysis + ops_analysis`。
3. content_type 保留 `combined`。
4. 可继续为设计/运营写入 `design`、`ops` content_type 以兼容现有行为。

文本兜底搜索也要纳入动态结果文本，否则自定义维度结果无法被搜到。

### 8.2 导出

JSON / Excel / ZIP 导出新增动态分析结果字段。

Excel 中 `analysis` sheet 保留旧列，并增加一个 `custom_analysis_json` 或拆成 `skill_name`、`analysis` 的多行结构。MVP 采用多行结构更便于人工阅读。

### 8.3 持续观察日报

日报生成输入新增“今日多维分析”，内容来自所有动态 skill 结果。

兼容策略：

1. 如果存在设计维度结果，继续作为设计摘要输入。
2. 如果存在运营维度结果，继续作为运营摘要输入。
3. 如果不存在设计/运营维度，日报仍可基于所有自定义维度生成综合摘要。

---

## 9. 初始化与默认 skill

数据库初始化时确保存在两个官方 active skill：

1. `设计维度`
2. `运营维度`

如果已存在同名官方 skill，不重复创建。

默认 Markdown：

```md
# 设计维度
从 UI 设计角度分析截图中的布局、配色、视觉层级、信息架构、组件密度、交互提示和可读性。请指出具体画面证据。
```

```md
# 运营维度
从运营策略角度分析截图中的促销机制、文案策略、价格策略、用户引导、转化路径、活动利益点和紧迫感营造。请指出具体画面证据。
```

---

## 10. 测试计划

后端测试：

1. 用户可创建文本 skill。
2. 用户可上传 `.md` 创建 skill。
3. Markdown 一级标题可解析为名称。
4. 普通用户只能编辑自己的 skill。
5. 普通用户可读取官方 skill。
6. 管理员可查看和编辑所有 skill。
7. 管理员可设置和取消官方 skill。
8. 创建请求时至少选择 1 个 skill。
9. 未选择自定义 skill 时，必须选择设计维度或运营维度。
10. 选择自定义 skill 后，可以取消设计维度和运营维度。
11. 请求创建时保存 skill 快照。
12. 修改原 skill 不影响已创建请求和任务快照。
13. 图片分析按任务快照输出多个维度。
14. 设计维度和运营维度同步旧字段。
15. 自定义维度进入 embedding combined 文本。
16. 文本搜索能命中自定义维度结果。
17. 导出包含动态分析结果。

前端验证：

1. “分析 skill” tab 可访问。
2. 用户可用文本创建 skill。
3. 用户可上传 `.md` 并保存 skill。
4. 官方 skill 默认选中。
5. 任务提交页至少选择 1 个 skill。
6. 持续观察计划创建页至少选择 1 个 skill。
7. 管理员可查看全部 skill 详情并设为官方。
8. 图片卡片和详情页可动态展示多个维度。

---

## 11. 风险与约束

1. 动态 JSON 解析必须容错，不能因为模型少返回一个维度就丢掉其他维度。
2. skill 内容会直接进入 prompt，需要限制长度，避免 token 爆炸。
3. 历史数据和新数据会长期共存，前端和导出必须有回退逻辑。
4. 任务快照是分析口径追溯的关键，不能只保存 skill id。
5. 管理员能看到所有 skill 内容，页面上要避免误导用户认为 skill 是私密内容。

---

## 12. 验收标准

1. 用户可以在“分析 skill”页面创建和上传 Markdown skill。
2. 管理员可以管理全部 skill，并设置官方 skill。
3. 用户提交任务和创建持续观察计划时，可以选择分析 skill。
4. 系统按任务或观察计划的 skill 快照执行后续截图分析。
5. 用户选择几个 skill，分析结果就返回几个维度。
6. 设计维度和运营维度继续兼容旧字段。
7. 自定义维度结果可展示、可搜索、可导出。
8. 已有历史截图不被迁移或自动重跑。
