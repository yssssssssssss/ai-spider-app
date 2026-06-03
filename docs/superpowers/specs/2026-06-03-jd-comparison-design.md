# 对比JD逐张AB分析 - 设计文档

**项目**: ai-taobao-app 竞品截图分析能力升级  
**日期**: 2026-06-03  
**范围**: 首页「竞品搜集」一次性任务  
**状态**: 已确认设计，待实现计划

---

## 1. 背景

现有系统支持用户提交竞品搜集需求，审批后生成任务，自动操作移动端 App 截图，并对每张截图执行单图分析。分析维度已经升级为 analysis skill，任务会保存 skill 快照，后续截图按快照输出动态分析结果。

新需求是在「竞品搜集」中增加一个功能按钮「对比JD」。用户开启后，系统需要在京东上执行等价操作，并在结果页中按逐张 AB 对照模式展示原竞品 App 与京东的差异。

逐张对比的关键风险是图片配对。如果按截图顺序配对，容易把无关页面硬凑在一起；如果要求页面类型精确分类，模型判断又会过于脆弱。本设计采用「对照组 + 对照槽位 + 配对分析」方案：先把用户本次任务拆成少量可编辑的对照槽位，再按槽位匹配 A 侧 App 和京东截图。只有两侧都可靠命中同一槽位时，才生成 AB 对比分析。

---

## 2. 已确认需求

1. 「对比JD」只作用于首页「竞品搜集」一次性任务，不扩展到「持续观察」。
2. 用户填写的目标 App 是 A 侧竞品 App。
3. 如果用户填写多个 A 侧 App，例如「淘宝、拼多多」，系统生成多组对照。
4. 京东任务只执行一次，并复用于多个 A 侧对照组。
5. 逐张对比采用「对照槽位」配对，不按截图顺序硬配。
6. 对照槽位由系统自动拆解，用户提交前可以编辑确认。
7. JD 等价执行指令由系统自动改写，用户提交前可以编辑确认。
8. 只有已配对图片才生成 AB 对比分析。
9. 缺失对照和未匹配截图只展示单图分析，不做 AB 对比。
10. AB 对比分析沿用用户选择的 analysis skill，并把每个 skill 改成 AB 对照口径。
11. 第一版 AB 结果只在任务结果页展示，不进入图片检索和导出。

---

## 3. 目标与非目标

### 3.1 目标

1. 在「竞品搜集」提交表单中增加「对比JD」开关。
2. 智能拆解时生成可编辑的 A 侧 App、对照槽位和 JD 等价执行指令。
3. 审批后生成多个 A 侧任务和一个复用的京东任务。
4. 用独立数据模型表达对照组、A 侧 App、对照槽位、图片槽位命中和逐张 AB 分析。
5. 截图完成单图分析后，自动进行槽位匹配和必要的 AB 分析。
6. 任务结果页展示每组 A App vs 京东的逐槽位结果。

### 3.2 非目标

1. 不支持持续观察的 JD 对照。
2. 不把 AB 对照结果纳入图片检索。
3. 不扩展 JSON、Excel、ZIP 导出。
4. 不做逐槽位手动重新配对。
5. 不做 AB 分析重试按钮。
6. 不自动替换同槽位已锁定图片。
7. 不允许管理员审批时修改槽位和 JD 指令。
8. 不迁移历史任务，不重跑历史截图。

---

## 4. 核心概念

### 4.1 对照组

`comparison_groups` 表示一次用户提交开启「对比JD」后产生的对照能力。一个 request 最多对应一个对照组。对照组拥有一个京东任务，并管理多个 A 侧 App。

### 4.2 A 侧 App

`comparison_group_apps` 表示一个 A 侧 App 与京东的对照关系。例如用户输入「淘宝、拼多多」，则产生两行：

1. 淘宝 vs 京东
2. 拼多多 vs 京东

京东任务只在 `comparison_groups.jd_task_id` 中保存一次，并被所有 A 侧 App 复用。

