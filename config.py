import os
from pathlib import Path

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal env
    load_dotenv = None

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


def _as_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    dashscope_api_key: str = Field(alias="DASHSCOPE_API_KEY")
    dashscope_base_url: str = Field(alias="DASHSCOPE_BASE_URL")
    model_name: str = Field(default="deepseek-v4-pro", alias="MODEL_NAME")
    request_timeout: float = Field(default=180.0, alias="REQUEST_TIMEOUT")
    news_limit: int = Field(default=3, alias="NEWS_LIMIT")
    prompt_version: str = Field(default="v5", alias="PROMPT_VERSION")
    max_retries: int = Field(default=1, alias="MODEL_MAX_RETRIES")
    mock_llm: bool = Field(default=False, alias="MOCK_LLM")
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_interval_seconds: int = Field(default=1800, alias="SCHEDULER_INTERVAL_SECONDS")
    scheduler_daily_enabled: bool = Field(default=True, alias="SCHEDULER_DAILY_ENABLED")
    admin_token: str = Field(default="", alias="ADMIN_TOKEN")
    allow_test_notify: bool = Field(default=False, alias="ALLOW_TEST_NOTIFY")
    # --- 多用户体系(task #62) ---
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")  # 生产 HTTPS 须 true
    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")  # 非空才 seed 管理员
    free_daily_cents: int = Field(default=300, alias="FREE_DAILY_CENTS")  # 免费用户每日 LLM 额度(分),默认 300=3元
    session_ttl_hours: int = Field(default=720, alias="SESSION_TTL_HOURS")  # 会话有效期,默认 30 天
    enable_registration: bool = Field(default=True, alias="ENABLE_REGISTRATION")

    @classmethod
    def from_env(cls) -> "Settings":
        payload = {
            "DASHSCOPE_API_KEY": os.getenv("DASHSCOPE_API_KEY", ""),
            "DASHSCOPE_BASE_URL": os.getenv("DASHSCOPE_BASE_URL", ""),
            "MODEL_NAME": os.getenv("MODEL_NAME", "deepseek-v4-pro"),
            "REQUEST_TIMEOUT": os.getenv("REQUEST_TIMEOUT", "180"),
            "NEWS_LIMIT": os.getenv("NEWS_LIMIT", "3"),
            "PROMPT_VERSION": os.getenv("PROMPT_VERSION", "v5"),
            "MODEL_MAX_RETRIES": os.getenv("MODEL_MAX_RETRIES", "1"),
            "MOCK_LLM": _as_bool(os.getenv("MOCK_LLM")),
            "SCHEDULER_ENABLED": _as_bool(os.getenv("SCHEDULER_ENABLED", "1")),
            "SCHEDULER_INTERVAL_SECONDS": os.getenv("SCHEDULER_INTERVAL_SECONDS", "1800"),
            "SCHEDULER_DAILY_ENABLED": _as_bool(os.getenv("SCHEDULER_DAILY_ENABLED", "1")),
            "ADMIN_TOKEN": os.getenv("ADMIN_TOKEN", ""),
            "ALLOW_TEST_NOTIFY": _as_bool(os.getenv("ALLOW_TEST_NOTIFY")),
            "COOKIE_SECURE": _as_bool(os.getenv("COOKIE_SECURE")),
            "ADMIN_USERNAME": os.getenv("ADMIN_USERNAME", "admin"),
            "ADMIN_PASSWORD": os.getenv("ADMIN_PASSWORD", ""),
            "FREE_DAILY_CENTS": os.getenv("FREE_DAILY_CENTS", "300"),
            "SESSION_TTL_HOURS": os.getenv("SESSION_TTL_HOURS", "720"),
            "ENABLE_REGISTRATION": _as_bool(os.getenv("ENABLE_REGISTRATION", "1")),
        }
        settings = cls.model_validate(payload)
        if not settings.mock_llm:
            if not settings.dashscope_api_key:
                raise ValueError("请设置 DASHSCOPE_API_KEY 或开启 MOCK_LLM=1")
            if not settings.dashscope_base_url:
                raise ValueError("请设置 DASHSCOPE_BASE_URL 或开启 MOCK_LLM=1")
        return settings


settings = Settings.from_env()
