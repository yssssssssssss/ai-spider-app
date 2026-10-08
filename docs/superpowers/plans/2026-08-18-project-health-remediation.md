# 项目健康问题修复 - Development Plan

> **状态：待审批。** 本文只定义修复方案，不代表已实施或已验证。

**Goal:** 清除当前仓库中的高风险工程卫生问题，建立单一验证入口和最小项目上下文，使后续开发、发布和 AI 协作都使用同一套可执行规则。

**Recommended approach:** 先阻断继续污染和误部署，再统一验证入口，最后收口项目说明与过期文档。复用现有 Python `unittest`、根 `package.json` 和原生 Git hooks；不引入 pytest、Husky、新服务或新的运行时依赖。

**Estimated effort:** 1.5–2 个开发日，不含凭据轮换或 Git 历史重写。

**Change size:** 会影响超过 8 个路径。绝大多数差异来自取消跟踪 `data/` 和 `worker_runs/` 下现有的 159 个运行产物；业务 API、数据库 schema 和前端功能不变。

---

## 1. Scope

### In scope

1. 停止跟踪运行截图和 Worker 日志，并阻止再次提交。
2. 检查已推送日志是否包含真实凭据，但不在输出中打印敏感值。
3. 将云端同步脚本改为默认无副作用、显式授权后才部署。
4. 建立覆盖后端、Worker、工具脚本和前端构建的单一验证入口。
5. 修复未被当前 `unittest` 命令执行的弹窗测试。
6. 启用现有 pre-commit 敏感文件检查，不新增 Husky 依赖。
7. 增加项目级 `AGENTS.md`，并让 `CLAUDE.md` 只委托到该文件。
8. 合并重复、过期的 TODO 和项目状态文档。
9. 将 `.claude/settings.local.json` 纳入仓库级忽略规则。
10. 在项目指令中统一用户可见输出语言为中文。

### Explicitly out of scope

1. 按用户要求，不处理“全局代理安全基线偏松”。
2. 不重构 `crud.py`、`manage.py`、`run_autoglm.py` 或 `index.css` 的业务实现；本轮只记录它们的边界和验证要求。
3. 不改变业务 API、数据库结构、Worker 协议或部署目录结构。
4. 不默认重写 Git 历史。只有确认已提交真实凭据时，才另开受控任务执行凭据轮换和历史清理。
5. 不新增 CI。先让本地开发与发布脚本共用一个稳定 verifier；CI 可在该命令稳定后单独评估。

---

## 2. Current evidence

| Area | Current state | Required end state |
|---|---|---|
| Runtime artifacts | `origin/main` 跟踪 `data/` 152 个文件、`worker_runs/` 7 个文件，共 182,454,214 bytes | 两个目录均不再被 Git 跟踪；运行时仍可自动创建 |
| Worker log | 一个已跟踪日志命中凭据相关关键词 | 确认是否只有字段名；真实凭据必须先轮换 |
| Deployment | `scripts/sync_to_cloud.sh` 默认真实部署到固定远端并重启服务 | 默认 dry-run；必须显式 `--apply` 且提供目标配置 |
| Verification | 根 `build` 只覆盖前端；发布脚本只跑一个后端模块 | 根 `npm run check` 覆盖全部受支持的自动检查 |
| Tests | Worker 测试独立；弹窗测试为 pytest 风格但项目未安装 pytest | 全部测试统一由 `unittest` 执行 |
| Git hook | `.husky/pre-commit` 已跟踪，但当前 clone 未启用 hooksPath | 使用原生 `.githooks`，通过显式 setup 命令启用 |
| Project context | 无 `AGENTS.md`、`CLAUDE.md` | 一个共享事实源，Claude 文件只做委托 |
| Durable docs | `TODO.md` 与 `docs/TODO.md` 分叉；验证快照分别写 129 和 77 | 只保留一个 TODO；文档引用命令，不保存瞬时通过数量 |

---

## 3. Key decisions

