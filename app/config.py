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
    supplier_balance_critical_ratio: float = 2.0
    retailer_due_soon_days: int = 7
    retailer_high_risk_overdue_days: int = 30
    retailer_high_risk_credit_ratio: float = 1.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
