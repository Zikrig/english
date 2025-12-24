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
from bot.db import get_post, set_user_level, upsert_user
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
        """🎄 <b>New Year English Challenge with Angie</b>

Добро пожаловать в новогодний English-челлендж!

Hello, holiday star! 🌟
Welcome to the New Year English Challenge with Angie🎄
It’s my New Year present for you! 🎁

I want your holidays to be fun, festive and useful for your English.
Hope you’ll enjoy it as much as I enjoyed creating it for you!☺️"""
    )
    await asyncio.sleep(3)
    await message.answer(
        """✨ <b>Как всё устроено</b>

Челлендж начинается <b>29 декабря</b> и продолжается до <b>7 января</b>. Каждый день ты будешь получать от меня маленькое задание или приятное новогоднее сообщение💙 и, конечно, будут подарки!🎁

✨ Всего челлендж длится <b>10 дней</b>
✨ В нём будет <b>8 заданий</b>. English only! Отвечаем только на английском, как можем :) 
✨ Я разыграю <b>3 новогодних подарка</b> для вашего английского
✨ <b>Чтобы участвовать в розыгрыше</b>, нужно:
• <b>выполнить все задания</b>
• <b>быть моим учеником</b>🧤🫶
✨ У вас будет почти <b>две недели</b> на выполнение: выполните все задания до 10 января, 12:00
✨ Итоги я подведу <b>11-12 января</b>

Получается такой  небольшой новогодний адвент к православному Рождеству 🎄с практикой английского, теплом и подарками 🎀
        """
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


async def _deliver_post_to_chat(message: Message, post) -> None:
    media_type = (getattr(post, "media_type", None) or "").strip().lower()
    file_id = getattr(post, "file_id", None)
    text = getattr(post, "text", "") or ""

    if not media_type or not file_id:
        await message.answer(text)
        return

    if media_type == "photo":
        await message.answer_photo(photo=file_id, caption=text)
        return
    if media_type == "video":
        await message.answer_video(video=file_id, caption=text)
        return
    if media_type == "document":
        await message.answer_document(document=file_id, caption=text)
        return
    if media_type == "audio":
        await message.answer_audio(audio=file_id, caption=text)
        return
    if media_type == "voice":
        await message.answer_voice(voice=file_id, caption=text)
        return
    if media_type == "video_note":
        await message.answer_video_note(video_note=file_id)
        if text.strip():
            await message.answer(text)
        return

    await message.answer(text)


@router.callback_query(F.data.startswith("openpost:"))
async def open_post_callback(call: CallbackQuery, session_factory):
    post_id = int(call.data.split(":", 1)[1])
    db = session_factory()
    try:
        post = get_post(db, post_id)
    finally:
        db.close()
    if not post:
        await call.answer("Пост не найден", show_alert=True)
        return
    # remove button
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _deliver_post_to_chat(call.message, post)
    await call.answer()


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