1. **运行数据全部退出 Git。** 代码没有引用任何已跟踪截图的固定路径，运行目录也会自行创建，因此不保留 `data/` 或 `worker_runs/` 中的现有文件作为隐式 fixture。今后如需测试图片，必须放入明确命名的 `tests/fixtures/`。
2. **不新增 pytest。** 将唯一的 pytest 风格函数改为 `unittest.TestCase`，沿用现有测试栈。
3. **不用 Husky。** 当前仓库没有 Husky 依赖；使用原生 `.githooks` 和 `git config core.hooksPath .githooks`，避免增加无价值依赖。
4. **发布必须 fail closed。** 没有 `--apply`、SSH 目标或公开验证 URL时，脚本不得发起网络或远端写操作。
5. **验证命令只有一个权威入口。** 本地开发、项目指令和发布脚本都调用根 `npm run check`，不再复制测试列表。
6. **Git 历史重写是条件动作。** 无真实凭据时不重写历史；发现真实凭据时，先轮换，再在单独维护窗口中清理历史。

**Rejected alternative:** 引入 pytest、Husky 和 GitHub Actions 一次性重建工程门禁。该方案会同时增加 Python、Node 和 CI 三层配置，无法解决当前最紧急的运行产物和误部署风险，维护成本高于收益。

**Premise collapse:** 本计划假设 `data/` 与 `worker_runs/` 都是可再生成的运行产物。现有源码搜索和项目文档支持这一判断。如果实施前发现某个文件是不可再生成的测试输入，必须先将它移动到 `tests/fixtures/` 并记录来源和用途，然后才能取消跟踪原目录。

---

## 4. Phase 1 — Contain tracked runtime artifacts

**Goal:** 当前阶段合并后，运行截图和日志不能再次进入提交；应用运行行为不变。

**Files:**

- Modify: `.gitignore`
- Modify: `manage.py`
- Modify: `scripts/pre-commit-secret-check.py`
- Modify: `backend/tests/test_flow_regressions.py`
- Remove from Git index: `data/**`
- Remove from Git index: `worker_runs/**`

### Implementation

1. 在 `.gitignore` 增加完整的 `data/` 规则和 `.claude/settings.local.json`；保留现有 `worker_runs/` 规则。
2. 使用 `git rm -r --cached data worker_runs` 取消跟踪，但不删除工作区文件。
3. 在 `manage.py::scan_tracked_ignored_files()` 中把 `data/`、`worker_runs/` 和 `.claude/settings.local.json` 视为禁止跟踪路径。
4. 在 `scripts/pre-commit-secret-check.py` 的禁止前缀中增加 `data/` 和 `worker_runs/`。
5. 扩展现有回归测试：新增文件会被阻断，删除历史文件仍允许提交。
6. 对当前提交中的 Worker 日志执行只输出文件名的关键词检查；检查真实内容时不得把值复制到 issue、文档或终端总结。
7. 若确认存在真实凭据：立即轮换对应凭据，停止合并，并单独安排历史清理。若只有字段名或脱敏文本：记录为无凭据泄漏，不重写历史。

### Verification

```bash
git ls-files data worker_runs
git check-ignore -v data/example.png worker_runs/example.log .claude/settings.local.json
python3 -m unittest backend.tests.test_flow_regressions
python3 scripts/pre-commit-secret-check.py
```

Pass criteria:

- `git ls-files data worker_runs` 无输出。
- 三个示例路径都由仓库 `.gitignore` 命中。
- pre-commit 回归测试通过。
- 本地原有截图和日志仍存在，但只作为未跟踪/忽略文件。

### Rollback

在提交前可使用 `git restore --staged data worker_runs` 恢复索引状态；`git rm --cached` 不删除本地文件。合并后如必须恢复某个 fixture，只恢复该文件到 `tests/fixtures/`，不得重新跟踪运行目录。

---

## 5. Phase 2 — Make deployment opt-in

**Goal:** 当前阶段合并后，误执行脚本不会连接远端、上传文件、切换版本或重启服务。

**Files:**

- Modify: `scripts/sync_to_cloud.sh`
- Create: `backend/tests/test_release_safety.py`

### Implementation

