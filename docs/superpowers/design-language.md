# 竞品分析平台设计语言

**项目**: ai-taobao-app  
**用途**: 记录当前前端的视觉特征、交互动效和可迁移设计规则  
**适用场景**: 管理后台、AI 工具台、数据分析平台、轻量工作台产品  

---

## 1. 设计定位

当前项目整体风格可以概括为：

> 暗色极简科技风 + 轻量玻璃质感 + 紫色 AI 强调色 + 微动效反馈

这套设计不追求强装饰和营销感，而是强调长时间使用时的克制、稳定和信息可读性。页面更接近 Apple / OpenAI 式的极简工具台，而不是传统电商大促风。

核心原则：

1. 暗色背景承载主体内容。
2. 半透明卡片区分信息层级。
3. 紫色只用于关键操作和当前状态。
4. hover 反馈轻，不做夸张动画。
5. 表格、表单、报告区都以扫描效率优先。

---

## 2. 配色方案

### 2.1 基础色

```css
--bg-primary: #000000;
--bg-secondary: #0d0d0d;
--bg-tertiary: #1a1a1a;
--bg-card: rgba(255, 255, 255, 0.04);
--bg-card-hover: rgba(255, 255, 255, 0.08);
--bg-input: rgba(255, 255, 255, 0.06);
--bg-input-focus: rgba(255, 255, 255, 0.1);
```

使用规则：

1. 页面背景使用 `--bg-primary`。
2. 面板或弹窗背景使用 `--bg-secondary`。
3. 输入框、代码块、结构化数据容器使用 `--bg-tertiary` 或半透明白。
4. 卡片默认使用 `--bg-card`，hover 使用 `--bg-card-hover`。

### 2.2 文字色

```css
--text-primary: #ffffff;
--text-secondary: #a1a1a6;
--text-tertiary: #6e6e73;
--text-muted: #48484a;
```

使用规则：

1. 标题和关键数字使用 `--text-primary`。
2. 正文说明和表格辅助信息使用 `--text-secondary`。
3. 空状态、占位信息、弱提示使用 `--text-tertiary`。
4. 禁用和极弱信息使用 `--text-muted`。

### 2.3 强调色

```css
--accent: #a855f7;
--accent-hover: #9333ea;
--accent-light: rgba(168, 85, 247, 0.15);
--accent-glow: rgba(168, 85, 247, 0.4);
```

使用规则：

1. 主按钮使用 `--accent`。
2. 主按钮 hover 使用 `--accent-hover`。
3. 输入框 focus 外发光使用 `--accent-light`。
4. 关键按钮 hover 阴影使用 `--accent-glow`。
5. 不要大面积铺紫色，紫色只作为操作和状态信号。

### 2.4 边框与阴影

```css
--border: rgba(255, 255, 255, 0.08);
--border-hover: rgba(255, 255, 255, 0.15);

--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
--shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4);
--shadow-lg: 0 12px 40px rgba(0, 0, 0, 0.5);
```

使用规则：

1. 所有卡片默认使用轻边框。
2. hover 只增强边框亮度。
3. 阴影用于可点击卡片、弹窗、浮层，不用于普通页面分区。

---

## 3. 圆角与布局

```css
--radius-sm: 8px;
--radius-md: 12px;
--radius-lg: 16px;
--radius-xl: 24px;
--radius-pill: 9999px;
```

使用规则：

1. 按钮和 badge 使用胶囊圆角 `--radius-pill`。
2. 输入框使用 `--radius-md`。
3. 卡片和表单容器使用 `--radius-lg`。
4. 图片详情弹窗可使用 `--radius-lg`。
5. 不要在页面大区块里套多层卡片，避免厚重。

布局规则：

1. 主容器最大宽度为 `1200px`。
2. 普通页面左右留白 `24px`，移动端 `16px`。
3. 表单类页面控制在 `640px` 到 `860px`。
4. 管理页表格和详情页可用全宽容器。

---

## 4. 页面切换与入场动效

项目使用轻量 CSS 动画，不使用复杂路由转场。

### 4.1 页面淡入

```css
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-fade-in {
  animation: fadeIn 0.5s ease forwards;
}
```

