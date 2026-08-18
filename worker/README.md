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

## 不应通过 Git 迁移的内容

以下目录和文件应在新电脑重新生成或单独备份：

- `.venv-worker/`
- `.env.worker.local`
- `worker_runs/`
- `logs/`
- `*.pid`

历史业务截图应以云端数据库和 OSS 为准；只有需要保留本地调试现场时，才单独备份 `worker_runs/`。
