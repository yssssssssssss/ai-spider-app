// ========================
//  通用图床模块 - 工具函数
// ========================

import { randomUUID } from 'node:crypto';
import { extname } from 'node:path';
import type { FileMetadata, UploadFileInput, UploadScenario, ValidationResult } from './types';

/**
 * 根据 MIME 类型推断文件扩展名
 */
export function getExtensionByMimeType(mimetype: string): string {
  const map: Record<string, string> = {
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/gif': '.gif',
    'image/svg+xml': '.svg',
    'image/avif': '.avif',
    'application/pdf': '.pdf',
    'text/plain': '.txt',
    'application/json': '.json',
  };
  return map[mimetype] || '.bin';
}

/**
 * 提取文件元信息
 */
export function extractFileMetadata(
  input: UploadFileInput,
  scenario: UploadScenario,
): FileMetadata {
  const extension =
    extname(input.originalname).toLowerCase() ||
    getExtensionByMimeType(input.mimetype);

  return {
    originalName: input.originalname,
    mimetype: input.mimetype,
    size: input.size,
    extension,
    scenario: scenario.name,
  };
}

/**
 * 生成安全的对象存储键（路径）
 * 格式: {prefix}/{scenario-name}/{timestamp}-{uuid}-{sanitized-name}.{ext}
 */
export function generateObjectKey(
  prefix: string,
  scenarioName: string,
  originalName: string,
  mimetype: string,
): string {
  const extension =
    extname(originalName).toLowerCase() ||
    getExtensionByMimeType(mimetype);

  // 清理文件名：只保留字母、数字、下划线、连字符
  const basename = originalName
    .replace(extname(originalName), '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    || 'file';

  const safePrefix = prefix.replace(/^\/+|\/+$/g, '');
  const timestamp = Date.now();
  const uuid = randomUUID();

  return `${safePrefix}/${scenarioName}/${timestamp}-${uuid}-${basename}${extension}`;
}

/**
 * 构建公开访问 URL
 */
export function buildPublicUrl(endpoint: string, bucket: string, key: string): string {
  const cleanEndpoint = endpoint.replace(/\/$/, '');
  const encodedKey = key
    .split('/')
    .map((segment) => encodeURIComponent(segment))
    .join('/');

  return `${cleanEndpoint}/${bucket}/${encodedKey}`;
}

/**
 * 校验上传文件是否符合场景配置
 */
export function validateUpload(
  input: UploadFileInput,
  scenario: UploadScenario,
): ValidationResult {
  if (!scenario.allowedMimeTypes.includes(input.mimetype)) {
    return {
      valid: false,
      error: `不支持的文件类型: ${input.mimetype}，仅允许: ${scenario.allowedMimeTypes.join(', ')}`,
    };
  }

  if (input.size > scenario.maxFileSize) {
    const maxMB = (scenario.maxFileSize / 1024 / 1024).toFixed(1);
    const actualMB = (input.size / 1024 / 1024).toFixed(1);
    return {
      valid: false,
      error: `文件过大: ${actualMB}MB，最大允许: ${maxMB}MB`,
    };
  }

  return { valid: true };
}

/**
 * 常用上传场景预设
 */
export const defaultScenarios: Record<string, UploadScenario> = {
  // 作品封面
  'work-cover': {
    name: 'work-covers',
    prefix: 'uploads',
    allowedMimeTypes: ['image/jpeg', 'image/png', 'image/webp'],
    maxFileSize: 10 * 1024 * 1024, // 10MB
    isPublic: true,
  },
  // 用户头像
  avatar: {
    name: 'avatars',
    prefix: 'uploads',
    allowedMimeTypes: ['image/jpeg', 'image/png', 'image/webp'],
    maxFileSize: 2 * 1024 * 1024, // 2MB
    isPublic: true,
  },
  // 文档附件
  attachment: {
    name: 'attachments',
    prefix: 'uploads',
    allowedMimeTypes: [
      'application/pdf',
      'text/plain',
      'application/json',
      'image/*',
    ],
    maxFileSize: 50 * 1024 * 1024, // 50MB
    isPublic: false,
  },
  // 富文本编辑器图片
  'editor-image': {
    name: 'editor-images',
    prefix: 'uploads',
    allowedMimeTypes: ['image/jpeg', 'image/png', 'image/webp', 'image/gif'],
    maxFileSize: 5 * 1024 * 1024, // 5MB
    isPublic: true,
  },
};
