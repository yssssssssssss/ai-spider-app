import os
from pydantic import ConfigDict
from pydantic_settings import BaseSettings


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=(
            os.path.join(PROJECT_ROOT, "backend", ".env"),
            os.path.join(PROJECT_ROOT, ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_ROOT: str = PROJECT_ROOT
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/competitor_db"
    )
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://modelservice.jdcloud.com/v1/")
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
    EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "0"))
    AI_MATCH_TEXT_EMBEDDING_PROFILE: str = os.getenv("AI_MATCH_TEXT_EMBEDDING_PROFILE", "")
    AI_MATCH_TEXT_EMBEDDING_ENDPOINT: str = os.getenv("AI_MATCH_TEXT_EMBEDDING_ENDPOINT", "")
    AI_MATCH_TEXT_EMBEDDING_API_KEY: str = os.getenv("AI_MATCH_TEXT_EMBEDDING_API_KEY", "")
    AI_MATCH_TEXT_EMBEDDING_MODEL: str = os.getenv("AI_MATCH_TEXT_EMBEDDING_MODEL", "")
    AI_MATCH_TEXT_VECTOR_DIMENSION: int = int(os.getenv("AI_MATCH_TEXT_VECTOR_DIMENSION", "0"))
    AI_MATCH_DOUBAO_EMBEDDING_ENDPOINT: str = os.getenv("AI_MATCH_DOUBAO_EMBEDDING_ENDPOINT", "")
    AI_MATCH_DOUBAO_EMBEDDING_API_KEY: str = os.getenv("AI_MATCH_DOUBAO_EMBEDDING_API_KEY", "")
    AI_MATCH_DOUBAO_EMBEDDING_MODEL: str = os.getenv("AI_MATCH_DOUBAO_EMBEDDING_MODEL", "")
    AI_MATCH_DOUBAO_VECTOR_DIMENSION: int = int(os.getenv("AI_MATCH_DOUBAO_VECTOR_DIMENSION", "0"))
    AI_MATCH_DOUBAO_SEND_DIMENSIONS: int = int(os.getenv("AI_MATCH_DOUBAO_SEND_DIMENSIONS", "0"))
    AI_MATCH_DOUBAO_EMBEDDING_FORMAT: str = os.getenv("AI_MATCH_DOUBAO_EMBEDDING_FORMAT", "")
    VLM_API_KEY: str = os.getenv("VLM_API_KEY", "")
    VLM_BASE_URL: str = os.getenv("VLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    VLM_MODEL: str = os.getenv("VLM_MODEL", "glm-4v")
    PHONE_AGENT_BASE_URL: str = os.getenv("PHONE_AGENT_BASE_URL", "")
    PHONE_AGENT_MODEL: str = os.getenv("PHONE_AGENT_MODEL", "")
    PHONE_AGENT_API_KEY: str = os.getenv("PHONE_AGENT_API_KEY", "")
    MODELSCOPE_VLM_MODEL: str = os.getenv("MODELSCOPE_VLM_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    AUTOGLM_MAX_STEPS: int = min(int(os.getenv("AUTOGLM_MAX_STEPS", "30")), 30)
    WATCH_SCHEDULER_ENABLED: bool = os.getenv("WATCH_SCHEDULER_ENABLED", "true").lower() != "false"
    WATCH_SCHEDULER_INTERVAL_SECONDS: int = int(os.getenv("WATCH_SCHEDULER_INTERVAL_SECONDS", "60"))
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-only-change-me")
    JWT_EXPIRES_MINUTES: int = int(os.getenv("JWT_EXPIRES_MINUTES", "120"))
    AUTH_DEFAULT_ADMIN_USERNAME: str = os.getenv("AUTH_DEFAULT_ADMIN_USERNAME", "admin")
    AUTH_DEFAULT_ADMIN_PASSWORD: str = os.getenv("AUTH_DEFAULT_ADMIN_PASSWORD", "admin123456")
    AUTH_DEFAULT_ADMIN_DISPLAY_NAME: str = os.getenv("AUTH_DEFAULT_ADMIN_DISPLAY_NAME", "管理员")
    AUTH_REGISTRATION_INVITE_CODE: str = os.getenv("AUTH_REGISTRATION_INVITE_CODE", "1234")
    TASK_MAX_RETRIES: int = int(os.getenv("TASK_MAX_RETRIES", "3"))
    WORKER_API_TOKEN: str = os.getenv("WORKER_API_TOKEN", "")

    # 京东云 OSS 配置
    JD_OSS_REGION: str = os.getenv("JD_OSS_REGION", "cn-south-1")
    JD_OSS_ENDPOINT: str = os.getenv("JD_OSS_ENDPOINT", "https://s3.cn-south-1.jdcloud-oss.com")
    JD_OSS_BUCKET: str = os.getenv("JD_OSS_BUCKET", "cia")
    JD_OSS_ACCESS_KEY_ID: str = os.getenv("JD_OSS_ACCESS_KEY_ID", "")
    JD_OSS_SECRET_ACCESS_KEY: str = os.getenv("JD_OSS_SECRET_ACCESS_KEY", "")
    JD_OSS_UPLOAD_PREFIX: str = os.getenv("JD_OSS_UPLOAD_PREFIX", "uploads")
    JD_OSS_VERIFY_UPLOAD: bool = os.getenv("JD_OSS_VERIFY_UPLOAD", "true").lower() != "false"

    def use_doubao_embedding(self) -> bool:
        return self.AI_MATCH_TEXT_EMBEDDING_PROFILE.lower() == "doubao"

    def use_doubao_multimodal_embedding(self) -> bool:
        return self.AI_MATCH_DOUBAO_EMBEDDING_FORMAT.lower() == "doubao-multimodal"

    def effective_embedding_dim(self) -> int:
        if self.use_doubao_embedding():
            return self.AI_MATCH_DOUBAO_VECTOR_DIMENSION or 2048
        return self.EMBEDDING_DIM or self.AI_MATCH_TEXT_VECTOR_DIMENSION or 1536


settings = Settings()