### 4.3 对照槽位

`comparison_slots` 是本次任务需要逐张对比的目标画面，不是通用页面分类。槽位由系统自动拆解，用户提交前可编辑。

示例：

| slot_key | name | description |
| --- | --- | --- |
| promo_landing | 会场首屏 | 进入目标活动会场后看到的首屏画面，重点观察利益点和入口布局 |
| product_detail | 商品详情首屏 | 从活动或搜索结果进入一个目标商品详情页后的首屏画面 |

槽位用于有限匹配：只判断某张截图是否命中本次任务的这些目标画面。

### 4.4 槽位命中

`comparison_slot_matches` 表示某张截图被判断命中某个槽位。只有高置信命中才参与 AB 配对。

### 4.5 AB 配对分析

`comparison_pair_analyses` 表示一组 A 图片和 JD 图片在同一槽位下的逐张对比分析。它不是单图分析，不能复用现有 `analysis` 表。

---

## 5. 数据模型

### 5.1 `comparison_groups`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 对照组 ID |
| `request_id` | UUID, FK requests.id | 来源 request |
| `baseline_app` | TEXT, NOT NULL | 固定保存为 `京东` |
| `jd_task_id` | UUID, FK tasks.id, nullable | 复用的京东任务 |
| `jd_instruction` | TEXT, NOT NULL | 用户确认后的京东等价执行指令 |
| `status` | TEXT, NOT NULL | `pending`、`running`、`ready`、`partial`、`completed`、`failed` |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |

建议索引：

1. `ix_comparison_groups_request_id`
2. `ix_comparison_groups_jd_task_id`
3. `ix_comparison_groups_status`

### 5.2 `comparison_group_apps`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | A 侧对照关系 ID |
| `comparison_group_id` | UUID, FK comparison_groups.id | 所属对照组 |
| `app_name` | TEXT, NOT NULL | A 侧 App 名称 |
| `task_id` | UUID, FK tasks.id, nullable | A 侧任务 |
| `status` | TEXT, NOT NULL | `pending`、`running`、`partial`、`completed`、`failed` |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |

约束：

1. 同一 `comparison_group_id` 下 `app_name` 唯一。
2. 同一 `comparison_group_id` 下 `task_id` 唯一，允许初始为空。

### 5.3 `comparison_slots`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 槽位 ID |
| `comparison_group_id` | UUID, FK comparison_groups.id | 所属对照组 |
| `slot_key` | TEXT, NOT NULL | 稳定短 key |
| `name` | TEXT, NOT NULL | 展示名称 |
| `description` | TEXT, NOT NULL | 槽位判断说明 |
| `required` | BOOLEAN, NOT NULL | 是否必需 |
| `sort_order` | INTEGER, NOT NULL | 展示顺序 |
| `created_at` | DATETIME | 创建时间 |

约束：

1. 同一 `comparison_group_id` 下 `slot_key` 唯一。
2. 每个对照组允许 1 到 5 个槽位。

### 5.4 `comparison_slot_matches`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 槽位命中 ID |
| `comparison_group_id` | UUID, FK comparison_groups.id | 所属对照组 |
| `slot_id` | UUID, FK comparison_slots.id, nullable | 命中的槽位，高置信或低置信时存在 |
| `app_name` | TEXT, NOT NULL | 截图所属 App |
| `task_id` | UUID, FK tasks.id | 截图所属任务 |
| `image_id` | UUID, FK images.id | 截图 |
| `confidence` | FLOAT, NOT NULL | VLM 置信度，范围 0 到 1 |
| `status` | TEXT, NOT NULL | `matched`、`low_confidence`、`unmatched` |
| `reason` | TEXT | 判断理由 |
| `created_at` | DATETIME | 创建时间 |

约束：

1. `image_id` 唯一，避免同一张图被重复记录。
2. 高置信 `matched` 时，同一 `comparison_group_id + slot_id + app_name` 第一张锁定，不自动替换。

