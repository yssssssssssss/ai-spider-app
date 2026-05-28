// ========================
//  通用图床模块 - 类型定义
// ========================

/**
 * 上传场景配置，用于区分不同业务类型的上传路径和限制
 */
export interface UploadScenario {
  /** 场景标识，如 'work-cover', 'avatar', 'attachment' */
  name: string;
  /** 存储路径前缀 */
  prefix: string;
  /** 允许的文件类型 */
  allowedMimeTypes: string[];
  /** 最大文件大小（字节） */
  maxFileSize: number;
  /** 是否公开可访问 */
  isPublic: boolean;
}

/**
 * 文件上传输入参数
 */
export interface UploadFileInput {
  /** 文件二进制内容 */
  buffer: Buffer;
  /** 原始文件名 */
  originalname: string;
  /** MIME 类型 */
  mimetype: string;
  /** 文件大小（字节） */
  size: number;
}

/**
 * 上传成功后的返回结果
 */
export interface UploadedAsset {
  /** OSS 对象键（路径） */
  key: string;
  /** 公开访问 URL */
  url: string;
}

/**
 * 预签名 URL 配置
 */
export interface PresignedUrlOptions {
  /** 对象键 */
  key: string;
  /** 过期时间（秒），默认 3600 */
  expiresIn?: number;
  /** HTTP 方法，默认 GET */
  method?: 'GET' | 'PUT';
}

/**
 * OSS 连接配置
 */
export interface OssConnectionConfig {
  /** 区域，如 cn-south-1 */
  region: string;
  /** 端点，如 https://s3.cn-south-1.jdcloud-oss.com */
  endpoint: string;
  /** Bucket 名称 */
  bucket: string;
  /** Access Key ID */
  accessKeyId: string;
  /** Secret Access Key */
  secretAccessKey: string;
}

/**
 * 上传校验结果
 */
export interface ValidationResult {
  valid: boolean;
  error?: string;
}

/**
 * 文件元信息
 */
export interface FileMetadata {
  originalName: string;
  mimetype: string;
  size: number;
  extension: string;
  scenario: string;
}
