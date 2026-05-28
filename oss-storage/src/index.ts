// ========================
//  通用图床模块 - 入口导出
// ========================

// 核心服务与模块
export { OssStorageModule } from './oss.module';
export { OssStorageService } from './oss.service';

// 工具函数与预设场景
export {
  buildPublicUrl,
  defaultScenarios,
  extractFileMetadata,
  generateObjectKey,
  getExtensionByMimeType,
  validateUpload,
} from './utils';

// 配置加载
export { createOssConfig, loadOssConfigFromEnv } from './config';

// 类型定义
export type {
  FileMetadata,
  OssConnectionConfig,
  OssEnvConfig,
  OssStorageModuleOptions,
  PresignedUrlOptions,
  UploadFileInput,
  UploadScenario,
  UploadedAsset,
  ValidationResult,
} from './types';
