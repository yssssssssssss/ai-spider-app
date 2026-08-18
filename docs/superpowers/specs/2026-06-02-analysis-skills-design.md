# 分析 Skill - 设计文档 v2

**日期**: 2026-06-11
**项目**: ai-spider-app 竞品截图分析能力升级
**方案**: B — 扩展 Analysis 表 + 新建 AnalysisSkill 表

---

## 1. 背景与目标

当前竞品截图分析固定输出两个字段：`design_analysis` 和 `ops_analysis`。目标是将分析维度升级为可由用户自定义的"分析 skill"，用户可以通过文本输入或上传 Markdown 文件创建自己的分析维度，在提交任务或创建持续观察计划时选择要应用的 skill。

方案 B 的核心思路：新建 `AnalysisSkill` 表管理 skill 定义，扩展 `Analysis` 表增加 `skill_id` + `result_json` 字段，使所有分析结果（内置 + 自定义）统一存储在一张表中，按 `skill_id` 区分，向后兼容已有数据。

---

## 2. 已确认产品决策

| 决策项 | 方案 |
| --- | --- |
| 维度选择粒度 | 按任务 / 持续观察计划选择 |
| skill 创建方式 | 文本输入 Markdown，或上传 `.md` / `.txt` 文件 |
| Markdown 规则 | 一级标题作为名称，正文作为 prompt |
| 上传格式 | 仅支持 Markdown/纯文本（与对比 skill 一致），不支持 JSON 配置 |
| 默认维度 | 系统内置官方 skill：设计维度、运营维度 |
| 管理员权限 | 查看全部 skill 内容，对全部 skill 增删改查 |
| 历史数据 | 不迁移、不自动重跑；新能力只影响后续新分析 |
| Skill 分类 | profile 字段区分普通截图(default) / 持续观察(watch) |

---

## 3. 数据模型

### 3.1 `analysis_skills`（新建）

与 `ComparisonSkill` 对齐的独立表：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID, PK | 主键 |
| `name` | Text, NOT NULL | skill 名称 |
| `description` | Text | 描述 |
| `prompt` | Text, NOT NULL | 分析指令（Markdown 正文） |
| `output_schema_json` | JSONB, 默认 `{}` | 输出 JSON schema 定义 |
| `scenario_tags_json` | JSONB, 默认 `[]` | 场景标签 |
| `profile` | String, 默认 `"default"` | 区分普通截图 / 持续观察 |
| `skill_type` | String, 默认 `"analysis"` | 区分 analysis / target |
| `status` | String, 默认 `"active"` | active / disabled / deleted |
| `version` | Integer, 默认 1 | prompt 变更时自增 |
| `is_system` | Boolean, 默认 false | 标记内置 skill |
| `created_by` | UUID, nullable | 创建用户 |
| `updated_by` | UUID, nullable | 更新用户 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

约束与索引：

1. `status` 默认 `active`。
2. `is_system` 默认 `false`。
3. 内置 skill（`is_system=True`）不可删除，只能编辑 prompt。
4. 删除采用软删除：`status = deleted`。
5. 索引：`(status)`, `(profile, status)`。

### 3.2 `analysis`（扩展）

在现有字段基础上新增 3 个字段：

| 新增字段 | 类型 | 说明 |
| --- | --- | --- |
| `skill_id` | UUID, FK → analysis_skills, nullable | 关联 skill；内置分析为 null |
| `skill_key` | String, nullable | skill 标识；旧数据为 null |
| `result_json` | JSONB, nullable | 完整分析结果 JSON |

兼容规则：

1. **内置 skill 分析**：同时写入 `design_analysis` + `ops_analysis` + `result_json`（向后兼容）。
2. **自定义 skill 分析**：只写入 `result_json`。
3. **旧数据**（无 skill_id、无 result_json）：前端和导出继续使用旧字段，不做任何改动。

唯一约束：

```
UniqueConstraint("image_id", "skill_id", name="uq_analysis_image_skill")
```

同一图片 + 同一 skill 只有一条分析结果。`skill_id=null` 的内置分析也保持唯一（原有逻辑不变）。

**注意**：由于同一图片现在可能有多条 Analysis 记录（每个 skill 一条），需要将 `image_id` 的 `unique=True` 约束移除，改为上述复合唯一约束。

