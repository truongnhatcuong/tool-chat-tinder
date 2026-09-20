"""Service coordinating match synchronization and mode management."""
from database.db import get_db_session
from database.repository import MatchRepository, ConversationRepository, MessageRepository
from utils.logger import logger


class MatchService:
    """Business logic for matches and mode configuration."""

    @staticmethod
    async def sync_matches(matches_data: list[dict]) -> list[dict]:
        """Save newly discovered matches or update existing ones in the database."""
        async with get_db_session() as session:
            repo = MatchRepository(session)
            results = []
            for item in matches_data:
                m = await repo.upsert_match(
                    tinder_id=item["tinder_id"],
                    name=item.get("name", "Match"),
                    age=item.get("age"),
                    bio=item.get("bio"),
                    profile_json=item.get("profile_json"),
                    mode=item.get("mode")
                )
                results.append({
                    "tinder_id": m.tinder_id,
                    "name": m.name,
                    "mode": m.mode,
                    "status": "Active"
                })
            return results

    @staticmethod
    async def set_mode(tinder_id: str, mode: str) -> None:
        async with get_db_session() as session:
            repo = MatchRepository(session)
            await repo.update_mode(tinder_id, mode)
            logger.info(f"Updated database mode for match {tinder_id} -> {mode}")

    @staticmethod
    async def get_mode(tinder_id: str) -> str:
        async with get_db_session() as session:
            repo = MatchRepository(session)
            m = await repo.get_by_tinder_id(tinder_id)
            return m.mode if m else "AUTO"

    @staticmethod
    async def set_all_modes(mode: str) -> None:
        """Update mode for all matches in the database."""
        async with get_db_session() as session:
            repo = MatchRepository(session)
            count = await repo.update_all_modes(mode)
            logger.info(f"Updated database mode for ALL matches ({count} updated) -> {mode}")

    @staticmethod
    async def list_matches() -> list[dict]:
        async with get_db_session() as session:
            repo = MatchRepository(session)
            models = await repo.list_all()
            return [
                {
                    "tinder_id": m.tinder_id,
                    "name": m.name,
                    "age": m.age,
                    "bio": m.bio,
                    "mode": m.mode,
                    "status": "Idle"
                }
                for m in models
            ]

    @staticmethod
    async def delete_match(tinder_id: str) -> bool:
        """Completely remove match and its related messages/conversations from database."""
        async with get_db_session() as session:
            repo = MatchRepository(session)
            deleted = await repo.delete_by_tinder_id(tinder_id)
            conv_repo = ConversationRepository(session)
            await conv_repo.delete_by_match_id(tinder_id)
            msg_repo = MessageRepository(session)
            await msg_repo.delete_by_match_id(tinder_id)
            logger.info(f"Unmatch cleanup: Deleted match {tinder_id} and related history from database.")
            return deleted

    @staticmethod
    async def cleanup_unmatched(current_active_tinder_ids: set[str]) -> list[str]:
        """Find matches in DB that no longer exist on Tinder (unmatched) and remove them."""
        async with get_db_session() as session:
            repo = MatchRepository(session)
            all_db_matches = await repo.list_all()
            unmatched_ids = [
                m.tinder_id for m in all_db_matches
                if m.tinder_id not in current_active_tinder_ids
            ]
        
        for tid in unmatched_ids:
            await MatchService.delete_match(tid)
        return unmatched_ids
