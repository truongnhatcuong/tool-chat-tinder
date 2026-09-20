"""Application settings module using Pydantic Settings and JSON config."""
import json
import os
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_JSON_PATH = BASE_DIR / "config" / "config.json"


class BrowserConfig(BaseModel):
    headless: bool = False
    profile_dir: str = "./data/tinder_browser"
    tinder_url: str = "https://tinder.com/"
    latitude: float = 16.0544
    longitude: float = 108.2022


class ScannerConfig(BaseModel):
    match_scan_interval: float = 10.0
    message_scan_interval: float = 2.0


class AutomationConfig(BaseModel):
    message_debounce_seconds: float = 5.0
    reply_delay_min: float = 3.0
    reply_delay_max: float = 10.0
    max_parallel_conversations: int = 5
    max_ai_replies_per_minute: int = 6
    default_match_mode: str = "AUTO"


class AIConfig(BaseModel):
    temperature: float = 0.7
    max_tokens: int = 150
    max_history_messages: int = 20
    max_retries: int = 3
    summary_trigger_count: int = 30


class AppSettings(BaseSettings):
    """Global application settings merging environment variables and config.json."""
    
    # Environment variables
    ai_api_key: str = Field(default="", validation_alias="AI_API_KEY")
    ai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="AI_BASE_URL")
    ai_model: str = Field(default="gpt-4o-mini", validation_alias="AI_MODEL")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/tinder_ai.db",
        validation_alias="DATABASE_URL"
    )
    debug: bool = Field(default=True, validation_alias="DEBUG")
    dry_run: bool = Field(default=True, validation_alias="DRY_RUN")
    global_auto_reply: bool = Field(default=False, validation_alias="GLOBAL_AUTO_REPLY")
    inspect_dom: bool = Field(default=True, validation_alias="INSPECT_DOM")
    user_age: int = Field(default=24, validation_alias="USER_AGE")
    
    # Nested configs from config.json
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    
    # App runtime state flags
    is_paused: bool = False
    emergency_stop: bool = False

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def get_masked_api_key(self) -> str:
        """Return masked API key for logging and GUI display."""
        if not self.ai_api_key or len(self.ai_api_key) < 8:
            return "********" if self.ai_api_key else ""
        return f"{self.ai_api_key[:3]}...{self.ai_api_key[-4:]}"

    def get_database_url(self) -> str:
        """Resolve database URL and ensure async driver prefix if needed."""
        url = self.database_url.strip()
        # Normalise sqlite URLs for aiosqlite
        if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite:///"):
            url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        # Normalise mysql URLs for aiomysql
        elif url.startswith("mysql://") and not url.startswith("mysql+aiomysql://"):
            url = url.replace("mysql://", "mysql+aiomysql://", 1)
        return url

    def save_config_json(self) -> None:
        """Persist nested configurations back to config.json."""
        data = {
            "browser": self.browser.model_dump(),
            "scanner": self.scanner.model_dump(),
            "automation": self.automation.model_dump(),
            "ai": self.ai.model_dump()
        }
        with open(CONFIG_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def load_json_overrides() -> dict[str, Any]:
    """Read config.json if it exists."""
    if CONFIG_JSON_PATH.exists():
        try:
            with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


_settings_instance: AppSettings | None = None


def get_settings() -> AppSettings:
    """Singleton getter for application settings."""
    global _settings_instance
    if _settings_instance is None:
        json_data = load_json_overrides()
        _settings_instance = AppSettings(**json_data)
    return _settings_instance


def reload_settings() -> AppSettings:
    """Reload settings from disk and environment."""
    global _settings_instance
    json_data = load_json_overrides()
    _settings_instance = AppSettings(**json_data)
    return _settings_instance
