"""OperdAI application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with env var loading."""

    # Environment
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://operdai:operdai_dev_password@localhost:5432/operdai"
    database_url_sync: str = "postgresql://operdai:operdai_dev_password@localhost:5432/operdai"
    database_app_role: str = "operdai_app"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret_key: str = "change-this-to-a-random-secret-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    llm_supervisor_model: str = "claude-opus-4-8"
    llm_critic_model: str = "claude-opus-4-8"
    llm_worker_model: str = "claude-haiku-4-5"

    # Encryption
    encryption_key: str = ""

    # Rate limiting
    rate_limit_per_minute: int = 60

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": False}


settings = Settings()
