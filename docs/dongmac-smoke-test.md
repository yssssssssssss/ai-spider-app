# DongMAC API Smoke Test

这个 smoke test 验证本地项目能否完成两步 API 调用：

1. 使用 `businessName + workspaceToken` 换取一小时有效的 `accessToken`。
2. 使用 `templateId + operator` 触发一条 DongMAC 测试任务并取得任务记录 ID。

它不会伪造设备控制接口。打开页面、点击和截图必须由 DongMAC 模板关联的入口脚本或平台中预先配置的 UI_Genie 指令完成。

## 1. 准备配置

```bash
cp .env.dongmac.example .env.dongmac.local
```

填写：

- `DONGMAC_BUSINESS_NAME`
- `DONGMAC_WORKSPACE_TOKEN`
- `DONGMAC_TEMPLATE_ID`
- `DONGMAC_OPERATOR`

如果要指定设备，填写 `DONGMAC_DEVICE_SERIAL`。如果要测试任务完成回调，填写一个 DongMAC 执行环境能够访问的 `DONGMAC_CALLBACK_URL`。

## 2. 先检查请求，不调用 API

```bash
python3 scripts/dongmac_smoke_test.py \
  --template-id 123 \
  --operator 'your-erp' \
  --target-url 'https://example.com' \
  --instruction '打开指定页面，等待加载完成并截图'
```

输出中的 `workspaceToken` 永远会被隐藏。

## 3. 创建真实测试任务

官方文档中的测试域名是 HTTP。确认当前机器位于可信内网后，显式允许 HTTP：

```bash
python3 scripts/dongmac_smoke_test.py \
  --target-url 'https://example.com' \
  --instruction '打开指定页面，等待加载完成并截图' \
  --instruction-id 2049 \
  --execute \
  --allow-http
```

成功时输出 `taskRecordId`。这只表示 DongMAC 已接受任务；执行完成情况需要在 DongMAC 平台查看，或通过模板中配置的回调地址接收。

`--instruction-id` 是 DongMAC 平台中预先创建的 UI_Genie 指令 ID，可以重复传入。`--target-url` 和 `--instruction` 只是写入 `repoConfig.extraParams` 的自定义值，只有模板入口脚本明确读取这些字段时才会生效；它们不是云真机的实时控制 API。

如果平台提供 HTTPS 地址，修改 `DONGMAC_BASE_URL` 后不需要 `--allow-http`。

## 4. 流程

```text
本地脚本
  -> POST /api/v1/auth/access-token
  <- accessToken
  -> POST /api/v1/task/ci/trigger
  <- taskRecordId
  -> DongMAC 按模板选择云真机并执行入口脚本
  -> 平台页面展示结果，或任务完成后调用 callbackUrl
```

当前 API 文档没有任务状态查询和截图下载接口，因此不要在本地脚本中轮询不存在的接口。
