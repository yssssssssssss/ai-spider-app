# @jdc/oss-storage

基于京东云 OSS（兼容 S3 协议）的通用图床封装模块，支持多场景上传、预签名 URL、文件删除等功能。

## 安装

```bash
npm install @jdc/oss-storage
# 或
pnpm add @jdc/oss-storage
```

依赖要求：
- `@nestjs/common` ^10.0.0
- `@aws-sdk/client-s3` ^3.0.0
- `@aws-sdk/s3-request-presigner` ^3.0.0

## 快速开始

### 1. 配置环境变量

```bash
JD_OSS_REGION=cn-south-1
JD_OSS_ENDPOINT=https://s3.cn-south-1.jdcloud-oss.com
JD_OSS_BUCKET=your-bucket-name
JD_OSS_ACCESS_KEY_ID=your-access-key
JD_OSS_SECRET_ACCESS_KEY=your-secret-key
JD_OSS_UPLOAD_PREFIX=uploads
```

### 2. 注册模块

```typescript
import { Module } from '@nestjs/common';
import { OssStorageModule } from '@jdc/oss-storage';

@Module({
  imports: [OssStorageModule.register()],
})
export class AppModule {}
```

### 3. 在 Controller 中使用

```typescript
import { Controller, Post, UploadedFile, UseInterceptors } from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { OssStorageService } from '@jdc/oss-storage';

@Controller('uploads')
export class UploadController {
  constructor(private readonly oss: OssStorageService) {}

  @Post('work-cover')
  @UseInterceptors(FileInterceptor('file'))
  async uploadCover(@UploadedFile() file: Express.Multer.File) {
    const result = await this.oss.upload('work-cover', {
      buffer: file.buffer,
      originalname: file.originalname,
      mimetype: file.mimetype,
      size: file.size,
    });
    return result; // { key, url }
  }
}
```

## 功能特性

### 多场景上传

内置 4 种默认场景，也支持自定义：

| 场景名 | 用途 | 限制 |
|---|---|---|
| `work-cover` | 作品封面 | jpg/png/webp, 10MB |
| `avatar` | 用户头像 | jpg/png/webp, 2MB |
| `attachment` | 文档附件 | pdf/txt/json/image, 50MB |
| `editor-image` | 编辑器图片 | jpg/png/webp/gif, 5MB |

### 自定义场景

```typescript
OssStorageModule.register({
  scenarios: {
    'product-image': {
      name: 'product-images',
      prefix: 'assets',
      allowedMimeTypes: ['image/webp', 'image/avif'],
      maxFileSize: 5 * 1024 * 1024,
      isPublic: true,
    },
  },
})
```

### 预签名 URL（私有访问）

```typescript
// 生成临时访问链接（默认 1 小时有效）
const url = await this.oss.getPresignedUrl({ key: 'uploads/xxx.jpg' });

// 生成前端直传链接
const putUrl = await this.oss.getPresignedUrl({
  key: 'uploads/xxx.jpg',
  method: 'PUT',
  expiresIn: 300, // 5 分钟
});
```

### 文件删除

```typescript
await this.oss.delete('uploads/avatars/xxx.jpg');
```

### 手动配置（不使用环境变量）

```typescript
OssStorageModule.register({
  ossConfig: {
    region: 'cn-south-1',
    endpoint: 'https://s3.cn-south-1.jdcloud-oss.com',
    bucket: 'my-bucket',
    accessKeyId: 'xxx',
    secretAccessKey: 'xxx',
    uploadPrefix: 'assets',
  },
})
```

## API 文档

### OssStorageService

| 方法 | 说明 |
|---|---|
| `upload(scenario, input)` | 上传文件到指定场景 |
| `delete(key)` | 删除 OSS 对象 |
| `getPresignedUrl(options)` | 获取预签名 URL |
| `validate(scenario, input)` | 校验文件是否符合场景要求 |
| `getScenario(name)` | 获取场景配置 |
| `getScenarioNames()` | 列出所有场景名称 |
| `buildUrl(key)` | 根据 key 构建公开访问 URL |

## 迁移指南：从 jd-oss.service.ts 升级

原 `JdOssService` 可替换为 `OssStorageService`：

```typescript
// 旧代码
const result = await this.jdOssService.uploadWorkCover(file);

// 新代码
const result = await this.ossStorageService.upload('work-cover', file);
```

上传接口 Controller 无需改动，只需替换注入的服务即可。

## 兼容性

本模块使用 AWS S3 SDK，因此兼容所有支持 S3 协议的对象存储：
- 京东云 OSS
- 阿里云 OSS
- 腾讯云 COS
- MinIO
- AWS S3

切换厂商时只需修改 `endpoint` 和 `region` 即可。
