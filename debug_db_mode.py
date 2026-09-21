import asyncio
from database.db import get_db_session, init_db
from database.repository import MatchRepository
from database.models import MatchModel
from services.match_service import MatchService

async def main():
    await init_db()
    async with get_db_session() as session:
        repo = MatchRepository(session)
        # Create a mock match
        m = await repo.upsert_match("test1", "Alice", mode="AUTO")
        print(f"Initial mode: {m.mode}")

    # Set mode to OFF
    await MatchService.set_mode("test1", "OFF")

    # Read back
    async with get_db_session() as session:
        repo = MatchRepository(session)
        m = await repo.get_by_tinder_id("test1")
        print(f"Read back mode: {m.mode}")

if __name__ == "__main__":
    asyncio.run(main())
