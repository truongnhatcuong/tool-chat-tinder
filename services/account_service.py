"""Account service managing multi-account Tinder browser profiles."""
import json
import time
from pathlib import Path
from typing import Any
from config.settings import CONFIG_JSON_PATH, BASE_DIR, get_settings
from utils.logger import logger

PROFILES_DIR = BASE_DIR / "data" / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_ACCOUNT = {
    "id": "default",
    "name": "Tài khoản 1 (Chính)",
    "profile_dir": "./data/tinder_browser"
}


class AccountService:
    """Manages multi-account profiles with isolated Playwright Chromium user directories."""

    @classmethod
    def _read_config(cls) -> dict[str, Any]:
        if CONFIG_JSON_PATH.exists():
            try:
                with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading config.json: {e}")
                return {}
        return {}

    @classmethod
    def _write_config(cls, data: dict[str, Any]) -> None:
        try:
            with open(CONFIG_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error writing config.json: {e}")

    @classmethod
    def get_accounts(cls) -> list[dict[str, Any]]:
        """Return the list of all registered account profiles."""
        config = cls._read_config()
        accounts = config.get("accounts")
        if not accounts or not isinstance(accounts, list):
            # Initialize with default account
            accounts = [dict(DEFAULT_ACCOUNT)]
            config["accounts"] = accounts
            config["active_account_id"] = DEFAULT_ACCOUNT["id"]
            cls._write_config(config)
        return accounts

    @classmethod
    def get_active_account(cls) -> dict[str, Any]:
        """Return the currently active account profile."""
        config = cls._read_config()
        active_id = config.get("active_account_id", "default")
        accounts = cls.get_accounts()
        for acc in accounts:
            if acc.get("id") == active_id:
                return acc
        return accounts[0] if accounts else dict(DEFAULT_ACCOUNT)

    @classmethod
    def get_account_by_id(cls, account_id: str) -> dict[str, Any] | None:
        """Find an account by its ID."""
        accounts = cls.get_accounts()
        for acc in accounts:
            if acc.get("id") == account_id:
                return acc
        return None

    @classmethod
    def set_active_account(cls, account_id: str) -> dict[str, Any]:
        """Set active account by ID and update browser profile_dir."""
        config = cls._read_config()
        accounts = cls.get_accounts()
        target = None
        for acc in accounts:
            if acc.get("id") == account_id:
                target = acc
                break

        if not target:
            target = accounts[0]
            account_id = target["id"]

        config["active_account_id"] = account_id
        if "browser" not in config:
            config["browser"] = {}
        config["browser"]["profile_dir"] = target["profile_dir"]

        cls._write_config(config)

        # Update in-memory settings
        settings = get_settings()
        settings.browser.profile_dir = target["profile_dir"]
        logger.info(f"Active account changed to: {target['name']} (ID: {account_id})")
        return target

    @classmethod
    def add_account(cls, name: str) -> dict[str, Any]:
        """Create a new account profile with dedicated isolated profile folder."""
        config = cls._read_config()
        accounts = cls.get_accounts()

        acc_id = f"acc_{int(time.time())}"
        profile_folder_name = acc_id
        profile_abs_path = PROFILES_DIR / profile_folder_name
        profile_abs_path.mkdir(parents=True, exist_ok=True)
        profile_rel_dir = f"./data/profiles/{profile_folder_name}"

        new_acc = {
            "id": acc_id,
            "name": name.strip() or f"Tài khoản {len(accounts) + 1}",
            "profile_dir": profile_rel_dir
        }
        accounts.append(new_acc)
        config["accounts"] = accounts
        cls._write_config(config)

        logger.info(f"Added new account profile: {new_acc['name']} at {profile_rel_dir}")
        return new_acc

    @classmethod
    def rename_account(cls, account_id: str, new_name: str) -> bool:
        """Rename an existing account profile."""
        config = cls._read_config()
        accounts = cls.get_accounts()
        found = False
        for acc in accounts:
            if acc.get("id") == account_id:
                acc["name"] = new_name.strip()
                found = True
                break

        if found:
            config["accounts"] = accounts
            cls._write_config(config)
            logger.info(f"Renamed account {account_id} to '{new_name}'")
            return True
        return False

    @classmethod
    def delete_account(cls, account_id: str) -> bool:
        """
        Delete an account profile from registry.
        Cannot delete if it is the only remaining account.
        """
        config = cls._read_config()
        accounts = cls.get_accounts()

        if len(accounts) <= 1:
            logger.warning("Cannot delete the only remaining account.")
            return False

        remaining = [acc for acc in accounts if acc.get("id") != account_id]
        if len(remaining) == len(accounts):
            return False

        config["accounts"] = remaining
        # If deleted active account, switch to first remaining
        if config.get("active_account_id") == account_id:
            config["active_account_id"] = remaining[0]["id"]
            if "browser" in config:
                config["browser"]["profile_dir"] = remaining[0]["profile_dir"]
            get_settings().browser.profile_dir = remaining[0]["profile_dir"]

        cls._write_config(config)
        logger.info(f"Deleted account profile {account_id}.")
        return True
