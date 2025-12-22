import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> set[int]:
    if not raw:
        return set()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
    return ids


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: set[int]
    tz: str
    database_url: str
    seed_json_path: str
    seed_on_start: bool


def load_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set")

    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

    tz = os.getenv("TZ", "Europe/Moscow").strip() or "Europe/Moscow"
    database_url = os.getenv("DATABASE_URL", "sqlite:///./bot_data/bot.db").strip()
    seed_json_path = os.getenv("SEED_JSON_PATH", "data/challenge_posts.json").strip() or "data/challenge_posts.json"
    seed_on_start = os.getenv("SEED_ON_START", "1").strip() not in ("0", "false", "False", "no", "NO")

    return Settings(
        bot_token=bot_token,
        admin_ids=admin_ids,
        tz=tz,
        database_url=database_url,
        seed_json_path=seed_json_path,
        seed_on_start=seed_on_start,
    )