### 5.5 `comparison_pair_analyses`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | AB 分析 ID |
| `comparison_group_app_id` | UUID, FK comparison_group_apps.id | A 侧 App 对照关系 |
| `slot_id` | UUID, FK comparison_slots.id | 对照槽位 |
| `a_image_id` | UUID, FK images.id | A 侧截图 |
| `jd_image_id` | UUID, FK images.id | JD 截图 |
| `custom_analysis_json` | JSONB | 沿用 dynamic skill 的结果结构 |
| `status` | TEXT, NOT NULL | `pending`、`success`、`partial`、`failed` |
| `error` | TEXT | 失败原因 |
| `analyzed_at` | DATETIME | 分析完成时间 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |

约束：

1. `comparison_group_app_id + slot_id` 唯一。
2. 只有 A 和 JD 两侧都有高置信槽位命中时才创建。

结果结构：

```json
{
  "results": [
    {
      "skill_id": "...",
      "skill_name": "设计维度",
      "analysis": "从设计维度对比 A 侧截图和京东截图的差异、共同点与可借鉴点。"
    }
  ],
  "errors": []
}
```

---

## 6. API 设计

### 6.1 智能拆解

扩展现有接口：

```text
POST /api/requests/interpret
```

入参保持现有结构：

```json
{
  "natural_language": "打开淘宝和拼多多，进入百亿补贴会场，分别截图首屏和商品详情页"
}
```

返回新增可选字段：

```json
{
  "target_app": "淘宝、拼多多",
  "target_scenario": "百亿补贴会场",
  "keywords": ["百亿补贴"],
  "description": "打开淘宝和拼多多，进入百亿补贴会场，分别截图首屏和商品详情页",
  "a_apps": ["淘宝", "拼多多"],
  "comparison_slots": [
    {
      "slot_key": "promo_landing",
      "name": "会场首屏",
      "description": "进入目标活动会场后看到的首屏画面",
      "required": true
    },
    {
      "slot_key": "product_detail",
      "name": "商品详情首屏",
      "description": "从活动会场进入一个目标商品详情页后的首屏画面",
      "required": true
    }
  ],
  "jd_instruction": "打开京东App，进入等价的百亿补贴或大促活动会场，分别截图会场首屏和商品详情页，并截图保存到本地"
}
```

兼容规则：

1. 旧前端可忽略新增字段。
2. 生成失败时仍返回旧字段，前端可让用户手动补充对照配置。
3. `a_apps` 不包含 `京东`。
4. `comparison_slots` 最多 5 个。

### 6.2 创建 request

扩展现有接口：

```text
POST /api/requests
```

新增字段：

```json
{
  "compare_jd_enabled": true,
  "comparison": {
    "a_apps": ["淘宝", "拼多多"],
    "jd_instruction": "打开京东App，进入等价的百亿补贴或大促活动会场，分别截图会场首屏和商品详情页，并截图保存到本地",
    "slots": [
      {
        "slot_key": "promo_landing",
        "name": "会场首屏",
        "description": "进入目标活动会场后看到的首屏画面",
        "required": true
      }
    ]
  }
}
```

后端校验：

1. `compare_jd_enabled=false` 时忽略 `comparison`。
2. `compare_jd_enabled=true` 时，`comparison` 必填。
3. `a_apps` 至少 1 个，去重后不得包含 `京东`。
4. `jd_instruction` 必填，长度限制 20 到 2000 字符。
5. `slots` 必须有 1 到 5 个。
6. 每个 slot 必须有 `name` 和 `description`。
7. `slot_key` 缺失时后端按名称生成稳定 key。
8. analysis skill 选择沿用现有规则，至少保留一个 skill。

保存策略：

1. `requests` 表新增 `compare_jd_enabled` 和 `comparison_config_json`。
2. request 创建时只保存用户确认后的配置，不立即创建对照组。
3. 对照组、任务、槽位在审批通过后创建。

### 6.3 对照结果查询

新增接口：

```text
GET /api/comparison-groups/by-task/{task_id}
```

