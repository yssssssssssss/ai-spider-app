# 会场审核工具运行说明

这些工具复核已冻结的官方会场截图，并另存结果。测量方法见 [视觉测量](visual-measurement.md)，报告截图与框选见 [检查项证据](check-evidence.md)，规则资产见 [规范目录](specifications/official-venue-review/README.md)。

## 环境与输入

在项目根目录运行。建议使用 Python 3.12 的独立环境：

```sh
python3.12 -m venv .venv-worker
. .venv-worker/bin/activate
python3 -m pip install -r backend/requirements.txt pytest==9.0.2
```

截图测量、QR 校验和离线测试不需要 API 密钥。重新模型审核使用 `backend/app/config.py` 的配置，从环境变量或被忽略的 `.env` / `backend/.env` 读取：本脚本优先选择 OpenAI 提供方，配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`VLM_MODEL`；其他提供方配置见 `.env.example`。模型须支持多图输入。不要把密钥写入运行命令或提交文件。

在线采集需要 Ego Lite 和 `ego-browser nodejs`，以及有权查看提报列表/预览页的浏览器会话。列表必须已在同一个 TaskSpace 的 `p1` 打开；登录由操作者完成。`VENUE_SPACE` 是该空间的数字 ID。采集脚本使用 Node 内置模块和 Ego 注入的 `taskSpace`，不能直接用 `node scripts/capture_venues.mjs` 运行。任务完成后使用该空间的 `finish({keep: []})` 关闭。

复核输入目录需要 `catalog.json`、原审核 `results.json`、`qrcodes/`、每会场的两张 PNG 和 `capture.json`、`specification/walkthrough.json`、`specification/assets/` 和 `specification/source.pdf`。PDF 哈希须匹配规则来源。**采集脚本只生成目录、QR 和截图，不生成原审核 `results.json` 或规范副本**；需先提供已有的完整审核包。复核和验证都依赖原审核包仍可读取。真实审核包、PDF 本机副本和运行结果不随代码提交；所有输入/输出路径均由参数指定，示例的 `data/deployments/` 已被忽略。

## 工具与示例

| 脚本 | 输入 → 输出 / 用途 |
| --- | --- |
| `capture_venues.mjs` | 提报列表 → `catalog.json`、QR、身份核验；再按核验入口生成两屏截图和 `capture.json`。 |
| `venue_identity.py` | 目录和 QR 像素 → `identity-verification.json`；`--repair-links` 可按 QR 修正目录预览链接并保存原目录备份。 |
| `rerun_venue_audit.py` | 完整原审核包、可选 `--spec` / `--records-file` → 独立复核目录，含逐会场审核、测量和模型调用记录。`--normalize-only` 复用输出目录中已有模型响应。 |
| `build_venue_recheck_report.py` | 复核目录 → `results.json`、比较数据、CSV、`report.html` 和证据 JS/CSS。 |
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

## 离线验证

测试生成小型图片/QR 或读取随代码提交的规则和 HTML fixture，不依赖真实审核包：

```sh
(cd backend && python3 -m pytest -q tests/test_tab_spacing_review.py tests/test_venue_check_evidence.py tests/test_venue_h5_policy.py tests/test_venue_reaudit.py tests/test_visual_measurement.py)
python3 -m pytest -q scripts/tests
node --test scripts/tests/web_visual_probe.test.mjs
```

最后一条只检查模块能加载；17 个浏览器断言须在 Ego Lite 中调用导出的 `validateWebVisual(page)`，见 [视觉测量验证](visual-measurement.md#验证)。
