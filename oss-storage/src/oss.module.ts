// ========================
//  通用图床模块 - NestJS 模块
// ========================

import { DynamicModule, Module } from '@nestjs/common';
import type { UploadScenario } from './types';
import { loadOssConfigFromEnv } from './config';
import { OssStorageService } from './oss.service';
import { defaultScenarios } from './utils';

/**
 * 模块配置选项
 */
export interface OssStorageModuleOptions {
  /** 从环境变量读取配置时的前缀，默认 'JD_OSS' */
  envPrefix?: string;
  /** 自定义 OSS 配置（优先级高于环境变量） */
  ossConfig?: {
    region: string;
    endpoint: string;
    bucket: string;
    accessKeyId: string;
    secretAccessKey: string;
    uploadPrefix?: string;
  };
  /** 自定义上传场景，会与默认场景合并 */
  scenarios?: Record<string, UploadScenario>;
  /** 测试环境是否跳过实际上传，默认 true */
  skipUploadInTest?: boolean;
}

/**
 * 图床存储模块
 *
 * 使用方式：
 * ```ts
 * // 1. 使用环境变量默认配置
 * OssStorageModule.register({})
 *
 * // 2. 自定义配置
 * OssStorageModule.register({
 *   scenarios: { ... },
 *   skipUploadInTest: false,
 * })
 *
 * // 3. 完全手动配置（不读环境变量）
 * OssStorageModule.register({
 *   ossConfig: { region, endpoint, bucket, accessKeyId, secretAccessKey },
 * })
 * ```
 */
@Module({})
export class OssStorageModule {
  static register(options: OssStorageModuleOptions = {}): DynamicModule {
    const config = options.ossConfig
      ? {
          ...options.ossConfig,
          uploadPrefix: options.ossConfig.uploadPrefix || 'uploads',
        }
      : loadOssConfigFromEnv(options.envPrefix || 'JD_OSS');

    const scenarios = {
      ...defaultScenarios,
      ...(options.scenarios || {}),
    };

    const skipUploadInTest = options.skipUploadInTest !== false;

    return {
      module: OssStorageModule,
      providers: [
        {
          provide: OssStorageService,
          useValue: new OssStorageService(config, scenarios, skipUploadInTest),
        },
      ],
      exports: [OssStorageService],
    };
  }
}
