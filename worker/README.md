# Local Worker

本地 worker 运行在连接 USB/ADB 手机的电脑上。它只通过 /api/worker/* 与云端通信，不需要数据库连接串或 OSS 密钥。

## 启动

    python3 -m pip install -r worker/requirements.txt
    export WORKER_BASE_URL="http://84222256dec64002a6bd-udapp-80.gcs-xy1a.jdcloud.com"
    export WORKER_API_TOKEN="<cloud WORKER_API_TOKEN>"
    export WORKER_NODE_KEY="macbook-local"
    python3 -m worker.main

先确认本机能看到手机：

    adb devices

## 单轮调试

    python3 -m worker.main --once

worker 执行任务时会设置 CAPTURE_SINK=local_files，采集脚本只在本地保存截图；随后 worker 把图片上传给云端，由云端统一入库、OSS 上传和分析。