1. 默认 `DRY_RUN=1`；新增 `--apply`，只有该参数可将其切换为真实执行。
2. 删除固定 SSH 主机和固定公开 URL 默认值。真实执行必须提供 `AI_SPIDER_SSH_TARGET` 与 `AI_SPIDER_PUBLIC_URL`。
3. `--apply` 缺少任一必需配置时，在运行本地测试、SSH、rsync、curl 或 systemctl 前退出非零。
4. dry-run 不要求远端工具可用，只打印将执行的本地与远端动作。
5. 保留 `--dry-run` 作为显式兼容参数；与 `--apply` 同时出现时直接报错，不猜测优先级。
6. 增加 `unittest` 合同测试，覆盖：默认无副作用、缺少配置失败、冲突参数失败、脚本语法有效。

### Verification

```bash
bash -n scripts/sync_to_cloud.sh
python3 -m unittest backend.tests.test_release_safety
scripts/sync_to_cloud.sh
```

Pass criteria:

- 无参数执行只输出 dry-run 计划，没有网络或文件同步副作用。
- `--apply` 缺少目标配置时立即失败。
- 合同测试通过。

### Rollback

回滚该提交即可恢复旧行为；不涉及远端状态迁移。若已用新脚本完成部署，回滚脚本不会改变已部署 release。

---

## 6. Phase 3 — Establish one verifier and activate hooks

**Goal:** 当前阶段合并后，开发者和发布流程使用同一个验证入口，所有现有自动测试都被执行。

**Files:**

- Modify: `package.json`
- Modify: `backend/tests/test_run_workflow_popup_handler.py`
- Modify: `scripts/sync_to_cloud.sh`
- Move: `.husky/pre-commit` → `.githooks/pre-commit`

### Implementation

1. 将弹窗测试改为标准 `unittest.TestCase`，保留原断言语义。
2. 在根 `package.json` 增加：
   - `test:python`：运行 `test_flow_regressions`、`test_run_workflow_popup_handler`、`test_release_safety`、`test_worker_workflow`。
   - `check`：依次运行 `test:python` 和现有前端 `build`。
   - `setup-hooks`：执行 `git config core.hooksPath .githooks`。
3. 将 hook 移到 `.githooks/pre-commit`；继续只运行快速的 staged-file 检查，不在每次提交时跑完整测试或前端构建。
4. 修改发布脚本，使本地门禁调用 `npm run check`，删除重复的测试模块列表和重复 build 分支。

### Verification

```bash
npm run setup-hooks
git config --get core.hooksPath
npm run check
```

Pass criteria:

- hooksPath 精确为 `.githooks`。
- `npm run check` 执行所有四个 Python 测试模块和前端 production build。
- 发布脚本不再维护第二份测试列表。

### Rollback

执行 `git config --unset core.hooksPath` 可停用自定义 hook；回滚文件提交可恢复旧命令。该阶段不修改业务数据。

---

## 7. Phase 4 — Add the project instruction surface

**Goal:** 当前阶段合并后，新开发者或 AI agent 能在一次读取内理解项目边界、验证方式和高风险操作。

**Files:**

- Create: `AGENTS.md`
- Create: `CLAUDE.md`

### `AGENTS.md` required content

1. **Project map:** `backend/`、`frontend/`、`worker/`、`Open-AutoGLM` 子模块、运行目录和部署脚本的职责。
2. **Hard boundaries:**
   - Worker 不直连数据库或 OSS。
   - `data/`、`worker_runs/`、日志和本地配置不得提交。
   - 云端部署必须显式 `--apply`，不得绕过本地 verifier。
3. **Verification:** 唯一默认命令为 `npm run check`；密钥诊断使用 `npm run doctor-secrets`；Git hook 初始化使用 `npm run setup-hooks`。
4. **Hotspot map:** 说明 `backend/app/crud.py`、`manage.py`、`run_autoglm.py` 和 `frontend/src/styles/index.css` 的稳定边界及修改后必须运行的检查。
5. **Communication:** 所有用户可见 commentary 和 final 使用中文；代码、命令与原文引文除外。
6. **Non-goals:** 不把一次性验证结果、机器路径、凭据或发布快照写入项目指令。

`CLAUDE.md` 只包含对 `AGENTS.md` 的委托，不复制任何规则。

### Verification

