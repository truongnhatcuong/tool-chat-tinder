"""Keep the operating system awake while Tinder automation is running."""
from __future__ import annotations

import atexit
import ctypes
import os
import subprocess
import sys
from typing import Final

from utils.logger import logger


class SleepPreventer:
    """Prevent idle system sleep on macOS and Windows, but allow display sleep."""

    _ES_CONTINUOUS: Final[int] = 0x80000000
    _ES_SYSTEM_REQUIRED: Final[int] = 0x00000001

    def __init__(self) -> None:
        self._active = False
        self._caffeinate_process: subprocess.Popen | None = None
        atexit.register(self.allow_sleep)

    @property
    def is_active(self) -> bool:
        return self._active

    def prevent_sleep(self) -> bool:
        """Keep the computer awake until allow_sleep() or process termination."""
        if self._active:
            return True

        if sys.platform == "darwin":
            return self._prevent_macos_sleep()
        if sys.platform.startswith("win"):
            return self._prevent_windows_sleep()

        logger.info(
            f"Sleep prevention is not configured for platform '{sys.platform}'."
        )
        return False

    def _prevent_macos_sleep(self) -> bool:
        """Use caffeinate -i tied to this Python PID; do not force display awake."""
        caffeinate_path = "/usr/bin/caffeinate"
        if not os.path.exists(caffeinate_path):
            logger.warning("macOS caffeinate was not found; system sleep is not blocked.")
            return False

        try:
            self._caffeinate_process = subprocess.Popen(
                [caffeinate_path, "-i", "-w", str(os.getpid())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._active = True
            logger.info(
                "Sleep prevention enabled on macOS: system stays awake while "
                "the tool runs; the display may still turn off."
            )
            return True
        except Exception as exc:
            logger.warning(f"Could not enable macOS sleep prevention: {exc}")
            return False

    def _prevent_windows_sleep(self) -> bool:
        """Request continuous system availability without ES_DISPLAY_REQUIRED."""
        try:
            result = ctypes.windll.kernel32.SetThreadExecutionState(
                self._ES_CONTINUOUS | self._ES_SYSTEM_REQUIRED
            )
            if result == 0:
                raise OSError("SetThreadExecutionState returned 0")
            self._active = True
            logger.info(
                "Sleep prevention enabled on Windows: system stays awake while "
                "the tool runs; the display may still turn off."
            )
            return True
        except Exception as exc:
            logger.warning(f"Could not enable Windows sleep prevention: {exc}")
            return False

    def allow_sleep(self) -> None:
        """Restore the operating system's normal idle-sleep behavior."""
        if not self._active:
            return

        if sys.platform == "darwin":
            process = self._caffeinate_process
            self._caffeinate_process = None
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass

        elif sys.platform.startswith("win"):
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(self._ES_CONTINUOUS)
            except Exception as exc:
                logger.debug(f"Could not restore Windows sleep state cleanly: {exc}")

        self._active = False
        logger.info("Sleep prevention disabled; normal system sleep was restored.")


sleep_preventer = SleepPreventer()
