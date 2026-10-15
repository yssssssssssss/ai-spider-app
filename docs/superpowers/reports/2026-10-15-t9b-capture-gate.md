T9b 采集闸门交付报告（2026-10-15）

已实现 Python 纯函数闸门、模型调用前拦截、楼层异常降级、任务汇总、仅重采失败会场 API 和前端入口。无新增依赖；未提交代码。`audit_workspace.py` 仅改 `_capture_failure` 中的原因优先级，保留旧数据回退，便于与 T9a-1 合并。

**实现与边界**

- 强信号集中在 `h5_capture_gate.PATTERNS`；未知页面放行。旧采集缺少首屏文字时支持三个已核对的特殊标题；新采集的“提示”标题需要正文信号，普通“请登录领取优惠券”文案不触发登录拦截。
- 被拦页面写入 `page_state=error`、单条闸门警告、全部 checks 为 uncertain、空 `model_calls` 和 `capture_gate`。报告生成器产出 `page_error`，收录后保留具体原因代码。
- `floor_error` 继续调用模型，强制涉及结构、顺序、首屏商品和间距的激活规则待确认。重采恢复后不继承上一轮闸门警告。
- fresh 审核及更新后的重审采集均先过闸；较新的截图可更新输出缓存。没有变更的有效旧缓存补上闸门元数据，无额外模型调用。`--no-gate` 关闭新增闸门，既有身份及完整性检查仍生效。
- 任务使用现有 `executor_ref_json.summary` 存储 `{gate: {blocked, by_reason, degraded}, blocked_venue_ids, hint?}`，无需迁移数据库。`by_reason` 统计阻断原因。迷路占所选会场至少 30% 时提示“可能是预览时间或预览链接失效”。汇总在报告步骤前保存，后续失败仍可重采。
- operator 可对 completed/failed H5 任务创建新任务；保留规范版本、项目、阶段及目录来源，只选被拦会场。目录来源通过 `force_recapture` 重新采集，避免复用旧的失败截图。无被拦会场、非 H5 或其他状态返回 409；viewer/未登录分别返回 403/401。
- 前端沿用既有类名，显示拦截计数、原因、降级数、提示和重采按钮；完成但有被拦会场的任务卡仍可见并可关闭。补充新 capture_reason 的中文标签。

**408 会场离线回放**

输入为用户指定的只读 `official-venue-audit-20261012-h5-v5-annotated-all408/results.json`，分类器只读取每条 result 的 capture，不读取模型判定或警告。退出码 0。

```text
total: 408
ground truth       blocked  not_blocked
page_error             202            4
valid                    0          202
blocked by_reason: {"expired": 3, "login_required": 3, "venue_lost": 196}
degraded by_reason: {}
```

有效会场误拦 0。与任务预期的 201 个标题可识别页存在一项样本差异：实际文件包含 **3 个**“京东登录注册”标题。额外的 `RA100917354732553734` 落地京东登录 URL，原审核警告为 `unverified_redirect`，概述为“正确二维码入口重定向到不同活动的登录页，页面身份无法核实”。因此按登录强信号拦截，总数为 202。

3 个“提示”页均已核对原 `audit.page_warnings`，明确写有“已过期、已结束的活动，暂不支持预览”：`RA092413440857595594`、`RA093009424331285923`、`RA100818290232970048`，全部归入 expired。

另外 4 个 page_error 使用真实会场标题，旧 capture 没有足以判定楼层异常或加载状态的正文，保守返回 ok，留给模型判断。未通过读取模型警告来补充闸门信号。

**验证**

最终在新建的 `t9b_test`（已创建 vector 扩展）上全量执行：**553 passed、3 skipped、1 failed**，耗时 37.66 秒。唯一失败为任务预先说明的 `test_analysis_skill_management_updates_prompt_overrides`，断言内置 system skills 数量至少 1，实际为 0。T9b 用例全部通过。测试完成后已删除 `t9b_test`；指定的 `data/oss-preferred-*.png`、`data/audit-jobs/`（含 backend 相对路径）检查为空。未连接 `competitor_db` 或 `audit_projects_demo`。

最终执行命令（数据库 URL 省略凭据）：

```sh
cd backend
GIT_TRACE2_EVENT=0 PYTEST_ADDOPTS='-p no:capture' \
DATABASE_URL='<t9b_test URL>' \
PYTHONPATH=/Users/heyunshen/work/PROJECT/jdc/ai-spider-app/Open-AutoGLM \
../.venv/bin/python3 -m pytest -p no:cacheprovider tests ../scripts/tests
```

`cd frontend && npm run build` 通过（TypeScript 与 Vite，133 个模块）。`git diff --check` 通过。测试覆盖各原因、保守放行、旧采集、无模型调用、page_error 报告、开关、缓存及新采集、原因收录、29%/30% 阈值、报告失败保留汇总、目录重新采集及 API 权限。

测试环境差异：本机 Python 的 readline 扩展导入会段错误，使用 `PYTEST_ADDOPTS='-p no:capture'` 跳过 pytest 输出捕获插件；本机 git-ai 会在临时 Git 仓库删除时后台写 notes，使用 `GIT_TRACE2_EVENT=0` 仅关闭测试子进程的 Git trace 通知，消除该清理竞态。未修改依赖、测试断言、仓库或全局 Git 配置来规避这些环境问题。

**改动文件**

- `backend/app/services/h5_capture_gate.py`：分类规则及纯函数。
- `scripts/rerun_venue_audit.py`：模型前闸门、降级与采集缓存更新、`--no-gate`。
- `scripts/replay_capture_gate.py`：离线混淆矩阵与误拦退出码。
- `backend/app/services/audit_workspace.py`：优先使用闸门 capture_reason。
- `backend/app/services/audit_job_h5.py`：任务汇总与目录强制重采。
- `backend/app/services/audit_jobs.py`：重采任务创建与状态约束。
- `backend/app/routers/audit_workspace.py`：operator 重采接口。
- `frontend/src/api.ts`：接口及闸门原因、任务汇总类型。
- `frontend/src/components/AuditJobUI.tsx`：汇总、提示、重采按钮及完成卡可见性。
- `frontend/src/components/AuditWorkspaceUI.tsx`：新原因中文标签。
- `backend/tests/test_h5_capture_gate.py`：分类及解析回归。
- `backend/tests/fixtures/h5_capture_gate_408.json`：来自只读样本的 12 条代表性元数据。
- `backend/tests/test_audit_job_h5.py`：汇总阈值、失败保留与真实重采路径。
- `backend/tests/test_audit_jobs.py`：重采上下文、状态及权限。
- `scripts/tests/test_venue_fresh_audit.py`：模型调用、报告、开关、缓存及恢复路径。
- `scripts/tests/test_capture_gate_replay.py`：回放退出码及原因统计。
- 本报告。
