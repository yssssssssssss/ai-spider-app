# 竞品分析平台 - 设计文档

**日期**: 2026-05-26  
**项目**: ai-taobao-app 竞品分析平台升级  
**阶段**: Phase 1 (数据基础设施 + Phase 2 AI分析)  

---

## 1. 项目背景与目标

在现有自动化截图采集工具（uiautomator2/Appium + OpenCV裁剪）基础上，构建一个完整的竞品分析平台，实现：

1. **图片数据持久化**：将采集的截图结构化存入数据库，记录时间、来源App、场景等维度
2. **AI智能分析**：对每张图片自动进行"设计角度"和"运营角度"双维度LLM分析
3. **前台交互界面**：用户可提交竞品搜集需求，并通过自然语言检索历史分析结果
4. **后台管理界面**：汇总审核用户提交的需求，调度采集/分析/入库全流程

---

## 2. 技术栈确认

| 层次 | 技术选型 | 理由 |
|------|----------|------|
| 数据库 | PostgreSQL + pgvector | 支持JSONB存储非结构化分析结果，pgvector支撑文本向量检索，为后续混合检索预留扩展空间 |
| 后端 | FastAPI (Python) | 与现有Python采集脚本同栈，异步支持好，自动API文档 |
| 前端 | React | 前后端分离，组件生态丰富，前后台界面统一技术栈 |
| LLM分析 | 复用 AutoGLM/VLM 通道 | 现有 `Open-AutoGLM/phone_agent/model/client.py` 可直接复用 |
| 文本检索 | OpenAI text-embedding-3-small (或智谱Embedding API) | 1536维向量，成本低，与pgvector兼容 |
| 异步任务 | FastAPI BackgroundTasks (Phase 1) → Celery (Phase 2扩展) | Phase 1轻量启动，后续高并发时升级为Celery+Redis |

---

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户层                                │
│  ┌──────────────┐                    ┌─────────────────┐   │
│  │  前台 (React) │                    │  后台 (React)    │   │
│  │  - 需求提交   │                    │  - 需求汇总审核  │   │
│  │  - 自然语言检索│                   │  - 任务调度管理  │   │
│  └──────┬───────┘                    └────────┬────────┘   │
└─────────┼─────────────────────────────────────┼────────────┘
          │                                     │
          ▼                                     ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI 后端                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ /api/    │  │ /api/    │  │ /api/    │  │ /api/    │  │