适用场景：

1. 页面主容器。
2. 搜索结果区域。
3. 提交成功提示。

### 4.2 卡片缩放进入

```css
@keyframes fadeInScale {
  from { opacity: 0; transform: scale(0.96); }
  to { opacity: 1; transform: scale(1); }
}

.animate-fade-in-scale {
  animation: fadeInScale 0.4s ease forwards;
}
```

适用场景：

1. 首页表单卡片。
2. 数据看板统计卡片。
3. 需要强调“加载后出现”的主要操作面板。

---

## 5. 按钮设计

### 5.1 主按钮

视觉特征：

1. 胶囊圆角。
2. 紫色背景。
3. hover 时轻微上浮。
4. hover 时出现紫色柔光。
5. disabled 降低透明度并取消动效。

```css
button {
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: #fff;
  transition: all var(--transition-fast);
}

button:hover {
  background: var(--accent-hover);
  transform: translateY(-1px);
  box-shadow: 0 4px 16px var(--accent-glow);
}
```

### 5.2 次级按钮

视觉特征：

1. 半透明卡片背景。
2. 轻边框。
3. hover 时背景和边框变亮。
4. 不使用明显光晕。

适用场景：

1. 刷新。
2. 返回。
3. 暂停/恢复。
4. 非主流程操作。

### 5.3 链接按钮

项目将部分 `<Link>` 样式统一成 `.link-button`，使路由跳转和普通按钮视觉一致。

适用场景：

1. 查看详情。
2. 返回列表。
3. 新建观察。

---

## 6. 卡片与 hover 态

### 6.1 普通卡片

默认：

1. 半透明背景。
2. 轻边框。
3. 16px 圆角。
4. 24px 内边距。

hover：

1. 背景从 `rgba(255,255,255,0.04)` 提升到 `rgba(255,255,255,0.08)`。
2. 边框从 `--border` 提升到 `--border-hover`。
3. 上浮 `translateY(-2px)`。
4. 添加中等阴影。

适用场景：

1. 数据统计卡片。
2. 报告面板。
3. 普通信息卡片。

### 6.2 截图卡片

交互特征：

1. 整卡可点击。
2. hover 时卡片上浮 `translateY(-4px)`。
3. 图片内部轻微放大 `scale(1.03)`。
4. 卡片右上角显示分析状态 badge。

适用场景：

1. 截图结果。
2. 观察快照。
3. 可预览素材。

---

## 7. 导航栏

顶部导航使用 sticky 毛玻璃效果。

视觉特征：

```css
position: sticky;
top: 0;
z-index: 100;
background: rgba(0, 0, 0, 0.65);
backdrop-filter: blur(20px) saturate(180%);
border-bottom: 1px solid rgba(255,255,255,0.06);
```

交互特征：

1. 当前导航项使用半透明白底高亮。
2. 非当前导航项为灰色文字。
3. hover 时文字变白。
4. 导航项不做强动效。

适用场景：

1. 后台管理系统。
2. AI 工具控制台。
3. 多模块数据平台。

---

## 8. 表单设计

输入框视觉：

1. 深色半透明背景。
2. 轻边框。
3. 12px 圆角。
4. placeholder 使用弱灰色。

focus 态：

```css
input:focus,
textarea:focus,
select:focus {
  border-color: var(--accent);
  background: var(--bg-input-focus);
  box-shadow: 0 0 0 3px var(--accent-light);
}
```

表单布局：

1. 单列时字段间距约 `20px` 到 `22px`。
2. 双列字段使用 `grid-template-columns: repeat(2, minmax(0, 1fr))`。
3. 移动端回落为单列。
4. 主提交按钮靠左或靠右都可以，但同一页面内保持一致。

---

## 9. 表格设计

表格视觉特征：

1. 无重边框。
2. 行分隔线使用 `--border`。
3. 表头小字号、灰色、字重 500。
4. 行 hover 背景轻微变亮。
5. 长文本使用 ellipsis。

适用场景：

1. 任务管理。
2. 需求管理。
3. 持续观察历史运行。
4. 后台数据列表。

设计目标：

