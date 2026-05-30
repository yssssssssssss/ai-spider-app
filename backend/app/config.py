import os
from pydantic_settings import BaseSettings


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Settings(BaseSettings):
    PROJECT_ROOT: str = PROJECT_ROOT
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/competitor_db"
    )
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://modelservice.jdcloud.com/v1/")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIM: int = 1536
    VLM_API_KEY: str = os.getenv("VLM_API_KEY", "")
    VLM_BASE_URL: str = os.getenv("VLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    VLM_MODEL: str = os.getenv("VLM_MODEL", "glm-4v")
    PHONE_AGENT_BASE_URL: str = os.getenv("PHONE_AGENT_BASE_URL", "")
    PHONE_AGENT_MODEL: str = os.getenv("PHONE_AGENT_MODEL", "")
    PHONE_AGENT_API_KEY: str = os.getenv("PHONE_AGENT_API_KEY", "")
    MODELSCOPE_VLM_MODEL: str = os.getenv("MODELSCOPE_VLM_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    AUTOGLM_MAX_STEPS: int = min(int(os.getenv("AUTOGLM_MAX_STEPS", "10")), 10)
    WATCH_SCHEDULER_ENABLED: bool = os.getenv("WATCH_SCHEDULER_ENABLED", "true").lower() != "false"
    WATCH_SCHEDULER_INTERVAL_SECONDS: int = int(os.getenv("WATCH_SCHEDULER_INTERVAL_SECONDS", "60"))

    # 京东云 OSS 配置
    JD_OSS_REGION: str = os.getenv("JD_OSS_REGION", "cn-south-1")
    JD_OSS_ENDPOINT: str = os.getenv("JD_OSS_ENDPOINT", "https://s3.cn-south-1.jdcloud-oss.com")
    JD_OSS_BUCKET: str = os.getenv("JD_OSS_BUCKET", "cia")
    JD_OSS_ACCESS_KEY_ID: str = os.getenv("JD_OSS_ACCESS_KEY_ID", "")
    JD_OSS_SECRET_ACCESS_KEY: str = os.getenv("JD_OSS_SECRET_ACCESS_KEY", "")
    JD_OSS_UPLOAD_PREFIX: str = os.getenv("JD_OSS_UPLOAD_PREFIX", "uploads")
    JD_OSS_VERIFY_UPLOAD: bool = os.getenv("JD_OSS_VERIFY_UPLOAD", "true").lower() != "false"

    class Config:
        env_file = (
            os.path.join(PROJECT_ROOT, ".env"),
            os.path.join(PROJECT_ROOT, "backend", ".env"),
        )
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
