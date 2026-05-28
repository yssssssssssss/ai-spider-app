// ========================
//  通用图床模块 - 配置管理
// ========================

import type { OssConnectionConfig, UploadScenario } from './types';

/**
 * OSS 环境变量配置映射
 */
export interface OssEnvConfig {
  region?: string;
  endpoint?: string;
  bucket?: string;
  accessKeyId?: string;
  secretAccessKey?: string;
  uploadPrefix?: string;
}

/**
 * 从环境变量读取 OSS 配置
 * 默认读取以下环境变量：
 *   - JD_OSS_REGION
 *   - JD_OSS_ENDPOINT
 *   - JD_OSS_BUCKET
 *   - JD_OSS_ACCESS_KEY_ID
 *   - JD_OSS_SECRET_ACCESS_KEY
 *   - JD_OSS_UPLOAD_PREFIX（可选，默认 'uploads'）
 */
export function loadOssConfigFromEnv(
  prefix = 'JD_OSS',
): OssConnectionConfig & { uploadPrefix: string } {
  const region = process.env[`${prefix}_REGION`] || '';
  const endpoint = (process.env[`${prefix}_ENDPOINT`] || '').replace(/\/$/, '');
  const bucket = process.env[`${prefix}_BUCKET`] || '';
  const accessKeyId = process.env[`${prefix}_ACCESS_KEY_ID`] || '';
  const secretAccessKey = process.env[`${prefix}_SECRET_ACCESS_KEY`] || '';
  const uploadPrefix = (
    process.env[`${prefix}_UPLOAD_PREFIX`] || 'uploads'
  ).replace(/^\/+|\/+/g, '');

  if (!region || !endpoint || !bucket || !accessKeyId || !secretAccessKey) {
    throw new Error(
      `OSS 配置不完整，请检查以下环境变量是否设置:\n` +
        `  ${prefix}_REGION\n` +
        `  ${prefix}_ENDPOINT\n` +
        `  ${prefix}_BUCKET\n` +
        `  ${prefix}_ACCESS_KEY_ID\n` +
        `  ${prefix}_SECRET_ACCESS_KEY`,
    );
  }

  return { region, endpoint, bucket, accessKeyId, secretAccessKey, uploadPrefix };
}

/**
 * 手动构建 OSS 配置（用于非环境变量场景）
 */
export function createOssConfig(config: OssEnvConfig): OssConnectionConfig {
  if (
    !config.region ||
    !config.endpoint ||
    !config.bucket ||
    !config.accessKeyId ||
    !config.secretAccessKey
  ) {
    throw new Error('OSS 配置字段不完整');
  }

  return {
    region: config.region,
    endpoint: config.endpoint.replace(/\/$/, ''),
    bucket: config.bucket,
    accessKeyId: config.accessKeyId,
    secretAccessKey: config.secretAccessKey,
  };
}

/**
 * 模块配置选项接口
 */
export interface OssStorageModuleOptions {
  /** OSS 连接配置 */
  ossConfig: OssConnectionConfig & { uploadPrefix?: string };
  /** 自定义上传场景，会合并到默认场景中 */
  scenarios?: Record<string, UploadScenario>;
  /** 是否在测试环境跳过实际上传 */
  skipUploadInTest?: boolean;
}
