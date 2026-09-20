"""Browser manager handling persistent Playwright Chromium context and session state."""
import asyncio
from datetime import datetime
from pathlib import Path
from playwright.async_api import (
    async_playwright,
    Playwright,
    BrowserContext,
    Page,
    Error as PlaywrightError
)
from config.settings import get_settings
from utils.logger import logger

DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug"
SCREENSHOTS_DIR = DEBUG_DIR / "screenshots"
HTML_DIR = DEBUG_DIR / "html"

SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
HTML_DIR.mkdir(parents=True, exist_ok=True)


class BrowserManager:
    """Manages persistent browser context, login detection, and lifecycle."""

    def __init__(self):
        self.settings = get_settings()
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def page(self) -> Page | None:
        return self._page

    async def start(self) -> Page:
        """Launch persistent browser context and navigate to Tinder."""
        if self._page and not self._page.is_closed():
            return self._page

        logger.info("Initializing Playwright Chromium with persistent profile...")
        profile_path = Path(self.settings.browser.profile_dir).resolve()
        profile_path.mkdir(parents=True, exist_ok=True)

        lat = getattr(self.settings.browser, "latitude", 16.0544)
        lon = getattr(self.settings.browser, "longitude", 108.2022)

        self._playwright = await async_playwright().start()

        # Launch persistent context
        # Automatically grants location and notification permissions to avoid annoying prompts
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=self.settings.browser.headless,
            viewport={"width": 1280, "height": 840},
            permissions=["geolocation", "notifications"],
            geolocation={"latitude": lat, "longitude": lon, "accuracy": 100},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ],
            ignore_default_args=["--enable-automation"]
        )

        try:
            await self._context.grant_permissions(
                ["geolocation", "notifications"],
                origin="https://tinder.com"
            )
            await self._context.set_geolocation({"latitude": lat, "longitude": lon, "accuracy": 100})
        except Exception as e:
            logger.debug(f"Permission grant notice: {e}")

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self._is_running = True

        logger.info(f"Navigating to {self.settings.browser.tinder_url}...")
        try:
            await self._page.goto(
                self.settings.browser.tinder_url,
                wait_until="domcontentloaded",
                timeout=45000
            )
        except Exception as e:
            logger.warning(f"Initial navigation completed with notice: {e}")

        # Automatically dismiss any initial blocking modals (Cookies, Location confirmation, Notifications)
        try:
            from browser.popup_handler import dismiss_blocking_popups
            await asyncio.sleep(1.5)
            await dismiss_blocking_popups(self._page)
        except Exception as e:
            logger.debug(f"Initial popup dismissal notice: {e}")

        return self._page

    async def check_login_status(self) -> bool:
        """
        Check if user is currently logged into Tinder.
        Detects URL pattern (/app/recs, /app/messages) or authenticated UI elements.
        """
        if not self._page or self._page.is_closed():
            return False

        try:
            current_url = self._page.url
            if "/app/" in current_url:
                logger.debug("Logged in detected via authenticated /app/ URL pattern.")
                return True

            # Check for logged-in specific DOM elements
            selectors = [
                "nav[aria-label='Sidebar']",
                "[data-testid='conversation-list']",
                "a[href*='/app/recs']",
                "a[href*='/app/messages']"
            ]
            for sel in selectors:
                loc = self._page.locator(sel)
                if await loc.count() > 0:
                    return True

            # Check if login button is present (meaning logged out)
            login_buttons = [
                "a[href*='login']",
                "button:has-text('Log in')",
                "button:has-text('Đăng nhập')"
            ]
            for btn in login_buttons:
                if await self._page.locator(btn).count() > 0:
                    return False

            return False
        except Exception as e:
            logger.warning(f"Error checking login status: {e}")
            return False

    async def wait_for_manual_login(self, timeout_seconds: int = 300) -> bool:
        """
        Pause and wait for the user to log in manually on first run.
        Polls every 2 seconds until logged in or timeout.
        """
        logger.info("Waiting for manual login in browser window (up to 5 minutes)...")
        elapsed = 0
        poll_interval = 2.0
        while elapsed < timeout_seconds:
            if not self._is_running or not self._page or self._page.is_closed():
                logger.warning("Browser closed while waiting for login.")
                return False

            if await self.check_login_status():
                logger.info("Tinder authentication verified! Session saved in browser profile.")
                return True

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        logger.error("Timed out waiting for manual Tinder login.")
        return False

    async def capture_debug_screenshot(self, name_prefix: str) -> Path:
        """Save a timestamped debug screenshot."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{name_prefix}_{timestamp}.png"
        filepath = SCREENSHOTS_DIR / filename
        if self._page and not self._page.is_closed():
            try:
                await self._page.screenshot(path=str(filepath))
                logger.debug(f"Saved debug screenshot: {filepath}")
            except Exception as e:
                logger.warning(f"Could not take screenshot: {e}")
        return filepath

    async def save_debug_html(self, name_prefix: str) -> Path:
        """Dump current page HTML content for DOM inspection."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{name_prefix}_{timestamp}.html"
        filepath = HTML_DIR / filename
        if self._page and not self._page.is_closed():
            try:
                html = await self._page.content()
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(html)
                logger.debug(f"Saved debug HTML dump: {filepath}")
            except Exception as e:
                logger.warning(f"Could not dump HTML: {e}")
        return filepath

    async def logout(self) -> bool:
        """
        Log out of current Tinder session by clearing storage and cookies.
        Navigates back to Tinder landing/login page.
        """
        logger.info("Logging out of Tinder session...")
        if self._page and not self._page.is_closed():
            try:
                if self._context:
                    await self._context.clear_cookies()
                await self._page.evaluate("""() => {
                    try {
                        localStorage.clear();
                        sessionStorage.clear();
                    } catch(e) {}
                }""")
                await self._page.goto(
                    self.settings.browser.tinder_url,
                    wait_until="domcontentloaded",
                    timeout=30000
                )
                logger.info("Tinder cookies and storage cleared. Browser navigated to login page.")
                return True
            except Exception as e:
                logger.error(f"Error during browser logout: {e}")
                return False
        return False

    async def restart_with_profile(self, profile_dir: str) -> Page:
        """
        Cleanly close existing browser and relaunch Playwright Chromium
        with a different account's persistent profile directory.
        """
        logger.info(f"Restarting browser with profile directory: {profile_dir}")
        await self.close()
        self.settings.browser.profile_dir = profile_dir
        return await self.start()

    async def open_or_focus(self) -> Page:
        """Ensure browser window is running, opened, and focused on Tinder."""
        if not self._is_running or not self._page or self._page.is_closed():
            return await self.start()
        try:
            await self._page.bring_to_front()
            if "/app/" not in self._page.url and "tinder.com" not in self._page.url:
                await self._page.goto(
                    self.settings.browser.tinder_url,
                    wait_until="domcontentloaded",
                    timeout=30000
                )
        except Exception as e:
            logger.warning(f"Could not focus page, restarting: {e}")
            return await self.start()
        return self._page

    async def close(self) -> None:
        """Cleanly close browser and context."""
        logger.info("Closing browser context...")
        self._is_running = False
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._playwright = None
        logger.info("Browser closed.")
