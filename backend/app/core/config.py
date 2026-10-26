import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://blogger:blogger@localhost:5432/blogger",
    )
    secret_key: str = os.getenv("SECRET_KEY", "dev-only-change-me")
    access_key_pepper: str = os.getenv("ACCESS_KEY_PEPPER", "dev-only-access-key-pepper")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "10080"))
    allowed_origins: list[str] = None  # type: ignore[assignment]
    auto_create_tables: bool = os.getenv("AUTO_CREATE_TABLES", "true").lower() == "true"
    gcs_bucket: str | None = os.getenv("GCS_BUCKET") or None
    public_asset_base_url: str | None = os.getenv("PUBLIC_ASSET_BASE_URL") or None
    upload_prefix: str = os.getenv("UPLOAD_PREFIX", "uploads")
    translation_api_base_url: str | None = os.getenv("TRANSLATION_API_BASE_URL") or None
    translation_api_key: str | None = os.getenv("TRANSLATION_API_KEY") or None
    translation_model: str | None = os.getenv("TRANSLATION_MODEL") or None
    translation_api_mode: str = os.getenv("TRANSLATION_API_MODE", "chat_completions")
    translation_timeout_seconds: float = float(os.getenv("TRANSLATION_TIMEOUT_SECONDS", "60"))

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_origins",
            _csv(os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")),
        )


settings = Settings()
