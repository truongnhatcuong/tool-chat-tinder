"""Tests for BrowserManager lifecycle and configuration."""
import pytest
from browser.manager import BrowserManager
from config.settings import get_settings


def test_browser_manager_init():
    settings = get_settings()
    mgr = BrowserManager()
    assert mgr.is_running is False
    assert mgr.page is None
    assert settings.browser.profile_dir == "./data/tinder_browser"
    assert "tinder.com" in settings.browser.tinder_url
