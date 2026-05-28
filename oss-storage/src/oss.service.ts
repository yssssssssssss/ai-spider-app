// ========================
//  通用图床模块 - 核心服务
// ========================

import { Injectable, InternalServerErrorException } from '@nestjs/common';
import { DeleteObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import type {
  OssConnectionConfig,
  PresignedUrlOptions,
  UploadFileInput,
  UploadScenario,
  UploadedAsset,
  ValidationResult,
} from './types';
import {
  buildPublicUrl,
  generateObjectKey,
  validateUpload,
} from './utils';

@Injectable()
export class OssStorageService {
  private client: S3Client | null = null;

  constructor(
    private readonly config: OssConnectionConfig & { uploadPrefix: string },
    private readonly scenarios: Record<string, UploadScenario>,
    private readonly skipUploadInTest = true,
  ) {}

  /**
   * 通用文件上传
   * @param scenarioName 上传场景名称
   * @param input 文件输入
   * @returns 上传结果 { key, url }
   */
  async upload(scenarioName: string, input: UploadFileInput): Promise<UploadedAsset> {
    const scenario = this.scenarios[scenarioName];
    if (!scenario) {
      throw new InternalServerErrorException(`未知的上传场景: ${scenarioName}`);
    }

    const validation = validateUpload(input, scenario);
    if (!validation.valid) {
      throw new InternalServerErrorException(validation.error);
    }

    const key = generateObjectKey(
      this.config.uploadPrefix,
      scenario.name,
      input.originalname,
      input.mimetype,
    );

    const url = buildPublicUrl(this.config.endpoint, this.config.bucket, key);

    // 测试环境可选择跳过实际上传
    if (this.skipUploadInTest && process.env.NODE_ENV === 'test') {
      return { key, url };
    }

    await this.getClient().send(
      new PutObjectCommand({
        Bucket: this.config.bucket,
        Key: key,
        Body: input.buffer,
        ContentType: input.mimetype,
      }),
    );

    return { key, url };
  }

  /**
   * 删除 OSS 对象
   * @param key 对象键（路径）
   */
  async delete(key: string): Promise<void> {
    if (this.skipUploadInTest && process.env.NODE_ENV === 'test') {
      return;
    }

    await this.getClient().send(
      new DeleteObjectCommand({
        Bucket: this.config.bucket,
        Key: key,
      }),
    );
  }

  /**
   * 获取预签名 URL（用于私有文件临时访问或前端直传）
   * @param options 预签名配置
   * @returns 预签名 URL 字符串
   */
  async getPresignedUrl(options: PresignedUrlOptions): Promise<string> {
    const command =
      options.method === 'PUT'
        ? new PutObjectCommand({
            Bucket: this.config.bucket,
            Key: options.key,
          })
        : new DeleteObjectCommand({
            Bucket: this.config.bucket,
            Key: options.key,
          });

    return getSignedUrl(this.getClient(), command as any, {
      expiresIn: options.expiresIn || 3600,
    });
  }

  /**
   * 校验文件是否符合指定场景的上传要求
   * @param scenarioName 场景名称
   * @param input 文件输入
   * @returns 校验结果
   */
  validate(scenarioName: string, input: UploadFileInput): ValidationResult {
    const scenario = this.scenarios[scenarioName];
    if (!scenario) {
      return { valid: false, error: `未知的上传场景: ${scenarioName}` };
    }
    return validateUpload(input, scenario);
  }

  /**
   * 获取场景配置
   */
  getScenario(name: string): UploadScenario | undefined {
    return this.scenarios[name];
  }

  /**
   * 列出所有场景名称
   */
  getScenarioNames(): string[] {
    return Object.keys(this.scenarios);
  }

  /**
   * 构建公开访问 URL（如果已知 key）
   */
  buildUrl(key: string): string {
    return buildPublicUrl(this.config.endpoint, this.config.bucket, key);
  }

  /**
   * 获取 S3 客户端（延迟初始化 + 单例）
   */
  private getClient(): S3Client {
    if (!this.client) {
      this.client = new S3Client({
        region: this.config.region,
        endpoint: this.config.endpoint,
        forcePathStyle: true,
        credentials: {
          accessKeyId: this.config.accessKeyId,
          secretAccessKey: this.config.secretAccessKey,
        },
      });
    }
    return this.client;
  }
}