用途：任务结果页根据当前 task 查询其所属 JD 对照结果。

返回结构：

```json
{
  "group_id": "...",
  "request_id": "...",
  "baseline_app": "京东",
  "jd_task_id": "...",
  "status": "partial",
  "apps": [
    {
      "id": "...",
      "app_name": "淘宝",
      "task_id": "...",
      "status": "partial",
      "slots": [
        {
          "slot_id": "...",
          "slot_key": "promo_landing",
          "name": "会场首屏",
          "description": "进入目标活动会场后看到的首屏画面",
          "status": "paired",
          "a_match": {
            "image": {},
            "analysis": {},
            "confidence": 0.91,
            "reason": "截图已到达活动会场首屏"
          },
          "jd_match": {
            "image": {},
            "analysis": {},
            "confidence": 0.88,
            "reason": "截图已到达京东等价活动首屏"
          },
          "pair_analysis": {
            "status": "success",
            "custom_analysis_json": {}
          }
        }
      ],
      "unmatched": [
        {
          "image": {},
          "analysis": {},
          "confidence": 0.2,
          "reason": "未命中任何对照槽位"
        }
      ]
    }
  ]
}
```

槽位状态：

1. `paired`: A 和 JD 都有高置信命中。
2. `missing_jd`: A 有高置信命中，JD 没有。
3. `missing_a`: JD 有高置信命中，A 没有。
4. `unmatched`: 无可展示的高置信命中。
5. `analysis_failed`: A 和 JD 已配对，但 AB 分析失败。

---

## 7. 审批与任务生成流程

普通 request 审批保持现有流程。

开启「对比JD」的 request 审批流程：

1. 更新 request 状态为 `approved`。
2. 读取 `comparison_config_json`。
3. 创建 `comparison_group`，保存 `request_id`、`baseline_app=京东`、`jd_instruction`。
4. 创建 `comparison_slots`。
5. 为每个 A 侧 App 创建任务：
   - `target_app = app_name`
   - `target_scenario = request.target_scenario`
   - `analysis_skill_snapshots_json = request.analysis_skill_snapshots_json`
   - `generated_instruction` 由 `plan_task` 针对该 A App 生成
6. 创建一个 JD 任务：
   - `target_app = 京东`
   - `target_scenario = request.target_scenario`
   - `analysis_skill_snapshots_json = request.analysis_skill_snapshots_json`
   - `generated_instruction = jd_instruction`
7. 更新 `comparison_group.jd_task_id`。
8. 创建 `comparison_group_apps`，关联每个 A App 与其任务。
9. 启动所有任务。

执行顺序建议：

1. 京东任务和 A 侧任务可以并行启动。
2. 如果设备资源有限，沿用现有任务队列和 worker 能力调度。
3. 对照组状态由关联任务和分析结果计算，不依赖手动推进。

---

## 8. 分析执行流程

### 8.1 单图分析

截图入库后继续执行现有流程：

1. 近似重复检测。
2. 目标页判断。
3. 按任务 skill 快照执行单图分析。
4. 写入 `analysis` 表。
5. 写入 embedding。

这一步不改变现有数据语义。

### 8.2 槽位匹配

单图分析成功或部分成功后，如果图片所属 task 在某个 `comparison_group` 中，则触发槽位匹配。

VLM 输入：

1. 当前图片。
2. 对照组 slots。
3. 当前 App 名。
4. request 的目标场景、关键词和描述。

输出 JSON：

```json
{
  "slot_key": "promo_landing",
  "confidence": 0.91,
  "reason": "截图已进入目标活动会场首屏"
}
```

匹配规则：

1. `confidence >= 0.75`: `matched`
2. `0.45 <= confidence < 0.75`: `low_confidence`
3. `< 0.45` 或无合适槽位: `unmatched`

同一 App 同一槽位锁定规则：

1. 如果已有高置信 `matched`，后续图片不替换。
2. 后续图片可以记录为低置信或未匹配，但不触发 AB。
3. 第一版不做自动重算，避免结果反复变化。

