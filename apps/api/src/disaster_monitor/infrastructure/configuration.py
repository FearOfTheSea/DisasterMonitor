"""Environment-backed infrastructure settings."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE_LOCATIONS = (".env", "apps/api/.env")


class Settings(BaseSettings):
    """Configuration required to run the local API."""

    app_name: str = Field(default="Disaster Monitor API", min_length=1)
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    ollama_base_url: str = Field(default="http://localhost:11434", min_length=1)
    ollama_model: str = Field(default="qwen3:4b-instruct-2507-q4_K_M", min_length=1)
    ollama_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    ollama_max_tokens: int = Field(default=512, ge=32, le=4096)
    specialist_llm_enabled: bool = False
    specialist_model_call_limit: int = Field(default=2, ge=0, le=2)
    long_term_memory_enabled: bool = False
    ollama_vision_model: str = Field(default="qwen3-vl:2b", min_length=1)
    ollama_vision_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    ollama_vision_max_tokens: int = Field(default=384, ge=64, le=2048)
    disaster_provider_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    disaster_provider_max_response_bytes: int = Field(
        default=1_000_000, ge=10_000, le=5_000_000
    )
    weather_alert_max_response_bytes: int = Field(
        default=3_000_000, ge=100_000, le=5_000_000
    )
    weather_alert_max_records: int = Field(default=500, ge=1, le=500)
    copernicus_sentinel_hub_instance_id: SecretStr | None = Field(
        default=None, repr=False
    )
    copernicus_sentinel_hub_layer_id: str = Field(
        default="TRUE_COLOR", pattern=r"^[A-Za-z0-9_-]+$"
    )
    planet_api_key: SecretStr | None = Field(default=None, repr=False)
    planet_mosaic_name: str | None = Field(default=None, max_length=200)
    event_media_enabled: bool = True
    event_media_target_count: int = Field(default=3, ge=1, le=6)
    event_media_candidate_limit: int = Field(default=12, ge=3, le=30)
    event_media_max_image_bytes: int = Field(
        default=3_000_000, ge=100_000, le=10_000_000
    )
    event_media_store_maximum_bytes: int = Field(
        default=24_000_000, ge=3_000_000, le=100_000_000
    )
    event_media_blob_root: Path = Path("data/event-media/blobs")
    reliefweb_app_name: str | None = None
    nasa_firms_map_key: SecretStr | None = Field(default=None, repr=False)
    operational_database_url: SecretStr | None = Field(default=None, repr=False)
    operational_blob_root: Path = Path("data/operational/blobs")
    operational_auto_migrate: bool = True
    country_catalog_root: Path = Path("data/geography")
    country_catalog_automatic_updates: bool = True
    country_catalog_update_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    country_catalog_max_response_bytes: int = Field(
        default=10_000_000, ge=1_000_000, le=50_000_000
    )
    country_catalog_retry_hours: int = Field(default=6, ge=1, le=168)
    trusted_operator_identity_enabled: bool = False
    trusted_operator_identity_header: str = Field(
        default="x-disastermonitor-operator", pattern=r"^[a-z0-9-]+$"
    )

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE_LOCATIONS,
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
