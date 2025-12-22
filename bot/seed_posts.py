import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.db import Post, create_post
from bot.time_utils import parse_moscow_datetime


def seed_posts_from_json(*, session_factory, json_path: str, tz: str) -> int:
    """
    Loads posts from JSON and inserts them into DB if missing (idempotent by key/level/send_at).
    Returns number of created posts.
    JSON format:
      { "posts": [ { "key": str, "title": str, "level": "all|starters|explorers|achievers", "send_at": "YYYY-MM-DD HH:MM", "text_html": str } ] }
    """
    path = Path(json_path)
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    if not path.exists():
        raise FileNotFoundError(f"Seed JSON not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    posts = raw.get("posts", [])
    created = 0

    db: Session = session_factory()
    try:
        for item in posts:
            key = (item.get("key") or "").strip()
            title = (item.get("title") or "").strip()
            level = (item.get("level") or "all").strip()
            send_at_s = (item.get("send_at") or "").strip()
            text_html = item.get("text_html") or ""
            if not key or not title or not send_at_s or not text_html:
                continue

            send_at = parse_moscow_datetime(send_at_s, tz)

            # idempotency check
            exists = db.scalar(
                select(Post.id).where(
                    Post.title == title,
                    Post.level == level,
                    Post.send_at == send_at,
                )
            )
            if exists:
                continue

            create_post(db, title=title, text=text_html, send_at=send_at, level=level)
            created += 1
    finally:
        db.close()

    return created


if __name__ == "__main__":
    raise SystemExit("Run via bot/main.py or import seed_posts_from_json()")


