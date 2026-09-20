"""Profile reader extracting publicly visible match information from the profile card."""
import re
from typing import Any
from playwright.async_api import Page
from utils.logger import logger


class ProfileReader:
    """Reads profile details currently visible in Tinder's profile view."""

    def __init__(self, page: Page):
        self.page = page

    async def read_current_profile(self) -> dict[str, Any]:
        """Extract profile information (name, age, bio, interests, job, school)."""
        if not self.page or self.page.is_closed():
            return {}

        profile_data: dict[str, Any] = {
            "name": "",
            "age": None,
            "bio": "",
            "interests": [],
            "job": "",
            "school": "",
            "relationship_goal": "",
            "distance": ""
        }

        try:
            # 1. Name & Age
            header_loc = self.page.locator("h1")
            if await header_loc.count() > 0:
                header_text = (await header_loc.first.inner_text()).strip()
                match = re.search(r"^(.+?)\s*(\d{2})$", header_text)
                if match:
                    profile_data["name"] = match.group(1).strip()
                    profile_data["age"] = int(match.group(2))
                else:
                    profile_data["name"] = header_text

            # 2. Bio
            bio_loc = self.page.locator("div[class*='bio'], div[class*='userProfile__desc']")
            if await bio_loc.count() > 0:
                profile_data["bio"] = (await bio_loc.first.inner_text()).strip()

            # 3. Interests / Passions
            passions_loc = self.page.locator("div[class*='passions'] span, [data-testid='interest-tag']")
            count = await passions_loc.count()
            interests = []
            for i in range(count):
                tag = (await passions_loc.nth(i).inner_text()).strip()
                if tag and tag not in interests:
                    interests.append(tag)
            profile_data["interests"] = interests

        except Exception as e:
            logger.warning(f"Error reading profile info: {e}")

        return profile_data
