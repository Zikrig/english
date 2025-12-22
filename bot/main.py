import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.admin_handlers import admin_router
from bot.config import load_settings
from bot.db import init_db, make_engine, make_session_factory
from bot.handlers import router
from bot.scheduler import setup_scheduler
from bot.seed_posts import seed_posts_from_json


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = load_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    init_db(engine)

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # used by scheduler for delivery notifications
    bot._admin_ids = settings.admin_ids  # type: ignore[attr-defined]
    dp = Dispatcher()

    # dependency injection (available as handler args by name)
    dp["settings"] = settings
    dp["session_factory"] = session_factory

    dp.include_router(router)
    dp.include_router(admin_router)

    if settings.seed_on_start:
        try:
            created = seed_posts_from_json(session_factory=session_factory, json_path=settings.seed_json_path, tz=settings.tz)
            if created:
                logging.getLogger(__name__).info("Seeded %s posts from %s", created, settings.seed_json_path)
        except FileNotFoundError:
            logging.getLogger(__name__).warning("Seed JSON not found: %s", settings.seed_json_path)
        except Exception:
            logging.getLogger(__name__).exception("Failed to seed posts from %s", settings.seed_json_path)

    scheduler = setup_scheduler(bot=bot, session_factory=session_factory, tz=settings.tz)
    dp["scheduler"] = scheduler

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())


