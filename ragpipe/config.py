from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAGPIPE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://ragpipe:ragpipe@localhost:5432/ragpipe"
    embedding_provider: str = "local"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = Field(default=384, gt=0)
    chunk_size: int = Field(default=800, gt=0)
    chunk_overlap: int = Field(default=120, ge=0)
    batch_size: int = Field(default=64, gt=0, le=2048)
    log_level: str = "INFO"
    source: Path | None = None

    @model_validator(mode="after")
    def validate_overlap(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self
