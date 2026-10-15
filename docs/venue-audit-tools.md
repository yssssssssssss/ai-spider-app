# 会场审核工具运行说明

这些工具对采集的官方会场截图做首轮审核或复核，并另存结果。测量方法见 [视觉测量](visual-measurement.md)，报告截图与框选见 [检查项证据](check-evidence.md)，规则资产见 [规范目录](specifications/official-venue-review/README.md)。

## 环境与输入

在项目根目录运行。建议使用 Python 3.12 的独立环境：

```sh
python3.12 -m venv .venv-worker
. .venv-worker/bin/activate
python3 -m pip install -r backend/requirements.txt pytest==9.0.2
```

截图测量、QR 校验和离线测试不需要 API 密钥。重新模型审核使用 `backend/app/config.py` 的配置，从环境变量或被忽略的 `.env` / `backend/.env` 读取：本脚本优先选择 OpenAI 提供方，配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`VLM_MODEL`；其他提供方配置见 `.env.example`。模型须支持多图输入。不要把密钥写入运行命令或提交文件。

在线采集需要 Ego Lite 和 `ego-browser nodejs`，以及有权查看提报列表/预览页的浏览器会话。列表必须已在同一个 TaskSpace 的 `p1` 打开；登录由操作者完成。`VENUE_SPACE` 是该空间的数字 ID。采集脚本使用 Node 内置模块和 Ego 注入的 `taskSpace`，不能直接用 `node scripts/capture_venues.mjs` 运行。任务完成后使用该空间的 `finish({keep: []})` 关闭。

复核输入目录需要 `catalog.json`、原审核 `results.json`、`qrcodes/`、每会场的两张 PNG 和 `capture.json`、`specification/walkthrough.json`、`specification/assets/` 和 `specification/source.pdf`。PDF 哈希须匹配规则来源。复核和验证都依赖原审核包仍可读取。

首轮审核使用 `--fresh --spec <profile.json>`，只需采集脚本生成的 `catalog.json`、`identity-verification.json`、`qrcodes/` 和 `venues/<record_id>/capture.json` 及截图，不读取 `results.json`。首轮仅支持 `audit_mode=h5_v2`；规范 profile 写入输出的 `specification/walkthrough.json`，参考图从仓库规范资产复制，原 PDF 不随仓库分发。正常会场的 `page_state` 由模型返回；采集失败、两屏不完整或身份未通过（包括登录页）的会场跳过模型，已启用规则记 `uncertain`，原因保存在 `page_warnings`。失败采集可以没有截图。

真实审核包、PDF 本机副本和运行结果不随代码提交；所有输入/输出路径均由参数指定，示例的 `data/deployments/` 已被忽略。

## 工具与示例

| 脚本 | 输入 → 输出 / 用途 |
| --- | --- |
| `capture_venues.mjs` | 提报列表 → `catalog.json`、QR、身份核验；再按核验入口生成两屏截图和 `capture.json`。 |
| `venue_identity.py` | 目录和 QR 像素 → `identity-verification.json`；`--repair-links` 可按 QR 修正目录预览链接并保存原目录备份。 |
| `audit_spec_profile.py` | 规范版本的 `rules_json` + `source_json`（文件或 stdin）→ `h5_v2` profile，只输出已启用且载体包含 H5 的规则。 |
| `rerun_venue_audit.py` | 完整原审核包，或 `--fresh` 采集目录 → 独立审核目录，含逐会场审核、测量和模型调用记录。可选 `--records-file` 选固定样本；`--normalize-only` 复用输出目录中已有模型响应。 |
| `build_venue_recheck_report.py` | 审核目录 → `results.json`、CSV、`report.html` 和证据 JS/CSS；首轮无新旧比较数据。 |
| `venue_check_evidence.py` | 报告构建器调用的模块；核验截图/DOM，生成展示用裁切与框选数据，无独立 CLI。 |
| `validate_venue_reaudit.py` | 已构建的复核目录及原审核包 → `validation.json`、实现副本、SHA256 清单和旁侧 ZIP；要求审核完成。 |
| `capture_tab_spacing.mjs` | 同一 Ego 空间、已构建复核目录 → `spacing/` 下实时 H5 截图、DOM 与逐会场测量记录。 |
| `apply_tab_spacing_reviews.py` | 完成的审核及实时 `spacing/` 记录 → 更新该输出目录的 OV-009、间距汇总/CSV/HTML，并重建报告。 |
| `recheck_tab_spacing.py` | 已有 `spacing-review.json` 的报告和新的规则 JSON（同名 `.md` 必须存在）→ 新目录重新判定间距，无模型调用。 |

目录采集示例（先设置 `VENUE_SPACE`，从项目根目录执行）：

```sh
VENUE_MODE=catalog VENUE_ROOT=data/deployments/venue-source ego-browser nodejs <<'JS'
const {pathToFileURL} = await import('node:url');
const path = await import('node:path');
await import(pathToFileURL(path.resolve('scripts/capture_venues.mjs')).href);
JS
```

去掉 `VENUE_MODE=catalog` 再运行同一命令采集两屏。`VENUE_PYTHON` 可指定已安装依赖的解释器，`VENUE_HELPER` 可指定 QR 校验脚本；默认从项目根目录找脚本。可选 `VENUE_RECORDS_FILE` 使用 `{"record_ids": [...]}` 选择固定样本。

采集后直接首轮审核并构建报告：

```sh
python3 scripts/rerun_venue_audit.py --fresh --source data/deployments/venue-source --output data/deployments/venue-first --spec docs/specifications/official-venue-review/h5-v5.json --concurrency 6
python3 scripts/build_venue_recheck_report.py --output data/deployments/venue-first
```