### 3.3 `tasks`（扩展）

| 新增字段 | 类型 | 说明 |
| --- | --- | --- |
| `analysis_skill_ids` | ARRAY(UUID), 默认 `[]` | 用户选择的 skill 列表 |

空数组 = 使用系统默认内置 skill。

### 3.4 `watch_plans`（扩展）

同 tasks，增加 `analysis_skill_ids` ARRAY(UUID) 字段。

### 3.5 `requests`（扩展）

同 tasks，增加 `analysis_skill_ids` ARRAY(UUID) 字段。审批生成 task 时从 request 复制。

---

## 4. 后端 API

### 4.1 管理 skill API

```text
POST   /api/admin/analysis-skills          创建 skill
GET    /api/admin/analysis-skills          列表（支持 profile 过滤）
GET    /api/admin/analysis-skills/{id}     详情
PATCH  /api/admin/analysis-skills/{id}     更新
DELETE /api/admin/analysis-skills/{id}     软删除（status=deleted）
POST   /api/admin/analysis-skills/upload   上传 Markdown
POST   /api/admin/analysis-skills/{id}/toggle  启停切换
```

权限：仅 admin 可访问。

### 4.2 任务相关 API 扩展

```text
PATCH  /api/admin/tasks/{id}   支持更新 analysis_skill_ids
POST   /api/requests           增加 analysis_skill_ids 字段
POST   /api/admin/watch-plans  增加 analysis_skill_ids 字段
```

### 4.3 Markdown 上传

`POST /api/admin/analysis-skills/upload`

- 接受 `.md` / `.txt` 文件
- 解析规则：一级标题 `# 标题` 作为 name，正文作为 prompt
- 如果没有一级标题，用户必须手动输入名称
- 内容长度限制 20,000 字符

---

## 5. 分析执行流程

### 5.1 流程改造

当前流程：`_analyze_and_embed()` → `analyzer.analyze()` → 固定写入 `design_analysis` + `ops_analysis`

改造后流程：

```
_analyze_and_embed(image):
  1. 获取 task.analysis_skill_ids
  2. 如果为空 → 使用系统默认内置 skill（保持现有行为）
  3. 如果非空 → 遍历每个 skill_id，对每个 skill 执行分析：
     a. 加载 AnalysisSkill 记录，校验 status=active
     b. 构建 prompt：skill.prompt + 上下文信息（target_app, keywords 等）
     c. 调用 LLM，解析 JSON 结果
     d. 写入 Analysis 记录：
        - 内置 skill: design_analysis + ops_analysis + result_json
        - 自定义 skill: result_json = LLM 返回的完整 JSON
        - skill_id / skill_key 关联到具体 skill
  4. 并行执行多个 skill 的分析（asyncio.gather）
```

### 5.2 LLMAnalyzer 改造

```
新增方法:
  analyze_with_skill(image_path, skill, context) → dict
    — 使用 skill.prompt 作为分析指令
    — 解析 LLM 返回的 JSON（不强制 design/ops 两字段）
    — 返回完整 parsed JSON

保留方法:
  analyze(image_path, context) — 内置 skill 仍走此路径
```

### 5.3 Prompt 构造

图片入库后，分析服务从任务或观察计划读取 `analysis_skill_ids`，加载对应 skill 的 prompt，构造分析指令。

输出格式要求（自定义 skill）：

```json
{
  "skill_name": "价格策略",
  "analysis": "120-250字分析内容"
}
```

内置 skill 仍输出 `design_analysis` + `ops_analysis` 双字段格式，同时存入 `result_json`。

### 5.4 解析与状态

1. 优先解析 JSON。
2. 解析失败时记录错误，不影响其他 skill 的分析。
3. 每个 skill 独立记录 Analysis，独立标记 status。

---

## 6. 内置 Skill 种子数据

启动时自动注入两个系统内置 skill（`is_system=True`）：

| name | profile | prompt | 说明 |
|------|---------|--------|------|
| 普通截图设计/策略分析 | default | 现有 ANALYSIS_PROMPT | 替代现有 DEFAULT_ANALYSIS_SKILLS |
| 持续观察截图分析 | watch | 现有 WATCH_ANALYSIS_PROMPT | 持续观察场景专用 |

系统内置 skill 不可删除，只能编辑 prompt。`app_settings` 中的 `analysis_skill_prompts` 配置迁移到新表后废弃。

