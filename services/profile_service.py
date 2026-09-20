"""Profile service managing extracted metadata."""
from database.db import get_db_session
from database.repository import MatchProfileRepository, MatchRepository


class ProfileService:
    @staticmethod
    async def update_profile(match_id: str, profile_data: dict) -> None:
        async with get_db_session() as session:
            match_repo = MatchRepository(session)
            profile_repo = MatchProfileRepository(session)

            # Update match record with basic fields
            await match_repo.upsert_match(
                tinder_id=match_id,
                name=profile_data.get("name", "Match"),
                age=profile_data.get("age"),
                bio=profile_data.get("bio"),
                profile_json=profile_data
            )

            # Update detailed profile table
            await profile_repo.upsert_profile(
                match_id=match_id,
                interests_json=profile_data.get("interests")
            )