### 8.3 AB 对比分析

新增高置信命中后，检查是否可生成 AB 对比：

1. 找到同一 `comparison_group_app`。
2. 找到同一 `slot` 的 A 侧高置信图片。
3. 找到同一 `slot` 的 JD 高置信图片。
4. 确认两张图片的单图 `analysis.status` 为 `success` 或 `partial`。
5. 确认没有已存在的 `comparison_pair_analyses`。
6. 创建 AB 分析记录并调用 VLM。

AB prompt 使用用户选择的 analysis skill 快照，但要求模型输出 AB 对照口径：

```text
你是一名电商竞品AB对照分析器。
请对 A 侧截图和京东截图在同一对照槽位下进行逐张对比。
必须按输入 analysis skill 分别输出结果。
不要评价不在图片中出现的内容。
如果某个维度无法判断，说明无法判断的原因。
```

输出 JSON：

```json
{
  "results": [
    {
      "skill_name": "设计维度",
      "analysis": "A侧与京东在视觉层级、入口表达和信息密度上的差异..."
    }
  ]
}
```

解析规则复用 `normalize_dynamic_analysis_result` 的思想：

1. skill 名称必须与输入一致。
2. 缺失某个 skill 结果时，其他 skill 仍保存。
3. 全部 skill 成功为 `success`。
4. 部分成功为 `partial`。
5. 全部失败为 `failed`。

---

## 9. 前端设计

### 9.1 竞品搜集表单

在 `RequestForm` 中新增「对比JD」开关。

交互：

1. 用户输入自然语言需求。
2. 点击「智能拆解」。
3. 展示原有结构化字段。
4. 如果开启「对比JD」，展示对照配置区：
   - A 侧 App 列表，可编辑。
   - JD 等价执行指令，可编辑。
   - 对照槽位列表，可增删改。
5. 槽位数量限制 1 到 5 个。
6. 提交时带上 `compare_jd_enabled` 和 `comparison`。

表单校验：

1. 开启对比时 A 侧 App 不得为空。
2. 开启对比时 A 侧 App 不得包含 `京东`。
3. 开启对比时 JD 指令不得为空。
4. 开启对比时至少一个槽位。
5. 每个槽位必须有名称和描述。

### 9.2 审批页

审批页只展示，不编辑：

1. 是否开启「对比JD」。
2. A 侧 App。
3. JD 指令摘要。
4. 对照槽位列表。
5. analysis skill 摘要。

### 9.3 任务结果页

`AdminTaskResults` 保留现有截图网格，并在上方增加 JD 对照区域。

展示结构：

1. 对照组状态摘要。
2. 每个 A 侧 App 一个分区，例如「淘宝 vs 京东」。
3. 每个分区内按 slot 顺序展示：
   - 槽位名称和状态。
   - A 图片和 JD 图片。
   - 两侧单图分析。
   - 已配对时展示 AB 对照分析。
   - 缺失时只展示存在侧单图分析。
4. 未匹配截图单独折叠展示，只显示单图分析和未匹配原因。

第一版不做：

1. 手动重配。
2. 重试 AB 分析。
3. 导出按钮扩展。

---

## 10. 权限与数据范围

1. 普通用户只能看到自己 request 和 task 对应的对照组。
2. operator 和 admin 沿用现有数据范围规则。
3. `GET /api/comparison-groups/by-task/{task_id}` 必须先校验当前用户是否可见该 task。
4. 返回结果中只包含用户可见任务的图片和分析。
5. 创建和审批对照组沿用 request 审批权限。

---

## 11. 失败处理

