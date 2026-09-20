"""Profile analyzer extracting high-value conversation hooks from profile metadata."""
from typing import Any


class ProfileAnalyzer:
    """Finds natural conversation hooks from bio and interests."""

    @staticmethod
    def extract_hooks(profile: dict[str, Any]) -> list[str]:
        hooks = []
        bio = profile.get("bio", "").lower()
        interests = profile.get("interests", [])

        if "cafe" in bio or any("coffee" in str(i).lower() for i in interests):
            hooks.append("Thích cafe, quán xá")
        if "du lịch" in bio or any("travel" in str(i).lower() for i in interests):
            hooks.append("Thích du lịch khám phá")
        if "mèo" in bio or "chó" in bio or any("pet" in str(i).lower() for i in interests):
            hooks.append("Yêu thú cưng")

        return hooks
