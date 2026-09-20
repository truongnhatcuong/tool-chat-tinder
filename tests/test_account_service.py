"""Unit tests for AccountService managing multi-account Tinder browser profiles."""
import pytest
import tempfile
import json
from pathlib import Path
from services.account_service import AccountService


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """Use a temporary config.json and profiles directory for tests."""
    temp_config = tmp_path / "config.json"
    temp_profiles = tmp_path / "profiles"
    temp_profiles.mkdir(parents=True, exist_ok=True)

    initial_config = {
        "browser": {
            "headless": False,
            "profile_dir": "./data/tinder_browser",
            "tinder_url": "https://tinder.com/"
        }
    }
    with open(temp_config, "w", encoding="utf-8") as f:
        json.dump(initial_config, f)

    monkeypatch.setattr("services.account_service.CONFIG_JSON_PATH", temp_config)
    monkeypatch.setattr("services.account_service.PROFILES_DIR", temp_profiles)
    from config.settings import get_settings
    orig_profile = get_settings().browser.profile_dir
    yield
    get_settings().browser.profile_dir = orig_profile


def test_default_account_auto_initialization():
    """Verify default account is automatically registered on first call."""
    accounts = AccountService.get_accounts()
    assert len(accounts) == 1
    assert accounts[0]["id"] == "default"
    assert "Tài khoản 1" in accounts[0]["name"]

    active = AccountService.get_active_account()
    assert active["id"] == "default"


def test_add_and_switch_account():
    """Verify adding a new profile and switching active account."""
    new_acc = AccountService.add_account("Nick Phụ 2")
    assert new_acc["name"] == "Nick Phụ 2"
    assert "acc_" in new_acc["id"]

    accounts = AccountService.get_accounts()
    assert len(accounts) == 2

    # Switch active
    switched = AccountService.set_active_account(new_acc["id"])
    assert switched["id"] == new_acc["id"]

    active = AccountService.get_active_account()
    assert active["id"] == new_acc["id"]


def test_rename_account():
    """Verify renaming an existing account profile."""
    new_acc = AccountService.add_account("Old Name")
    renamed = AccountService.rename_account(new_acc["id"], "Brand New Name")
    assert renamed is True

    updated = AccountService.get_account_by_id(new_acc["id"])
    assert updated is not None
    assert updated["name"] == "Brand New Name"


def test_delete_account_and_protection():
    """Verify account deletion and prevention of deleting the only remaining account."""
    # Cannot delete single account
    assert AccountService.delete_account("default") is False

    # Add second account
    acc2 = AccountService.add_account("Nick 2")
    assert len(AccountService.get_accounts()) == 2

    # Now can delete acc2
    assert AccountService.delete_account(acc2["id"]) is True
    assert len(AccountService.get_accounts()) == 1
