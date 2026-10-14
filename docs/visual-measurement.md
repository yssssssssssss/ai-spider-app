# 视觉测量工具

当前提供可独立调用的测量模块和命令行工具，像素测量本身不需要调用模型或数据库。已接入 `scripts/rerun_venue_audit.py` 的冻结截图批量复核流程：模型定位区域，工具计算数值，规则处理器依据证据判定适用性。在线后台任务尚未接入；本轮结果另存，保留原始审核作为对照。

## 提供的能力

| 工具 | 输入 | 输出 | 使用边界 |
| --- | --- | --- | --- |
| 区域取色 | 原始截图、区域坐标 | 主色、前5种颜色及占比、指定色匹配比例 | 读取实际像素；混色区域不会被平均成一个虚构颜色 |
| 背景色条带识别 | 截图、搜索区域、背景色 | 条带坐标、宽/高、匹配比例 | 多条结果均保留为候选；白色空白不自动等同于楼层间隔 |
| 边缘距离 | 截图、两个组件的边界框 | 水平/垂直边缘距离、接触或重叠关系 | 边界框需要先准确定位；模型给出的近似框不能作为精确组件边界 |
| 网页样式和布局取值 | Ego Lite Page、明确的CSS选择器 | 字体色、背景色、圆角、margin/padding、组件间CSS距离 | 面向直接打开的H5页面；不读取Android原生界面或后台配置 |

Python实现位于 `backend/app/services/visual_measurement.py`，命令行入口为 `scripts/measure_visual.py`；网页实现为 `scripts/web_visual_probe.mjs`。

## 从历史截图复现

在项目根目录使用已安装 `backend/requirements.txt` 的Python环境：

```bash
python scripts/measure_visual.py \
  --image data/tasks/official-venue-audit-20261010/venues/p01-r15-RA100818285918762070/screen-2.png \
  --capture data/tasks/official-venue-audit-20261010/venues/p01-r15-RA100818285918762070/capture.json \
  --plan docs/examples/visual-measurement-plan.json \
  --output data/tasks/visual-measurement-20261010/screenshot-measurement.json \
  --html data/tasks/visual-measurement-20261010/report.html
```

该样例的区域经过人工查看截图选取。工具读出左侧背景 `#E999D0`、卡片空白处 `#FFFFFF`，并在选定纵向区域找到长度为 `3、4、4、4、3` 截图像素的纯背景色条带。条带长度表示连续满足颜色条件的像素行数，边缘抗锯齿可能使它小于实际布局间隔。

`--capture` 可省略；提供时必须匹配文件名、SHA256和尺寸，结果会携带原会场名称、会场ID、通天塔项目ID和对应屏幕信息。报告另存，原始截图保持不变；HTML内嵌原图，叠加测量区域标注，JSON记录截图和测量计划的哈希。

## 计划格式

坐标采用 `[left, top, right, bottom]`，右边界和下边界不包含在区域中，单位为原始截图像素。所有坐标必须在图内，不能直接使用模型返回的归一化坐标。

```json
{
  "measurements": [
    {
      "id": "floor-gap",
      "label": "已定位的两个楼层边缘距离",
      "rule_id": "OV009",
      "kind": "distance",
      "params": {
        "first_bbox": [10, 100, 380, 200],
        "second_bbox": [10, 212, 380, 312],
        "axis": "vertical"
      },
      "length_comparison": {"expected_design_px": 24}
    }
  ]
}
```

上面是格式示例，坐标没有对应本项目的某个真实楼层。测量将得到12截图像素，比较状态为 `needs_calibration`，不会据此判不合规。用户已选择先输出截图像素，因此当前不默认套用750设计稿或CSS单位。

`color.params` 使用 `bbox`，可选 `expected_hex`；`bands.params` 使用 `bbox` 和 `background_hex`，可选 `axis`、`min_length_px`、`min_matching_ratio`；两者可显式指定 `max_channel_delta`。默认每个RGB通道容差为0，条带每行匹配比例必须为100%。这些是识别参数，不是规范中的验收容差。

后续明确单位时，`length_comparison` 可以补充 `image_px_per_design_px` 和 `calibration_source`；缺少来源会拒绝比较。没有明确的 `tolerance_design_px` 时，只输出换算结果和差值。即使得到 `within_tolerance`，也仍需确认组件边界和规则适用性，才能形成审核结论。

## 网页取值

先用Ego Lite快照或可见DOM确认组件及选择器，再传入测量模块。选择器必须唯一；不存在、重复、隐藏或不完整显示的组件会产生明确状态，距离计算仅接受完整位于视口内的目标。