| 场景 | 处理 |
| --- | --- |
| A 或 JD 任务失败 | 已采集截图继续参与槽位匹配；缺失侧显示缺失，不生成 AB |
| 单图分析失败 | 不触发槽位匹配和 AB，结果页显示单图分析失败 |
| 槽位匹配失败 | 记录 `unmatched`，只显示单图分析 |
| 低置信命中 | 记录 `low_confidence`，不参与 AB |
| A 有图 JD 无图 | 显示 `missing_jd`，不生成 AB |
| JD 有图 A 无图 | 显示 `missing_a`，不生成 AB |
| AB 分析失败 | 显示两侧单图分析和失败原因 |
| 已有 AB 分析 | 不重复触发 |

---

## 12. 测试计划

### 12.1 后端测试

1. `interpret_request`
   - 多 App 输入能拆出 `a_apps`。
   - 能生成 1 到 5 个 slots。
   - 能生成 JD instruction。
   - 普通不对比场景兼容旧返回。

2. `create_request`
   - `compare_jd_enabled=false` 时走旧逻辑。
   - 开启对比时校验 A App、slots、JD 指令。
   - A 侧包含 `京东` 时拒绝。
   - 槽位超过 5 个时拒绝。

3. 审批生成任务
   - 单 A App 生成 A 任务、JD 任务、group、slots。
   - 多 A App 生成多个 A 任务和一个 JD 任务。
   - JD task 被多个 `comparison_group_apps` 复用。
   - 旧普通 request 审批不受影响。

4. 槽位匹配
   - 高置信记录 `matched`。
   - 低置信记录 `low_confidence`，不进入 AB。
   - 未匹配记录 `unmatched`。
   - 同 App 同 slot 已有高置信时不替换。

5. AB 分析触发
   - A 和 JD 都存在才触发。
   - 缺失一侧不触发。
   - 单图分析失败不触发。
   - 已有 pair analysis 不重复触发。

### 12.2 前端测试

1. 「对比JD」开关显示和隐藏对照配置。
2. 智能拆解后可编辑 A App、slots、JD 指令。
3. 提交 payload 正确。
4. 任务结果页展示：
   - `paired`
   - `missing_jd`
   - `missing_a`
   - `unmatched`
   - `analysis_failed`

---

## 13. 实现顺序建议

1. 后端 schema、model、migration 兼容列。
2. request interpret 和 create_request 扩展。
3. 审批生成对照组和多任务。
4. 槽位匹配服务。
5. AB 对比分析服务。
6. 对照结果查询 API。
7. 提交页「对比JD」配置 UI。
8. 审批页摘要展示。
9. 任务结果页对照展示。
10. 回归测试。

---

## 14. 风险与缓解

1. **JD 等价路径不稳定**  
   缓解：JD 指令允许用户提交前编辑，不强行只替换 App 名。

2. **槽位匹配不可靠**  
   缓解：使用置信度阈值，低置信不参与 AB。

3. **截图数量不一致**  
   缓解：按槽位配对，缺失侧只展示单图分析。

4. **分析结果重复生成**  
   缓解：`comparison_group_app_id + slot_id` 唯一，已有 AB 分析不重复触发。

5. **数据关系膨胀**  
   缓解：只新增表达真实关系的表，不把结果塞进万能 JSON。

6. **现有普通任务被影响**  
   缓解：`compare_jd_enabled=false` 时走旧流程；所有新逻辑都以对照组存在为前置条件。

---

## 15. 验收标准

1. 用户可以在「竞品搜集」开启「对比JD」。
2. 智能拆解后能看到并编辑 A 侧 App、JD 指令和对照槽位。
3. 单 A App 提交后，审批生成 A 任务和一个 JD 任务。
4. 多 A App 提交后，审批生成多个 A 任务和一个复用 JD 任务。
5. 截图先保留现有单图分析。
6. 同槽位 A 和 JD 都命中时生成 AB 对比分析。
7. 缺失对照和未匹配截图不生成 AB，只显示单图分析。
8. 任务结果页能按 A App vs 京东展示逐槽位结果。
9. 普通不启用「对比JD」的 request、task、analysis 流程保持原行为。
10. 后端回归测试覆盖对照 request、审批、多任务、槽位匹配和 AB 分析触发。
