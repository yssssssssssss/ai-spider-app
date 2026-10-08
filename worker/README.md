# Local Worker

本地 Worker 运行在连接 USB/ADB 手机的电脑上，只通过 `/api/worker/*` 与云端通信，不需要数据库连接串或 OSS 密钥。

## 新电脑初始化

克隆父项目及 Open-AutoGLM Fork：

```bash
git clone --recurse-submodules https://github.com/yssssssssssss/ai-spider-app.git
cd ai-spider-app
```

已有父项目副本时初始化或更新子模块：

```bash
git submodule sync --recursive
git submodule update --init --recursive
```

创建独立虚拟环境并安装依赖：

```bash
python3 -m venv .venv-worker
.venv-worker/bin/python -m pip install -r worker/requirements.txt
```

滑动过程帧使用 `scrcpy` 录屏和 `ffmpeg` 提帧。macOS 安装：

```bash
brew install scrcpy ffmpeg
```

如果 `scrcpy` 不可用，任务会自动降级为滑动期间并发 `screencap`，但过程帧数量会明显减少。

创建本地配置。该文件被 Git 忽略，不要提交真实密钥：

```bash
cp .env.worker.example .env.worker.local
chmod 600 .env.worker.local
```

至少填写：

- `WORKER_BASE_URL`
- `WORKER_API_TOKEN`
- `WORKER_NODE_KEY`
- `PHONE_AGENT_BASE_URL`
- `PHONE_AGENT_API_KEY`
- `PHONE_AGENT_MODEL`

滑动贴片检测默认参数：

- `SCROLL_PROMO_SWIPE_COUNT=1`
- `SCROLL_PROMO_MAX_FRAMES=6`
- `SCROLL_PROMO_FPS=10`

确认本机能看到手机：

```bash
adb devices
```

设备状态必须是 `device`，不能是 `offline` 或 `unauthorized`。

## 启动

前台启动，便于首次排查：

```bash
scripts/start_local_worker.sh
```

脚本默认加载 `.env.worker.local` 并优先使用 `.venv-worker/bin/python`。也可以指定其他配置文件：

```bash
WORKER_ENV_FILE=/path/to/worker.env scripts/start_local_worker.sh
```

## 单轮调试

```bash
scripts/start_local_worker.sh --once
```

Worker 执行任务时会设置 `CAPTURE_SINK=local_files`，采集脚本只在本地保存截图；随后 Worker 将图片上传给云端，由云端统一入库、OSS 上传和分析。

Worker 默认同时声明 `uiautomator2`、`autoglm`、`scroll_promo` 和 `jd_new_floor_audit` 能力。新品楼层检查会打开京东“新品”页并关闭遮挡弹窗：先保存原始全屏截图并完成原 3.3 至 3.9“腰部楼层巡查”，再点击“新奇集市”并等待 8 秒，以红色“推荐”文字为锚点动态定位 z1；随后按手指上滑 800px（页面向下）、手指下滑 400px（页面向上回退）的顺序采集 z2/z3，并在 z1、z2 左滑 400px，最终上传 7 张截图并生成包含“腰部楼层巡查”和“二级tab组件巡查”的合并报告。

## 不应通过 Git 迁移的内容

以下目录和文件应在新电脑重新生成或单独备份：

- `.venv-worker/`
- `.env.worker.local`
- `worker_runs/`
- `logs/`
- `*.pid`

历史业务截图应以云端数据库和 OSS 为准；只有需要保留本地调试现场时，才单独备份 `worker_runs/`。