│  │ requests │  │ tasks    │  │ images   │  │ search   │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       └─────────────┴─────────────┴─────────────┘         │
│                         │                                   │
│                         ▼                                   │
│              ┌─────────────────────┐                       │
│              │  LLM Analysis Module│                       │
│              │  (设计/运营双维度)   │                       │
│              └─────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│              PostgreSQL + pgvector                          │
│  ┌────────┐  ┌──────────┐  ┌────────┐  ┌────────────┐    │
│  │ images │  │ analysis │  │ tasks  │  │ embeddings │    │
│  └────────┘  └──────────┘  └────────┘  └────────────┘    │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│           现有采集模块（复用 uiautomator2）                  │
│        step1-down_img.py / run_workflow.py                  │
└─────────────────────────────────────────────────────────────┘
```

### 核心设计原则

- **数据库为中心**：所有状态（图片、分析、任务、需求）持久化到PostgreSQL
- **异步分析**：图片入库后自动触发LLM分析（FastAPI BackgroundTasks）
- **向量检索**：pgvector存储文本embedding，支撑自然语言检索
- **现有采集模块复用**：不改现有采集逻辑，通过新增任务调度层来驱动

---

## 4. 数据库设计

### 4.1 表结构

#### `images` — 图片主表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID, PK | 主键 |
| `file_path` | TEXT, NOT NULL | 图片存储路径 |
| `source_app` | TEXT | 来源App: `taobao`, `pdd` 等 |
| `scenario` | TEXT | 场景: `首页`, `搜索页`, `商品详情`, `百亿补贴` 等 |
| `captured_at` | TIMESTAMP | 截图时间 |
| `task_id` | UUID, FK → tasks | 关联采集任务 |
| `created_at` | TIMESTAMP | 入库时间 |

#### `analysis` — LLM分析结果表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID, PK | 主键 |
| `image_id` | UUID, FK → images | 关联图片 |
| `design_analysis` | TEXT | LLM设计角度分析 |
| `ops_analysis` | TEXT | LLM运营角度分析 |
| `analyzed_at` | TIMESTAMP | 分析完成时间 |
| `status` | ENUM | `pending`/`success`/`failed` |

#### `requests` — 用户竞品搜集需求表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID, PK | 主键 |
| `user_id` | TEXT | 提交用户标识（前台匿名或简单标识） |
| `target_app` | TEXT | 目标App |
| `target_scenario` | TEXT | 目标场景 |
| `keywords` | TEXT[] | 竞品关键词数组 |
| `description` | TEXT | 补充说明 |
| `status` | ENUM | `pending`/`approved`/`rejected` |
| `created_at` | TIMESTAMP | 提交时间 |

#### `tasks` — 采集任务表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID, PK | 主键 |
| `request_id` | UUID, FK → requests, nullable | 关联需求（可为空，管理员直接创建） |
| `name` | TEXT | 任务名称 |
| `keyword` | TEXT | 采集关键词 |
| `target_app` | TEXT | 目标App |
| `target_scenario` | TEXT | 目标场景 |
| `status` | ENUM | `pending`/`running`/`completed`/`failed` |
| `admin_id` | TEXT | 审核管理员标识 |
| `approved_at` | TIMESTAMP | 审核通过时间 |
| `completed_at` | TIMESTAMP | 任务完成时间 |

#### `embeddings` — 文本向量表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID, PK | 主键 |
| `analysis_id` | UUID, FK → analysis | 关联分析结果 |
| `embedding` | VECTOR(1536) | pgvector向量，文本语义表征 |
| `content_type` | TEXT | `design` / `ops` / `combined` |

### 4.2 设计说明

- `images.source_app` 和 `images.scenario` 与现有 `WorkflowStep` 的 `app` 字段对齐
- `tasks` 可独立创建（管理员直接发起），也可由 `requests` 审批后转换
- `embeddings` 维度1536兼容OpenAI text-embedding-3-small；后续升级混合检索时，图片视觉embedding可新增表或列

---

## 5. LLM分析模块

### 5.1 触发时机

图片入库后自动触发（FastAPI BackgroundTasks），或后台手动触发单图重分析。

### 5.2 Prompt设计

```
你是一位电商竞品分析专家。请对以下截图进行双维度分析，输出为JSON格式：

{
  "design_analysis": "从UI设计角度分析（布局、配色、视觉层级、信息架构、交互细节等）",
  "ops_analysis": "从运营策略角度分析（促销手段、文案策略、价格策略、用户引导、转化漏斗等）"
}

要求：
- 每个维度200-500字
- 具体指出截图中的设计/运营亮点
- 如果是系列截图，请与前几张做对比分析（如有上下文）
```

### 5.3 实现方式

- 复用现有 AutoGLM/VLM 调用通道
- 图片转base64 → 调用多模态LLM → 解析JSON → 写入 `analysis` 表
- 异步执行，避免阻塞入库流程

### 5.4 错误处理

| 场景 | 处理方式 |
|------|----------|
| LLM返回非JSON | 用正则提取文本块，写入 `design_analysis` 或 `ops_analysis`，状态标记为 `partial` |
| LLM调用失败 | 重试3次（指数退避），最终标记 `status = failed`，后台可手动重试 |
| 某维度为空 | 允许单维度分析，缺失维度记为 `null` |

---

## 6. API设计（FastAPI）

### 6.1 前台接口

```
POST   /api/requests          # 提交竞品搜集需求
       Body: { target_app, target_scenario, keywords[], description? }

GET    /api/requests/{id}     # 查询需求状态

POST   /api/search            # 自然语言检索竞品图片
       Body: { query: "红色大促弹窗设计", limit: 20, offset: 0 }
       → 返回: [{ image_id, file_path, design_analysis, ops_analysis, similarity }]
```

### 6.2 后台接口

```
GET    /api/admin/requests    # 汇总所有用户提交的需求（支持状态/时间筛选、分页）

PUT    /api/admin/requests/{id}/approve  # 审核通过，自动生成采集任务
       Body: { admin_id, keyword?, target_app?, target_scenario? }