---

## 7. 前端交互

### 7.1 Skill 编辑页（AnalysisSkills.tsx）

对齐 CompareSkills 的布局：左侧编辑面板 + 右侧 skill 列表。

```
┌─────────────────────────────────────────────────────┐
│  Skill 编辑 > 截图分析 Skill                          │
│─────────────────────────────────────────────────────│
│  ┌──────────────┐  ┌─────────────────────────────┐  │
│  │ 新建 Skill    │  │ 内置: 普通截图设计/策略分析   │  │
│  │              │  │ default · v3 · 启用中         │  │
│  │ 名称 [     ] │  │ 系统 Skill · 不可删除         │  │
│  │ 描述 [     ] │  │                    [编辑]     │  │
│  │ 场景 [     ] │  ├─────────────────────────────┤  │
│  │ Prompt       │  │ 内置: 持续观察截图分析        │  │
│  │ [textarea  ] │  │ watch · v1 · 启用中          │  │
│  │              │  │ 系统 Skill · 不可删除         │  │
│  │ 输出Schema   │  │                    [编辑]     │  │
│  │ [textarea  ] │  ├─────────────────────────────┤  │
│  │ 适用场景      │  │ 用户自建: 京东价格分析        │  │
│  │ ○ 默认       │  │ default · v2 · 启用中        │  │
│  │ ○ 持续观察    │  │ [编辑] [停用] [删除]          │  │
│  │              │  ├─────────────────────────────┤  │
│  │ 状态          │  │ 用户自建: 淘宝活动分析        │  │
│  │ ○ 启用 ○ 停用 │  │ default · v1 · 已停用        │  │
│  │              │  │ [编辑] [启用] [删除]          │  │
│  │ [上传MD] [保存]│  └─────────────────────────────┘  │
│  └──────────────┘                                    │
└─────────────────────────────────────────────────────┘
```

关键交互：

- 内置 skill：只显示编辑按钮，无删除/停用
- 自建 skill：编辑、启停切换、删除
- 上传 Markdown 按钮（与 CompareSkills 一致）
- Prompt 编辑区折叠展示摘要 + 展开编辑

### 7.2 任务创建/编辑 — Skill 选择

在任务表单中增加 skill 多选区域：

```
┌─────────────────────────────────────┐
│ 采集设置                             │
│ ┌─────────────────────────────────┐ │
│ │ 分析 Skill          [选择Skill] │ │
│ │ ☑ 普通截图设计/策略分析 (内置)   │ │
│ │ ☐ 持续观察截图分析 (内置)        │ │
│ │ ☑ 京东价格分析 (自建)            │ │
│ │ ☐ 淘宝活动分析 (已停用,不可选)   │ │
│ └─────────────────────────────────┘ │
│ 未选择时使用系统默认内置 Skill        │
└─────────────────────────────────────┘
```

关键交互：

- 多选 checkbox，已停用的 skill 灰显不可选
- 默认不选 = 使用系统内置 skill（保持向后兼容）
- 普通任务只显示 `profile=default` 的 skill，持续观察只显示 `profile=watch`

### 7.3 图片分析结果展示

按 skill 分组展示：

```
┌─────────────────────────────────────┐
│ 分析结果                             │
│                                     │
│ ▸ 普通截图设计/策略分析 (内置)        │
│   设计分析: ...                      │
│   运营分析: ...                      │
│                                     │
│ ▸ 京东价格分析                       │
│   price_analysis: ...               │
│   promotion_analysis: ...           │
└─────────────────────────────────────┘
```

关键逻辑：

- 旧数据（无 skill_id）：显示在"内置分析"分组下，保持现有展示
- 新数据（有 skill_id）：按 skill name 分组，result_json 的 key 动态渲染
- 无 skill_id + 无 result_json 的旧记录不做任何改动

---

## 8. 搜索、embedding、导出与持续观察兼容

### 8.1 搜索与 embedding

embedding 文本来源调整为：

1. 优先使用 `result_json` 中的分析文本拼接。
2. 如果没有 `result_json`，使用旧的 `design_analysis + ops_analysis`。
3. content_type 保留 `combined`。
4. 可继续为设计/运营写入 `design`、`ops` content_type 以兼容现有行为。

