"""Unit tests for configuration loading and safety defaults."""
import os
from config.settings import AppSettings, get_settings


def test_safety_defaults():
    # Model field defaults before any user .env overrides
    assert AppSettings.model_fields["dry_run"].default is True, "DRY_RUN model default must be True"
    assert AppSettings.model_fields["global_auto_reply"].default is False, "GLOBAL_AUTO_REPLY model default must be False"
    assert AppSettings.model_fields["inspect_dom"].default is True, "INSPECT_DOM model default must be True"


def test_api_key_masking():
    settings = AppSettings(AI_API_KEY="sk-abcdef1234567890qwertyuiop")
    masked = settings.get_masked_api_key()
    assert masked.startswith("sk-")
    assert masked.endswith("uiop")
    assert "abcdef" not in masked
    assert "..." in masked


def test_database_url_normalization():
    settings_sqlite = AppSettings(DATABASE_URL="sqlite:///./test.db")
    assert "aiosqlite" in settings_sqlite.get_database_url()

    settings_mysql = AppSettings(DATABASE_URL="mysql://root:pass@localhost:3306/db")
    assert "aiomysql" in settings_mysql.get_database_url()