PUT    /api/admin/requests/{id}/reject   # 审核拒绝
       Body: { admin_id, reason? }

GET    /api/admin/tasks       # 任务列表（支持状态筛选、分页）

POST   /api/admin/tasks/{id}/run         # 手动触发采集任务
       → 调用现有采集脚本，异步执行

GET    /api/admin/tasks/{id}/progress    # 查询任务进度（已采集数、已分析数）
```

### 6.3 内部/采集端接口

```
POST   /api/images            # 图片入库（采集端上传或本地扫描）
       Body: { file_path, source_app, scenario, task_id, captured_at }
       → 入库成功后自动触发LLM分析

POST   /api/images/{id}/analyze         # 手动触发单图LLM分析
```

---

## 7. 前端界面设计

### 7.1 前台（React）

| 页面 | 功能 |
|------|------|
| **需求提交页** | 表单：目标App下拉、目标场景输入、竞品关键词标签输入、补充说明文本框；提交后显示需求ID和状态 |
| **检索页** | 顶部自然语言搜索框 + 结果卡片流：图片缩略图 + 设计/运营分析摘要高亮 + 来源App/场景标签 |

### 7.2 后台（React）

| 页面 | 功能 |
|------|------|
| **需求汇总页** | 表格：用户提交列表（ID、目标App、关键词、状态、提交时间）+ 筛选（状态/时间范围）+ 批量审核通过/拒绝 |
| **任务管理页** | 任务列表（名称、关键词、状态、进度条）+ 手动触发/停止按钮 + 查看已采集图片和分析 |
| **数据看板** | 统计卡片：今日采集量、待分析数、待审核需求数、任务完成率 |

---

## 8. 分阶段实施计划

### Phase 1：数据基础设施（Week 1-2）

1. 搭建PostgreSQL + pgvector环境
2. 创建数据库表（`images`, `analysis`, `requests`, `tasks`, `embeddings`）
3. 创建图片入库脚本（扫描现有 `data/` 目录，批量导入）
4. 集成采集脚本：在 `run_workflow.py` 中新增图片入库逻辑

### Phase 2：AI分析（Week 2-3）

1. 开发LLM分析模块（Prompt + JSON解析 + 错误处理）
2. 开发文本embedding生成模块
3. 开发异步分析触发器（图片入库后自动触发）
4. 存量图片批量分析脚本

### Phase 3：前台界面（Week 3-4）

1. FastAPI后端：需求提交接口、检索接口
2. React前台：需求提交页、自然语言检索页
3. 集成文本向量检索（pgvector `<=>` 距离排序）

### Phase 4：后台界面（Week 4-5）

1. FastAPI后端：需求审核接口、任务调度接口、进度查询
2. React后台：需求汇总页、任务管理页、数据看板
3. 采集任务调度：审核通过后调用现有采集脚本

### Phase 5：优化与扩展（Week 5-6）

1. 混合检索升级（图片CLIP embedding，可选）
2. 任务队列升级（Celery + Redis）
3. 用户权限与登录（如需要）
4. 性能优化与监控

---

## 9. 关键决策记录

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 数据库 | PostgreSQL + pgvector | 支持JSONB和向量检索，功能全面 |
| 前后端架构 | FastAPI + React（前后端分离） | 用户明确要求 |
| LLM分析输出 | 自由发挥文本，固定双维度 | 用户确认 |
| 检索方案 | Phase 1 纯文本语义匹配 | 实现简单，基于已有LLM分析文本 |
| 异步任务 | FastAPI BackgroundTasks | Phase 1轻量，后续可升级Celery |
| 图片embedding | 暂不实现（Phase 5可选） | 降低初期复杂度，pgvector预留扩展 |

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM API调用成本高 | 分析费用不可控 | 增加分析开关、批量折扣、本地模型备选 |
| 采集脚本与后端耦合 | 采集失败影响入库 | 采集与入库解耦，采集脚本独立运行，通过API或文件扫描上报 |
| pgvector性能瓶颈 | 向量检索慢 | 加向量索引（ivfflat/hnsw），分页限制返回数量 |
| 图片存储膨胀 | 磁盘占用大 | 定期归档/压缩，或迁移到对象存储（OSS/S3） |

---

*文档版本: v1.0*  
*等待用户审阅与确认*
