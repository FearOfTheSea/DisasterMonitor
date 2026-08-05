"""Environment-backed infrastructure settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration required to run the local API."""

    app_name: str = Field(default="Disaster Monitor API", min_length=1)
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    ollama_base_url: str = Field(default="http://localhost:11434", min_length=1)
    ollama_model: str = Field(default="qwen3:1.7b", min_length=1)
    ollama_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    ollama_max_tokens: int = Field(default=512, ge=32, le=4096)
    disaster_provider_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    disaster_provider_max_response_bytes: int = Field(
        default=1_000_000, ge=10_000, le=5_000_000
    )
    reliefweb_app_name: str = Field(default="disaster-monitor-local", min_length=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origins(self) -> list[str]:
        """Return comma-separated browser origins as a clean list."""
        return [
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        ]
