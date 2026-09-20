"""Helper module to detect and dismiss annoying popups like Location permissions, Cookies, Notifications, Home screen."""
import asyncio
from playwright.async_api import Page
from utils.logger import logger

DISMISS_SELECTORS = [
    # 1. Location permission in-app modal (Tự động bấm Cho phép / Bật vị trí để Tinder hiển thị thẻ)
    "div[role='dialog'] button:has-text('Cho phép')",
    "button:has-text('Cho phép')",
    "div[role='dialog'] button:has-text('Bật vị trí')",
    "button:has-text('Bật vị trí')",
    "div[role='dialog'] button:has-text('Bật Vị Trí')",
    "button:has-text('Bật Vị Trí')",
    "div[role='dialog'] button:has-text('Allow')",
    "button:has-text('Allow')",
    "div[role='dialog'] button:has-text('Enable')",
    "button:has-text('Enable')",
    "button:has-text('Tôi hiểu')",

    # 2. Cookies & GDPR consent (Tự động chấp nhận để không bị che khuất màn hình)
    "button:has-text('Tôi chấp nhận')",
    "button:has-text('Chấp nhận tất cả')",
    "button:has-text('I accept')",
    "button:has-text('Accept all')",
    "button:has-text('Accept')",
    "button:has-text('Đồng ý')",

    # 3. Add to home screen dialog
    "button:has-text('Không quan tâm')",
    "div[role='dialog']:has-text('Thêm Tinder') button:has-text('Không quan tâm')",
    "button:has-text('Not interested')",

    # 4. Notifications permissions (Bấm từ chối/để sau để không bị spam thông báo hệ thống)
    "button:has-text('Không phải bây giờ')",
    "button:has-text('Not now')",
    "button:has-text('Sau')",
    "button:has-text('Để sau')",
    "button:has-text('Bỏ qua')",
    "button:has-text('Dismiss')",

    # 5. Upsell / Platinum / Priority Like dialogs
    "button:has-text('Có lẽ để sau đi')",
    "button:has-text('Maybe later')",
    "button:has-text('Không, cảm ơn')",
    "button:has-text('No thanks')",
    "div[role='dialog'] button:has(span:has-text('Đóng'))",
    "div[role='dialog'] button.close"
]


async def dismiss_blocking_popups(page: Page, max_rounds: int = 4) -> bool:
    """
    Check for blocking dialogs (Location, Cookies, Notifications, Upsells)
    and automatically click allow/dismiss buttons across multiple consecutive popups.
    """
    if not page or page.is_closed():
        return False

    any_dismissed = False
    for _ in range(max_rounds):
        round_dismissed = False
        for selector in DISMISS_SELECTORS:
            try:
                loc = page.locator(selector)
                if await loc.count() > 0 and await loc.first.is_visible():
                    btn_text = (await loc.first.inner_text()).strip()
                    logger.info(f"Phát hiện popup Tinder ('{btn_text}'). Đang tự động cấp quyền/bấm đóng...")
                    await loc.first.click()
                    await asyncio.sleep(0.8)
                    round_dismissed = True
                    any_dismissed = True
                    break
            except Exception:
                pass
        if not round_dismissed:
            break

    return any_dismissed
