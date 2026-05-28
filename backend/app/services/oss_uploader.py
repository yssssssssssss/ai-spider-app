#!/usr/bin/env python3
"""
京东云 OSS 上传服务
兼容 AWS S3 API，使用 boto3 客户端
"""
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import settings


# 默认上传场景配置
DEFAULT_SCENARIOS = {
    "screenshot": {
        "name": "screenshots",
        "prefix": "uploads",
        "allowed_mime_types": ["image/png", "image/jpeg", "image/webp"],
        "max_file_size": 20 * 1024 * 1024,  # 20MB
        "is_public": True,
    },
    "cropped": {
        "name": "cropped",
        "prefix": "uploads",
        "allowed_mime_types": ["image/png", "image/jpeg", "image/webp"],
        "max_file_size": 10 * 1024 * 1024,  # 10MB
        "is_public": True,
    },
    "analysis": {
        "name": "analysis",
        "prefix": "uploads",
        "allowed_mime_types": ["image/png", "image/jpeg", "image/webp", "application/json"],
        "max_file_size": 50 * 1024 * 1024,  # 50MB
        "is_public": True,
    },
}


class OssUploader:
    """京东云 OSS 上传器"""

    def __init__(
        self,
        region: Optional[str] = None,
        endpoint: Optional[str] = None,
        bucket: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        upload_prefix: Optional[str] = None,
        scenarios: Optional[dict] = None,
    ):
        self.region = region or settings.JD_OSS_REGION
        self.endpoint = (endpoint or settings.JD_OSS_ENDPOINT).rstrip("/")
        self.bucket = bucket or settings.JD_OSS_BUCKET
        self.access_key_id = access_key_id or settings.JD_OSS_ACCESS_KEY_ID
        self.secret_access_key = secret_access_key or settings.JD_OSS_SECRET_ACCESS_KEY
        self.upload_prefix = (upload_prefix or settings.JD_OSS_UPLOAD_PREFIX).strip("/")
        self.scenarios = scenarios or DEFAULT_SCENARIOS
        self.verify_upload = settings.JD_OSS_VERIFY_UPLOAD
        self._client = None

    def _get_client(self):
        """获取 S3 客户端（延迟初始化 + 单例）"""
        if self._client is None:
            if not all([self.access_key_id, self.secret_access_key]):
                raise ValueError(
                    "京东云 OSS 认证信息不完整，请设置环境变量:\n"
                    "  JD_OSS_ACCESS_KEY_ID\n"
                    "  JD_OSS_SECRET_ACCESS_KEY"
                )
            self._client = boto3.client(
                "s3",
                region_name=self.region,
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=BotoConfig(s3={"addressing_style": "path"}),
            )
        return self._client

    def _validate_upload(self, file_path: str, scenario_name: str) -> tuple[bool, Optional[str]]:
        """校验文件是否符合场景要求"""
        scenario = self.scenarios.get(scenario_name)
        if not scenario:
            return False, f"未知的上传场景: {scenario_name}"

        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size > scenario["max_file_size"]:
            max_mb = scenario["max_file_size"] / 1024 / 1024
            actual_mb = file_size / 1024 / 1024
            return False, f"文件过大: {actual_mb:.1f}MB，最大允许: {max_mb:.1f}MB"

        # 检查 MIME 类型（简单通过扩展名判断）
        import mimetypes

        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type and not any(
            mime_type == allowed or (allowed.endswith("/*") and mime_type.startswith(allowed[:-1]))
            for allowed in scenario["allowed_mime_types"]
        ):
            return False, f"不支持的文件类型: {mime_type}，仅允许: {', '.join(scenario['allowed_mime_types'])}"

        return True, None

    def _generate_object_key(self, scenario_name: str, original_name: str) -> str:
        """生成 OSS 对象存储键（路径）"""
        scenario = self.scenarios.get(scenario_name, DEFAULT_SCENARIOS["screenshot"])
        ext = Path(original_name).suffix.lower() or ".png"

        # 清理文件名：只保留字母、数字、下划线、连字符
        basename = Path(original_name).stem
        basename = basename.lower()
        basename = re.sub(r"[^a-z0-9_-]+", "-", basename)
        basename = basename.strip("-") or "file"

        timestamp = int(datetime.now().timestamp() * 1000)
        unique_id = uuid.uuid4().hex[:8]

        return f"{self.upload_prefix}/{scenario['name']}/{timestamp}-{unique_id}-{basename}{ext}"

    def _build_public_url(self, key: str) -> str:
        """构建公开访问 URL"""
        # 对 key 中的每个路径段进行 URL 编码
        encoded_key = "/".join(
            quote(segment, safe="") for segment in key.split("/")
        )
        return f"{self.endpoint}/{self.bucket}/{encoded_key}"

    def _verify_object_exists(self, key: str) -> tuple[bool, Optional[str]]:
        if not self.verify_upload:
            return True, None
        try:
            self._get_client().head_object(Bucket=self.bucket, Key=key)
            return True, None
        except ClientError as e:
            return False, f"OSS 上传后校验失败: {e}"

    def upload(
        self,
        file_path: str,
        scenario_name: str = "screenshot",
        object_key: Optional[str] = None,
    ) -> dict:
        """
        上传文件到京东云 OSS

        Args:
            file_path: 本地文件路径
            scenario_name: 上传场景名称
            object_key: 自定义对象键（可选）

        Returns:
            {"key": str, "url": str, "success": bool, "error": Optional[str]}
        """
        if not os.path.exists(file_path):
            return {"key": "", "url": "", "success": False, "error": f"文件不存在: {file_path}"}

        # 校验
        valid, error = self._validate_upload(file_path, scenario_name)
        if not valid:
            return {"key": "", "url": "", "success": False, "error": error}

        # 生成对象键
        if not object_key:
            object_key = self._generate_object_key(scenario_name, os.path.basename(file_path))

        url = self._build_public_url(object_key)

        try:
            # 推断 Content-Type
            import mimetypes
            content_type, _ = mimetypes.guess_type(file_path)
            content_type = content_type or "application/octet-stream"

            self._get_client().upload_file(
                file_path,
                self.bucket,
                object_key,
                ExtraArgs={"ContentType": content_type},
            )
            verified, verify_error = self._verify_object_exists(object_key)
            if not verified:
                print(f"  ⚠️ {verify_error}")
                return {"key": object_key, "url": "", "success": False, "error": verify_error}

            print(f"  ☁️  已上传 OSS: {object_key}")
            return {"key": object_key, "url": url, "success": True, "error": None}

        except ClientError as e:
            error_msg = f"OSS 上传失败: {e}"
            print(f"  ⚠️ {error_msg}")
            return {"key": object_key, "url": url, "success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"上传异常: {e}"
            print(f"  ⚠️ {error_msg}")
            return {"key": object_key, "url": url, "success": False, "error": error_msg}

    def delete(self, object_key: str) -> bool:
        """删除 OSS 对象"""
        try:
            self._get_client().delete_object(Bucket=self.bucket, Key=object_key)
            print(f"  🗑️  已删除 OSS: {object_key}")
            return True
        except ClientError as e:
            print(f"  ⚠️ 删除失败: {e}")
            return False

    def upload_bytes(
        self,
        data: bytes,
        filename: str,
        scenario_name: str = "screenshot",
        object_key: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> dict:
        """直接上传字节数据到 OSS"""
        import tempfile

        # 写入临时文件后上传
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            result = self.upload(tmp_path, scenario_name, object_key)
            return result
        finally:
            os.unlink(tmp_path)


# 全局单例
oss_uploader = OssUploader()
