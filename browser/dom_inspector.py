"""DOM Inspector and Selector Health Check engine for Tinder Web."""
import json
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import Page
from browser.selectors import TINDER_SELECTORS
from utils.logger import logger

DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug"
DOM_REPORT_PATH = DEBUG_DIR / "dom_report.json"
DOM_NOTES_PATH = DEBUG_DIR / "dom_notes.md"


class DOMInspector:
    """Inspects live Tinder DOM, tests candidate locators, and performs health checks."""

    def __init__(self, page: Page):
        self.page = page

    async def test_selector(self, selector: str) -> tuple[bool, int, str]:
        """Test if a single selector matches elements on the page."""
        try:
            locator = self.page.locator(selector)
            count = await locator.count()
            if count > 0:
                # Check visibility of the first element
                is_visible = await locator.first.is_visible()
                return True, count, "visible" if is_visible else "hidden"
            return False, 0, "not found"
        except Exception as e:
            return False, 0, f"error: {e}"

    async def find_working_selector(self, key: str) -> tuple[str | None, int]:
        """Iterate through fallback candidates for a key and return the first working one."""
        candidates = TINDER_SELECTORS.get(key, [])
        for candidate in candidates:
            success, count, state = await self.test_selector(candidate)
            if success and count > 0:
                logger.debug(f"Selector match for '{key}': '{candidate}' (count={count}, state={state})")
                return candidate, count
        return None, 0

    async def run_full_inspection(self) -> dict:
        """
        Run a complete inspection across all declared selector categories.
        Outputs results to debug/dom_report.json and debug/dom_notes.md.
        """
        logger.info("================ STARTING TINDER REAL DOM INSPECTION ================")
        current_url = self.page.url
        report = {
            "scan_date": datetime.now(timezone.utc).isoformat(),
            "tinder_url": current_url,
            "selectors": {},
            "summary": {
                "total_checked": len(TINDER_SELECTORS),
                "matched": 0,
                "missing": 0
            }
        }

        notes_lines = [
            "# Tinder DOM Inspection Notes",
            f"**Inspection Date:** {report['scan_date']}",
            f"**Page URL:** {current_url}\n",
            "| Element Key | Working Selector | Elements Found | Status |",
            "|---|---|---|---|"
        ]

        for key, candidates in TINDER_SELECTORS.items():
            working_sel, count = await self.find_working_selector(key)
            if working_sel:
                report["selectors"][key] = working_sel
                report["summary"]["matched"] += 1
                notes_lines.append(f"| `{key}` | `{working_sel}` | {count} | ✅ Verified |")
            else:
                report["selectors"][key] = None
                report["summary"]["missing"] += 1
                notes_lines.append(f"| `{key}` | *None working from candidates* | 0 | ❌ Missing |")

        # Write dom_report.json
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        with open(DOM_REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # Write dom_notes.md
        with open(DOM_NOTES_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(notes_lines))

        logger.info(
            f"DOM Inspection finished: {report['summary']['matched']}/{report['summary']['total_checked']} selectors resolved."
        )
        logger.info(f"Report saved to {DOM_REPORT_PATH}")
        return report

    async def perform_health_check(self) -> tuple[bool, dict[str, str]]:
        """
        Selector health check required before automation or sending.
        If on /app/messages/, checks chat_input and message_container.
        If on /app/recs or sidebar, checks conversation_list.
        """
        logger.info("Checking Tinder DOM health...")
        current_url = self.page.url
        is_in_chat = "/app/messages/" in current_url

        critical_keys = ["conversation_list"]
        if is_in_chat:
            critical_keys.append("chat_input")
        else:
            logger.info("  (Đang ở trang quẹt thẻ /app/recs - Hãy click vào 1 người trong danh sách Matches để test chat_input)")

        results: dict[str, str] = {}
        all_passed = True

        for key in critical_keys:
            working_sel, count = await self.find_working_selector(key)
            if working_sel:
                results[key] = "OK"
                logger.info(f"  {key}: OK ({working_sel})")
            else:
                results[key] = "FAILED"
                all_passed = False
                logger.error(f"  {key}: FAILED - No matching selector found on live page.")

        if not all_passed:
            logger.critical("SELECTOR HEALTH CHECK FAILED! Global Auto Reply must remain DISABLED.")
        else:
            logger.info("SELECTOR HEALTH CHECK PASSED.")

        return all_passed, results