```bash
test -s AGENTS.md
test "$(tr -d '\r\n' < CLAUDE.md)" = "@AGENTS.md"
rg -n "npm run check|npm run doctor-secrets|npm run setup-hooks" AGENTS.md
```

Pass criteria:

- 项目 instruction surface 不再为 FAIL。
- Claude 与 Codex 读取同一项目事实源。
- 文档引用检查通过。

### Rollback

删除两个新增文件即可；不影响运行时。

---

## 8. Phase 5 — Remove durable documentation drift

**Goal:** 当前阶段合并后，仓库只有一个任务状态来源，验证结果由命令产生而不是手工维护数字。

**Files:**

- Modify: `TODO.md`
- Remove: `docs/TODO.md`
- Remove: `docs/TASK_STATUS.md`
- Remove: `docs/project_status.md`
- Modify only if links require it: directly referencing Markdown files

### Implementation

1. 以根 `TODO.md` 为唯一任务状态来源，只保留未完成且仍有效的工作项。
2. 删除“本轮 77/129 个测试通过”、live health、向量维度、重复组数量等瞬时快照。
3. 将验证说明替换为 `npm run check`、`npm run doctor-secrets` 和明确的人工验收条件。
4. 删除两个 2026-05-27 项目状态快照；Git 历史已经保留其内容，不在仓库中建立 archive 副本。
5. 修复删除后产生的 Markdown 引用。

### Verification

```bash
rg -n "docs/(TODO|TASK_STATUS|project_status)\.md" . --glob "*.md" --glob "!docs/superpowers/plans/2026-08-18-project-health-remediation.md"
rg -n "本轮.*通过|当前验证快照|生成时间：2026-05-27" TODO.md docs --glob "!docs/superpowers/plans/2026-08-18-project-health-remediation.md"
```

Pass criteria:

- 两条 `rg` 命令均无输出，表示没有失效状态文档引用或旧验证快照。
- 任务状态只在根 `TODO.md` 维护。

### Rollback

从 Git 恢复被删除文档即可；不影响运行时或数据。

---

## 9. Repository-external follow-up

该任务不进入项目修复提交，也不阻塞上述五个阶段：在独立的全局配置维护会话中，为 10 个跨 runtime、同名但内容不同的技能指定唯一权威来源：`agent-reach`、`grill-me`、`grill-with-docs`、`handoff`、`improve-codebase-architecture`、`prototype`、`setup-matt-pocock-skills`、`tdd`、`triage`、`vercel-react-best-practices`。处理完成后重新运行 health collector，验收条件为 `cross_runtime_conflicts: 0` 或每个保留分歧都有明确的 runtime 专用名称。

本跟进不包含用户明确排除的全局代理安全基线整改。

---

## 10. Final acceptance checklist

- `origin/main` 的新提交不再跟踪 `data/` 或 `worker_runs/`。
- 已提交 Worker 日志完成敏感内容确认；若存在真实凭据，已先完成轮换。
- 无参数发布脚本没有外部副作用，真实发布必须显式 `--apply`。
- `npm run check` 覆盖全部 Python 测试模块和前端 production build。
- `.githooks/pre-commit` 已启用并阻止运行产物或敏感文件进入暂存区。
- `AGENTS.md` 是唯一项目指令事实源，`CLAUDE.md` 不复制规则。
- 主要代码热点具有边界和对应 verifier 说明。
- 根 `TODO.md` 是唯一任务状态文档，不包含瞬时验证数字。
- health 的文档引用、instruction surface 和 maintainability 检查不再报告本计划覆盖的问题。
- 工作树只包含本计划声明的文件变化，无业务 API、schema 或协议变更。

## 11. Release and rollback

1. Phase 1 和 Phase 2 作为 P0，必须先合并；二者可独立回滚。
2. Phase 3–5 各自独立提交，上一阶段完成后系统始终可开发、可验证、可发布。
3. 合并 Phase 2 后，首次真实部署先运行 `npm run check`，再显式传入目标配置和 `--apply`。
4. 若 Phase 1 发现真实凭据，不进行普通发布；先轮换凭据，再决定是否安排 Git 历史重写。
5. Git 历史重写会影响所有 clone 和分支，必须作为单独维护任务获得明确批准，不能混入本计划的普通修复提交。
