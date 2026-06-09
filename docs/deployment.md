# 部署信息

> 记录时间：2026-06-09

## 云服务器

- 访问地址：http://45.205.27.116:8081
- 新项目端口：8081
- 服务器已有服务端口：80、8080、7860（当前项目未占用）

## 前端

- 服务方式：Nginx 静态服务
- 入口地址：http://45.205.27.116:8081/

## 后端

- systemd 服务名：ai-taobao-backend
- 监听地址：127.0.0.1:8000

## API 反向代理

- `/api/*` 经 Nginx 转发到后端服务

## 数据库

- 数据库：PostgreSQL
- 数据库名：ai_taobao_app
- pgvector：已编译安装并启用
- pgvector 版本：0.7.4

## 本地设备 worker

- 本机托管方式：macOS LaunchAgent
- 服务名：`com.ai-spider.local-worker`
- 启动脚本：`scripts/start-local-worker.sh`
- 日志：`logs/local-worker.log`、`logs/local-worker.err.log`
- 云端地址：`http://45.205.27.116:8081`
- 节点：`local-mac-SZMAC-F7F7KPQ2`（显示名：`本地采集机`）
- 检查状态：`launchctl print gui/$(id -u)/com.ai-spider.local-worker`
- 重启：`launchctl kickstart -k gui/$(id -u)/com.ai-spider.local-worker`
