from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DistribuSense"
    environment: str = "development"
    database_url: str = "sqlite:///./distribusense.db"
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    safety_stock_days: float = 3
    stockout_warning_days: int = 14
    slow_moving_days: int = 30
    expiry_monitor_days: int = 90
    expiry_warning_days: int = 60
    expiry_critical_days: int = 30
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
