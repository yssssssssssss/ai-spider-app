# 审核工作台视觉设计稿

来源：设计画布「项目走查 · 全周期视觉方案」（https://claude.ai/artifact/TmTte5rWrjZBx9WjxZWCia）导出的画面源文件。
这些 `.dc.html` 是画布专用格式（`<x-dc>` 模板 + `renderVals()` 数据），只作为视觉与交互参考，不能直接运行，也不要复制其中的数据。

| 文件 | 画面 | 对应路由 |
| --- | --- | --- |
| Scale.dc.html | ⑤ 大规模审核驾驶舱 | `/audits/:runId` |
| Structure.dc.html | ④ 信息架构 | 导航与 `/specs`、`/audits` 列表的组织方式 |
| Main.dc.html | ① 项目驾驶舱 | `/audit-projects/:id` |
| Matrix.dc.html | ② 规范矩阵 | `/audit-projects/:id` 内的矩阵视图 |
| Lifeline.dc.html | ③ 页面生命线 | `/audit-projects/:id/pages/:pageKey` |

设计稿中的“重点会场 11 个”未按 `duplicate_of` 去重；以 API 计算结果（7 个）为准。截图证据区、“发起复查”“标记为已知例外”按钮不在 v2 范围内。