首轮输出的 `baseline.json` 标记 `fresh: true`，原始结果哈希和计数为 `null`；检查项的 `previous_status` 为 `null`。报告不读取原始结果、不生成 `comparison.json` / `comparison.csv`，`results.json` 的 `comparison` 为 `null`，可由后端 `parse_h5_results` 导入。非 `ready` 会场的报告状态为 `page_error`，导入为 `capture_failed`；导入器只读取 `page_state` 与 `page_warnings` 识别原因，含 `login` 的原因映射为 `login_required`，普通采集失败映射为 `other`。`validate_venue_reaudit.py` 仍用于有基线的复核。

规范版本转换输入为 `{"rules_json": [...], "source_json": {...}}`，使用后端版本字段的原值。CLI 默认从 stdin 读取、向 stdout 输出，也可指定文件：

```sh
python3 scripts/audit_spec_profile.py --input data/deployments/spec-version.json --output data/deployments/h5-profile.json
python3 scripts/rerun_venue_audit.py --fresh --source data/deployments/venue-source --output data/deployments/venue-versioned --spec data/deployments/h5-profile.json
```

Python 调用入口为 `scripts.audit_spec_profile.build_profile(rules_json, source_json)`。转换恢复强度名称与来源规则的扩展字段，保留 `duplicate_of`；间距、文字计数、框架和结果策略来自 `source_json`，缺失会报错，不补默认策略。`--fresh --limit N` 按目录顺序选前 N 个会场；复核的 `--limit N` 保持只选择原审核 `ready` 会场。`--records-file` 与 `--limit` 互斥，若采集只选了部分会场，审核也应使用同一份 `--records-file`。

已有完整原审核包时，先复核、再构建、最后验证：验证器需要构建器生成的 JSON 和 CSV。

```sh
python3 scripts/venue_identity.py --root data/deployments/venue-source
python3 scripts/rerun_venue_audit.py --source data/deployments/venue-source --output data/deployments/venue-recheck --spec docs/specifications/official-venue-review/h5-v5.json --concurrency 6
python3 scripts/build_venue_recheck_report.py --output data/deployments/venue-recheck
python3 scripts/validate_venue_reaudit.py --output data/deployments/venue-recheck
```

实时 Tab 测量使用同一 TaskSpace，`project` 为项目根目录，`source` 为已构建报告，`root` 为测量写入目录；可选 `records` 为 record ID 数组：

```sh
ego-browser nodejs <<'JS'
const path = await import('node:path');
const {pathToFileURL} = await import('node:url');
globalThis.tabSpacingCapture = {space: Number(process.env.VENUE_SPACE), project: process.cwd(), source: path.resolve('data/deployments/venue-recheck'), root: path.resolve('data/deployments/venue-recheck')};
await import(pathToFileURL(path.resolve('scripts/capture_tab_spacing.mjs')).href);
JS
python3 scripts/apply_tab_spacing_reviews.py --output data/deployments/venue-recheck
python3 scripts/validate_venue_reaudit.py --output data/deployments/venue-recheck
python3 scripts/recheck_tab_spacing.py --source data/deployments/venue-recheck --output data/deployments/venue-spacing-recheck --spec docs/specifications/official-venue-review/h5-v5.json
```

## 后端 H5 执行器接入

`backend/app/services/audit_job_h5.py` 提供 `register()` 与 `on_startup()`。在后端启动生命周期中先调用 `register()` 注册 H5 执行器，再调用 `on_startup()`：后者把重启前的 `running` / `ingesting` 任务标为失败，保留等待登录的任务，并唤醒串行队列。两者重复注册会复用同一个执行器；启动恢复应只在后端启动时调用。

```python
from app.services import audit_job_h5

audit_job_h5.register()
audit_job_h5.on_startup()
```

模块不在 import 时启动线程，也不修改应用入口；入口维护者需把上述调用接入启动流程。API 的 start / continue / reconcile 在请求事务提交后唤醒后台线程，线程使用独立 `SessionLocal`。当前仅适用于单进程本机后端。

H5 输入二选一：`{"catalog_url": "https://yx.jd.com/…", "venue_ids": ["RA…"]}`，或 `{"catalog_dir": "data/…", "venue_ids": ["RA…"]}`。目录必须在本仓库 `data/` 内且包含目录与身份校验文件，也接受相对于 `data/` 的路径。省略或清空 `venue_ids` 表示全部；目录模式会复制采集输入到 job 工作目录，复用源目录保持不变。工作目录为 `data/audit-jobs/<job_id>/`。

测试可向 `H5AuditExecutor(runner=..., session_factory=..., repo=...)` 注入依赖。runner 实现 `run(args, *, cwd, stdin=None, on_start=None, on_json=None, cancelled=None)`（返回含 returncode / stderr 的结果）与 `terminate(pid)`（终止整个进程组），所有 Ego 与 Python 子进程都经过此接口。

## 离线验证

测试生成小型图片/QR 或读取随代码提交的规则和 HTML fixture，不依赖真实审核包：

```sh
(cd backend && python3 -m pytest -q tests/test_tab_spacing_review.py tests/test_venue_check_evidence.py tests/test_venue_h5_policy.py tests/test_venue_reaudit.py tests/test_visual_measurement.py)
python3 -m pytest -p no:cacheprovider scripts/tests
node --test scripts/tests/web_visual_probe.test.mjs
```

最后一条只检查模块能加载；17 个浏览器断言须在 Ego Lite 中调用导出的 `validateWebVisual(page)`，见 [视觉测量验证](visual-measurement.md#验证)。
