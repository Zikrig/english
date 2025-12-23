from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram import F
import asyncio
import datetime as dt
from zoneinfo import ZoneInfo
import re

from bot.config import Settings
from bot.db import set_user_level, upsert_user
from bot.keyboards import LEVELS, user_level_kb

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, session_factory):
    """
    Minimal user entrypoint:
    - registers user in DB so they can receive scheduled posts
    """
    if not message.from_user:
        return
    db = session_factory()
    try:
        upsert_user(db, telegram_id=message.from_user.id)
    finally:
        db.close()

    # Day 0 intro + level selection
    await message.answer(
        "🎄 <b>New Year English Challenge with Angie</b>\n\n"
        "Hello, holiday star! Welcome to the New Year English Challenge 🎄\n"
        "It’s my New Year present for you, I want to make your New Year holidays fun, festive and meaningful in terms of English.\n"
        "Hope you’ll enjoy it as much as I enjoyed creating it for you!\n\n"
        "Добро пожаловать в новогодний English-челлендж!"
    )
    await asyncio.sleep(3)
    await message.answer(
        "✨ <b>Как всё устроено</b>\n\n"
        "Our challenge starts on December 29th, you’ll get the 1st little new year task.\n\n"
        "✨ One small task a day (29 Dec – 7 Jan)\n"
        "✨ Одно небольшое задание в день (29 декабря – 7 января)\n\n"
        "✨ Complete all tasks by 10 January, 12:00.\n"
        "✨ Выполните все задания до 10 января, 10:00\n\n"
        "✨ English only\n"
        "✨ Отвечаем на английском, как можем:)\n\n"
        "✨ Fun, practice and holiday mood 💙\n"
        "✨ Практика, радость и праздничное настроение 💙"
    )
    await asyncio.sleep(3)
    await message.answer("Before we start, please choose your level 👇", reply_markup=user_level_kb())


@router.callback_query(F.data.startswith("ulevel:"))
async def choose_level(call: CallbackQuery, session_factory):
    if not call.from_user:
        return
    level = call.data.split(":", 1)[1]
    if level not in LEVELS:
        await call.answer("Неизвестный уровень", show_alert=True)
        return

    db = session_factory()
    try:
        set_user_level(db, telegram_id=call.from_user.id, level=level)
    finally:
        db.close()

    await call.message.answer(f"Great! You chose <b>{LEVELS[level]}</b>.\n\nGreat! See you on December 29th! 🎄")
    await call.answer("Сохранено ✅")


class NotCommand(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        txt = (message.text or message.caption or "").strip()
        return not txt.startswith("/")

class NotAdmin(BaseFilter):
    async def __call__(self, message: Message, settings: Settings) -> bool:
        if not message.from_user:
            return False
        return message.from_user.id not in settings.admin_ids


@router.message(F.chat.type == "private", NotCommand(), NotAdmin())
async def forward_non_admin_messages_to_admins(message: Message, settings: Settings):
    """
    Forward ALL non-admin user messages to admins (except commands).
    """
    if not message.from_user:
        return

    # hashtags for each forwarded message (requested format)
    today = dt.datetime.now(ZoneInfo(settings.tz)).date().isoformat()  # YYYY-MM-DD
    today = today.replace("-", "_")
    tags = f"#{today} #tg{message.from_user.id}"
    if message.from_user.username:
        nick = re.sub(r"[^0-9A-Za-z_]", "_", message.from_user.username).strip("_")
        if nick:
            tags += f" @{nick}"

    for admin_id in settings.admin_ids:
        try:
            forwarded = await message.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            await message.bot.send_message(
                chat_id=admin_id,
                text=tags,
                reply_to_message_id=forwarded.message_id,
            )
        except Exception:
            continue
