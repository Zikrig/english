import asyncio
import datetime as dt
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy.orm import Session

from bot.db import (
    Post,
    get_all_users,
    get_post,
    get_unsent_due_posts,
    get_unsent_future_posts,
    get_users_by_level,
    mark_post_sent,
)

logger = logging.getLogger(__name__)


def _job_id(post_id: int) -> str:
    return f"post_{post_id}"


async def _send_post(bot: Bot, session_factory, post_id: int, tz: str) -> None:
    db: Session = session_factory()
    try:
        post = get_post(db, post_id)
        if not post:
            return
        if post.sent:
            return

        if post.level == "all":
            users = get_all_users(db)
        else:
            users = get_users_by_level(db, post.level)
        total_count = len(users)
        sent_count = 0
        for user in users:
            try:
                await _deliver_post_to_user(bot, user.telegram_id, post)
                sent_count += 1
                await asyncio.sleep(0.04)
            except TelegramRetryAfter as e:
                await asyncio.sleep(float(e.retry_after) + 0.5)
            except TelegramForbiddenError:
                # user blocked bot / can't be reached: ignore
                continue
            except TelegramBadRequest:
                continue
            except Exception:
                logger.exception("Failed sending post_id=%s to telegram_id=%s", post_id, user.telegram_id)
                continue

        now = dt.datetime.now()
        mark_post_sent(db, post_id, sent_at=now)
        logger.info("Post %s sent to %s users", post_id, sent_count)
        await _notify_admins_summary(bot, post_id=post.id, post_level=post.level, delivered=sent_count, total=total_count)
    finally:
        db.close()


async def _deliver_post_to_user(bot: Bot, chat_id: int, post: Post) -> None:
    """
    Send a post with optional media (stored as Telegram file_id).
    Supported: photo/video/document/audio/voice/video_note; otherwise fall back to text.
    """
    media_type = (post.media_type or "").strip().lower()
    file_id = post.file_id
    text = post.text or ""

    if not media_type or not file_id:
        await bot.send_message(chat_id=chat_id, text=text)
        return

    if media_type == "photo":
        await bot.send_photo(chat_id=chat_id, photo=file_id, caption=text)
        return
    if media_type == "video":
        await bot.send_video(chat_id=chat_id, video=file_id, caption=text)
        return
    if media_type == "document":
        await bot.send_document(chat_id=chat_id, document=file_id, caption=text)
        return
    if media_type == "audio":
        await bot.send_audio(chat_id=chat_id, audio=file_id, caption=text)
        return
    if media_type == "voice":
        await bot.send_voice(chat_id=chat_id, voice=file_id, caption=text)
        return
    if media_type == "video_note":
        await bot.send_video_note(chat_id=chat_id, video_note=file_id)
        if text.strip():
            await bot.send_message(chat_id=chat_id, text=text)
        return

    await bot.send_message(chat_id=chat_id, text=text)

async def _notify_admins_summary(bot: Bot, *, post_id: int, post_level: str, delivered: int, total: int) -> None:
    """
    Sends ONE admin notification per post send.
    Admin IDs are stored on the Bot instance as `bot._admin_ids` (set in main).
    """
    admin_ids = getattr(bot, "_admin_ids", None)
    if not admin_ids:
        return
    text = (
        f"✅ Рассылка завершена\n"
        f"Пост: <b>#{post_id}</b> (уровень: <b>{post_level}</b>)\n"
        f"Доставлено: <b>{delivered}</b> / <b>{total}</b>"
    )
    for admin_id in list(admin_ids):
        try:
            await bot.send_message(chat_id=int(admin_id), text=text, disable_web_page_preview=True)
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.5)
            try:
                await bot.send_message(chat_id=int(admin_id), text=text, disable_web_page_preview=True)
            except Exception:
                continue
        except (TelegramForbiddenError, TelegramBadRequest):
            continue
        except Exception:
            continue


def schedule_or_send_now(
    *,
    bot: Bot,
    scheduler: AsyncIOScheduler,
    session_factory,
    post: Post,
    tz: str,
) -> None:
    if post.sent:
        return

    now = dt.datetime.now()
    jobid = _job_id(post.id)

    # best-effort cleanup
    try:
        scheduler.remove_job(jobid)
    except Exception:
        pass

    if post.send_at <= now:
        asyncio.create_task(_send_post(bot, session_factory, post.id, tz))
        return

    scheduler.add_job(
        _send_post,
        trigger=DateTrigger(run_date=post.send_at),
        id=jobid,
        args=[bot, session_factory, post.id, tz],
        replace_existing=True,
        misfire_grace_time=60 * 60,
    )


def unschedule_post(scheduler: AsyncIOScheduler, post_id: int) -> None:
    try:
        scheduler.remove_job(_job_id(post_id))
    except Exception:
        pass


def setup_scheduler(*, bot: Bot, session_factory, tz: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.start()

    db: Session = session_factory()
    try:
        now = dt.datetime.now()

        due = get_unsent_due_posts(db, now=now)
        for post in due:
            asyncio.create_task(_send_post(bot, session_factory, post.id, tz))

        future = get_unsent_future_posts(db, now=now)
        for post in future:
            schedule_or_send_now(bot=bot, scheduler=scheduler, session_factory=session_factory, post=post, tz=tz)
    finally:
        db.close()

    return scheduler