1. 信息密度比卡片更高。
2. 适合快速扫描。
3. 操作按钮集中在右侧。

---

## 10. 状态标签

状态标签使用 `.badge`。

视觉特征：

1. 胶囊形。
2. 左侧小圆点。
3. 低透明度背景。
4. 颜色表达状态，不使用大面积强色。

状态颜色：

```css
.badge-pending {
  background: rgba(255, 204, 0, 0.12);
  color: #ffcc00;
}

.badge-running {
  background: rgba(10, 132, 255, 0.12);
  color: #0a84ff;
}

.badge-completed {
  background: rgba(175, 175, 180, 0.12);
  color: #afafb2;
}

.badge-rejected {
  background: rgba(255, 69, 58, 0.12);
  color: #ff453a;
}
```

---

## 11. 弹窗与图片预览

图片详情弹窗特征：

1. 使用 `position: fixed` 覆盖视窗。
2. 黑色半透明遮罩。
3. 弹窗居中。
4. 左侧展示完整图片。
5. 右侧展示设计分析和运营分析。
6. 图片使用 `object-fit: contain`。
7. 内容超出时内部滚动。

适用场景：

1. 截图详情。
2. 图片分析详情。
3. 素材预览。
4. 报告详情。

---

## 12. 结构化内容展示

持续观察详情页中，原始 JSON 不直接展示给用户，而是转为中文结构化块。

映射示例：

| 原字段 | 展示文案 |
|--------|----------|
| `added` | 新增内容 |
| `removed` | 消失内容 |
| `strengthened` | 强化内容 |
| `weakened` | 弱化内容 |
| `continuous_actions` | 持续动作 |
| `key_changes` | 关键变化 |
| `stable_modules` | 稳定模块 |
| `short_term_campaigns` | 短期活动 |
| `design_takeaways` | 设计启示 |
| `ops_takeaways` | 运营启示 |

展示规则：

1. 对象字段转为中文小标题。
2. 字符串数组转为标签列表。
3. 嵌套对象转为小卡片。
4. 空数组和空对象显示“暂无”。
5. 布尔值显示“是/否”。

适用场景：

1. 周期报告。
2. 与昨日相比。
3. LLM 结构化输出。
4. 趋势分析字段。

---

## 13. Tab 设计

首页“竞品搜集 / 持续观察”使用轻量 segmented control。

视觉特征：

1. 外层是胶囊形半透明容器。
2. 内部两列等宽。
3. 当前 tab 使用紫色背景。
4. 非当前 tab 使用灰色文字。
5. hover 只轻微提亮背景。

适用场景：

1. 同一页面内切换两个互斥表单。
2. 切换报告视角。
3. 切换图片/分析内容。

---

## 14. 迁移清单

迁移到其他项目时，建议优先复制以下部分：

1. CSS 变量：颜色、圆角、阴影、transition。
2. 全局 reset、字体、滚动条。
3. 按钮样式：主按钮、次级按钮、链接按钮。
4. 输入框 focus 样式。
5. 卡片和卡片 hover。
6. 表格基础样式。
7. 状态 badge。
8. 页面入场动画 `.animate-fade-in` 和 `.animate-fade-in-scale`。
9. sticky 毛玻璃导航。
10. 图片详情弹窗布局。
11. 结构化内容展示样式。
12. segmented tab 样式。

---

## 15. 迁移时的注意事项

1. 不要把紫色铺满页面，紫色只做强调色。
2. 不要引入大面积渐变背景，否则会破坏工具台气质。
3. hover 动效保持轻，不要大幅缩放或弹跳。
4. 表格页面优先保证信息密度，不要全部改成卡片流。
5. 卡片可以 hover 上浮，但普通页面 section 不要都做成浮动卡片。
6. 结构化报告不要直接展示 JSON，应转为中文标签、列表和小卡片。
7. 移动端优先保证单列布局，不要让表单字段挤压。

---

## 16. 一句话总结

这套设计语言的核心不是某个单独组件，而是一套统一规律：

> 暗底、轻边框、低透明卡片、紫色强调、轻微 hover 位移、结构化信息可读化。

迁移时保持这些规律，比逐行复制样式更重要。