```javascript
const {probeWebVisual} = await import(
  "file:///绝对项目路径/scripts/web_visual_probe.mjs"
);
const facts = await probeWebVisual(page, {
  targets: [
    {id: "title", selector: ".jd-header-new-title"},
    {id: "floor-a", selector: "#已确认的楼层A"},
    {id: "floor-b", selector: "#已确认的楼层B"}
  ],
  distances: [
    {id: "floor-gap", first: "floor-a", second: "floor-b", axis: "vertical"}
  ]
});
```

网页工具读取的是CSS计算值和渲染后的DOM边界框，同时保留DPR、视口缩放、滚动位置、祖先透明度和变换信息。带透明度、渐变、阴影、滤镜或遮挡的元素，其计算样式不直接等同于最终显示像素。工具不会检查遮挡，也不会测量伪元素、跨域iframe或推断App原生导航栏配置；建议直接打开会场预览链接。

## 规范与工具的对应关系

- OV008：H5标题可读取计算样式，避免从抗锯齿文字反推原始色值；App原生状态栏仍需要原生证据。
- OV009：先确认楼层边界，再测距离。当前记录截图像素或CSS像素，24PX的单位换算尚未确定。
- OV010：可测背景是否呈白色；PDF中的“必须白色”“建议白色”与非白色分支，需要业务口径统一，工具无法替代该决策。
- OV011：H5可读取卡片圆角和间距；截图工具当前没有实现圆角拟合，不能从模型的近似框精确推断圆角。
- OV012：可记录卡片间实际距离和背景色条带。规范没有数值下限，因此样例的3～4像素条带不能单独作为不合规依据。

截图工具记录解码后的RGB通道，不进行ICC色彩转换，也不推断JPEG压缩前的原始色值；透明像素不会被当作白色背景。命令行拒绝动图及带EXIF旋转的图片，避免测量坐标与浏览器显示方向不一致。文字、图片、渐变和水印混在同一区域时，颜色占比不会自动成为整个组件的色值。

## 批量复核

```bash
python scripts/rerun_venue_audit.py \
  --source data/tasks/official-venue-audit-20261010 \
  --output data/tasks/official-venue-audit-20261010-recheck \
  --concurrency 8
python scripts/build_venue_recheck_report.py \
  --output data/tasks/official-venue-audit-20261010-recheck
python scripts/validate_venue_reaudit.py \
  --output data/tasks/official-venue-audit-20261010-recheck
```

复核先验证原截图SHA256及尺寸，冻结原408个会场的身份信息，再对正常展示的截图重新调用视觉模型。未就绪截图按原图与原分类留待确认。每个会场保留模型响应、区域请求、工具结果及调用记录；失败可重新运行，已有完成结果会跳过。`--normalize-only` 可在已有模型响应上重算像素与规则，不产生额外模型调用。

背景定位框可能含水印或卡片边缘。确认白色背景时要求区域主色覆盖至少95%；定位非白色背景取样时要求主色占比至少50%。工具进一步寻找完全不透明、颜色一致的3×3像素块，保留原区域直方图和纯色取样坐标。区域足够大时，还会在下半部分查找第二处纯色取样。至少两处不同的、语义清晰的feeds背景取样均为白色，才将OV-011/012转为本次可见范围不适用；单处、定位不清、混色或取样不一致都不触发该变更。这些比例是定位质量门槛，不是规范的色值容差。

本批截图有水印，背景色条带使用90%的行/列颜色匹配比例，RGB通道容差为0。这是识别参数，不是规范验收容差。扫描条带触及搜索框边缘时会标记 `touches_search_boundary`，不能把被截断的条带长度当作完整组件间距。条带数值不自动触发24PX判定。

HTML提供每会场两屏、逐项新旧结论和像素区域标注；JSON及CSV分别记录全部结论、测量和变化来源。白背景条件确认产生的变更与重新模型审核产生的变更分开统计。本轮不混用新的线上DOM与旧截图，因此网页CSS测量模块未参与本批冻结截图的数值判定。

## 验证

```bash
python -m unittest discover -s backend/tests -p test_visual_measurement.py -v
```

11项Python测量测试覆盖色值噪声、透明度、渐变、纯色局部取样、多个条带、水平识别、接触/重叠/反向坐标、尺寸校准和会场关联校验。另有 `test_venue_reaudit.py` 的7项复核测试，确保工具不会消除缺失的尺寸校准、规范冲突、原生导航证据及未就绪状态，并验证异常提示不会被误归为设计高度问题。

网页验证通过 `scripts/tests/web_visual_probe.test.mjs` 的 `validateWebVisual(page)` 执行，使用代理拥有的Ego Lite Page，包含17个断言：已知字体色、白色背景、12px圆角、24CSS像素间隔、未校准状态、隐藏/透明/屏外/部分显示、子元素显式可见、祖先位移、重复/缺失/错误选择器、反向目标和不相交目标。测试结果保存在 `data/tasks/visual-measurement-20261010/web-probe-validation.json`。