文本兜底搜索也要纳入 `result_json` 文本，否则自定义 skill 结果无法被搜到。

### 8.2 导出

JSON / Excel / ZIP 导出新增动态分析结果字段。

Excel 中 `analysis` sheet 保留旧列，并增加 `skill_name`、`result_json` 的多行结构。

### 8.3 持续观察日报

日报生成输入新增"多维分析"，内容来自所有 skill 的 result_json。

兼容策略：

1. 如果存在设计维度结果，继续作为设计摘要输入。
2. 如果存在运营维度结果，继续作为运营摘要输入。
3. 如果不存在设计/运营维度，日报可基于所有自定义维度生成综合摘要。

---

## 9. 迁移策略

### 9.1 数据库迁移

```sql
-- 1. 新建 analysis_skills 表
CREATE TABLE analysis_skills (...);

-- 2. 扩展 analysis 表
ALTER TABLE analysis ADD COLUMN skill_id UUID REFERENCES analysis_skills(id);
ALTER TABLE analysis ADD COLUMN skill_key VARCHAR;
ALTER TABLE analysis ADD COLUMN result_json JSONB;

-- 3. 移除 image_id 的 unique 约束（同一图片可有多个 skill 的分析）
ALTER TABLE analysis DROP CONSTRAINT IF EXISTS analysis_image_id_key;
-- 添加新的复合唯一约束
ALTER TABLE analysis ADD CONSTRAINT uq_analysis_image_skill UNIQUE (image_id, skill_id);

-- 4. 扩展 tasks 表
ALTER TABLE tasks ADD COLUMN analysis_skill_ids UUID[];

-- 5. 扩展 watch_plans 表
ALTER TABLE watch_plans ADD COLUMN analysis_skill_ids UUID[];

-- 6. 扩展 requests 表
ALTER TABLE requests ADD COLUMN analysis_skill_ids UUID[];
```

### 9.2 种子数据

启动时自动注入两个系统内置 skill：

1. `普通截图设计/策略分析`（profile=default, is_system=True）
2. `持续观察截图分析`（profile=watch, is_system=True）

如果已存在同名系统 skill，不重复创建。

### 9.3 配置迁移

`app_settings` 中的 `analysis_skill_prompts` 配置迁移到 `analysis_skills` 表后废弃。

---

## 10. 测试计划

后端测试：

1. 创建 AnalysisSkill（文本输入）
2. 上传 `.md` / `.txt` 创建 AnalysisSkill
3. Markdown 一级标题解析为名称
4. 内置 skill 不可删除
5. 自建 skill 可编辑、停用、删除
6. 任务选择 analysis_skill_ids
7. 图片分析按任务绑定的 skill 执行
8. 内置 skill 同时写入旧字段 + result_json
9. 自定义 skill 只写入 result_json
10. 同一图片 + 同一 skill 唯一约束
11. 自定义 skill 结果可被搜索命中
12. 导出包含动态分析结果
13. 旧数据（无 skill_id）展示不受影响

前端验证：

1. Skill 编辑页可访问，布局与 CompareSkills 对齐
2. 可用文本和上传创建 skill
3. 内置 skill 只显示编辑按钮
4. 任务表单 skill 多选交互
5. 图片分析结果按 skill 分组展示
6. 旧数据展示不受影响

---

## 11. 风险与约束

1. `image_id` unique 约束移除后，需要确认所有查询 `analysis` by `image_id` 的地方都改为处理列表。
2. 动态 JSON 解析必须容错，不能因为模型返回格式错误就丢掉其他 skill 的分析。
3. skill prompt 会直接进入 LLM 请求，需限制长度避免 token 爆炸。
4. 历史数据和新数据长期共存，前端和导出必须有回退逻辑。
5. 内置 skill 的 prompt 更新后，已有 Analysis 记录的 result_json 不会自动更新。

---

## 12. 验收标准

1. 用户可以在"分析 Skill"页面创建和上传 Markdown skill。
2. 管理员可以管理全部 skill。
3. 任务和持续观察计划可选择分析 skill。
4. 系统按任务绑定的 skill 执行截图分析。
5. 用户选择几个 skill，就返回几个维度的分析结果。
6. 设计维度和运营维度继续兼容旧字段。
7. 自定义 skill 结果可展示、可搜索、可导出。
8. 已有历史截图不被迁移或自动重跑。
