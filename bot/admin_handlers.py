from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import Settings
from bot.db import (
    create_post,
    delete_post,
    get_post,
    get_post_dates,
    get_posts_by_date,
    get_posts_by_level,
    count_posts_by_date,
    count_posts_by_level,
    update_post_level,
    update_post_content,
    update_post_send_time,
    update_post_text_title,
)
from bot.keyboards import (
    LEVELS,
    admin_menu_kb,
    admin_post_level_kb,
    confirm_delete_kb,
    dates_kb,
    levels_kb,
    post_actions_kb,
    posts_list_kb,
)
from bot.scheduler import schedule_or_send_now, unschedule_post
from bot.time_utils import format_dt, parse_moscow_datetime

admin_router = Router()

PAGE_SIZE = 10


def _extract_message_content(message: Message) -> tuple[str, str | None, str | None]:
    """
    Extract text/caption (as HTML) + media type + Telegram file_id from a message.
    """
    html_text = getattr(message, "html_text", None)
    html_caption = getattr(message, "html_caption", None) or getattr(message, "caption_html", None)
    text = html_text or html_caption or message.text or message.caption or ""

    if message.photo:
        return text, "photo", message.photo[-1].file_id
    if message.video:
        return text, "video", message.video.file_id
    if message.voice:
        return text, "voice", message.voice.file_id
    if message.video_note:
        return text, "video_note", message.video_note.file_id
    if message.audio:
        return text, "audio", message.audio.file_id
    if message.document:
        return text, "document", message.document.file_id

    return text, None, None


async def _send_post_preview(message: Message, post) -> None:
    """
    Sends a preview of the post content into the current chat.
    This is needed because "view post" is rendered as text, but post may contain media.
    """
    media_type = (getattr(post, "media_type", None) or "").strip().lower()
    file_id = getattr(post, "file_id", None)
    text = getattr(post, "text", "") or ""

    # Telegram caption limit is 1024 chars. If longer, send as separate message.
    caption = text if len(text) <= 1024 else ""
    tail_text = "" if caption else text

    if not media_type or not file_id:
        return

    if media_type == "photo":
        await message.answer_photo(photo=file_id, caption=caption)
    elif media_type == "video":
        await message.answer_video(video=file_id, caption=caption)
    elif media_type == "document":
        await message.answer_document(document=file_id, caption=caption)
    elif media_type == "audio":
        await message.answer_audio(audio=file_id, caption=caption)
    elif media_type == "voice":
        await message.answer_voice(voice=file_id, caption=caption)
    elif media_type == "video_note":
        await message.answer_video_note(video_note=file_id)
    else:
        # unknown media type: ignore
        return

    if tail_text.strip():
        await message.answer(tail_text)

def _is_admin(user_id: int | None, settings: Settings) -> bool:
    return bool(user_id) and user_id in settings.admin_ids


class CreatePostFSM(StatesGroup):
    title = State()
    level = State()
    content = State()
    send_at = State()


class EditPostFSM(StatesGroup):
    title = State()
    level = State()
    text = State()
    send_at = State()
    content = State()


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, settings: Settings):
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        await message.answer("Доступ запрещён.")
        return
    await message.answer("Админ-панель:", reply_markup=admin_menu_kb())


@admin_router.callback_query(F.data == "admin:back")
async def admin_back(call: CallbackQuery, settings: Settings):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.edit_text("Админ-панель:", reply_markup=admin_menu_kb())
    await call.answer()

@admin_router.callback_query(F.data == "admin:dates")
async def admin_dates(call: CallbackQuery, settings: Settings, session_factory):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    db = session_factory()
    try:
        all_dates = get_post_dates(db)
    finally:
        db.close()

    page = 0
    chunk = all_dates[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    await call.message.edit_text(
        "🗓 <b>Посты по датам</b>\n\nВыберите дату:",
        reply_markup=dates_kb(chunk, page=page, has_prev=False, has_next=len(all_dates) > (page + 1) * PAGE_SIZE),
    )
    await call.answer()


@admin_router.callback_query(F.data.startswith("dpage:"))
async def admin_dates_page(call: CallbackQuery, settings: Settings, session_factory):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    page = int(call.data.split(":", 1)[1])
    if page < 0:
        page = 0
    db = session_factory()
    try:
        all_dates = get_post_dates(db)
    finally:
        db.close()
    max_page = max(0, (len(all_dates) - 1) // PAGE_SIZE) if all_dates else 0
    page = min(page, max_page)
    chunk = all_dates[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    await call.message.edit_text(
        "🗓 <b>Посты по датам</b>\n\nВыберите дату:",
        reply_markup=dates_kb(chunk, page=page, has_prev=page > 0, has_next=page < max_page),
    )
    await call.answer()


@admin_router.callback_query(F.data == "admin:levels")
async def admin_levels(call: CallbackQuery, settings: Settings):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.edit_text("🎚 <b>Посты по уровням</b>\n\nВыберите уровень:", reply_markup=levels_kb())
    await call.answer()


@admin_router.callback_query(F.data.startswith("adate:"))
async def open_date_posts(call: CallbackQuery, settings: Settings, session_factory):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    date_str = call.data.split(":", 1)[1]
    # render page 0 for this date
    await _render_posts_list(call, settings, session_factory=session_factory, ctx="d", ctx_value=date_str, page=0)
    await call.answer()


@admin_router.callback_query(F.data.startswith("alevel:"))
async def open_level_posts(call: CallbackQuery, settings: Settings, session_factory):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    level = call.data.split(":", 1)[1]
    await _render_posts_list(call, settings, session_factory=session_factory, ctx="l", ctx_value=level, page=0)
    await call.answer()


@admin_router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


@admin_router.callback_query(F.data.startswith("plist:"))
async def posts_page(call: CallbackQuery, settings: Settings, session_factory):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return

    _, ctx, ctx_value, page_raw = call.data.split(":", 3)
    page = int(page_raw)
    await _render_posts_list(call, settings, session_factory=session_factory, ctx=ctx, ctx_value=ctx_value, page=page)
    await call.answer()


async def _render_posts_list(
    call: CallbackQuery,
    settings: Settings,
    *,
    ctx: str,
    ctx_value: str,
    page: int,
    session_factory,
) -> None:
    """
    ctx:
      - "d": date (YYYY-MM-DD)
      - "l": level (all/starters/explorers/achievers)
    """
    if page < 0:
        page = 0

    db = session_factory()
    try:
        if ctx == "d":
            total = count_posts_by_date(db, ctx_value)
            max_page = max(0, (total - 1) // PAGE_SIZE) if total else 0
            page = min(page, max_page)
            offset = page * PAGE_SIZE
            posts = get_posts_by_date(db, ctx_value, limit=PAGE_SIZE, offset=offset)
            back_cb = "admin:dates"
            title = f"🗓 <b>Посты за {ctx_value}</b>"
        else:
            total = count_posts_by_level(db, ctx_value)
            max_page = max(0, (total - 1) // PAGE_SIZE) if total else 0
            page = min(page, max_page)
            offset = page * PAGE_SIZE
            posts = get_posts_by_level(db, ctx_value, limit=PAGE_SIZE, offset=offset)
            back_cb = "admin:levels"
            title = f"🎚 <b>Посты уровня {ctx_value}</b>"
    finally:
        db.close()

    if not posts:
        await call.message.edit_text("Постов не найдено.", reply_markup=admin_menu_kb())
        return

    has_prev = page > 0
    has_next = page < max_page
    await call.message.edit_text(
        title,
        reply_markup=posts_list_kb(
            posts,
            settings.tz,
            back_cb=back_cb,
            ctx=ctx,
            ctx_value=ctx_value,
            page=page,
            has_prev=has_prev,
            has_next=has_next,
        ),
    )


@admin_router.callback_query(F.data == "admin:create")
async def admin_create(call: CallbackQuery, settings: Settings, state: FSMContext):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await state.set_state(CreatePostFSM.title)
    await call.message.edit_text("Введите <b>название</b> поста (для списка кнопок):")
    await call.answer()


@admin_router.message(CreatePostFSM.title)
async def create_title(message: Message, state: FSMContext, settings: Settings):
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не должно быть пустым. Введите название ещё раз:")
        return
    await state.update_data(title=title)
    await state.set_state(CreatePostFSM.level)
    await message.answer("Выберите <b>уровень</b> для поста:", reply_markup=admin_post_level_kb())


@admin_router.callback_query(F.data.startswith("plevel:"), CreatePostFSM.level)
async def create_pick_level(call: CallbackQuery, settings: Settings, state: FSMContext):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    level = call.data.split(":", 1)[1]
    if level != "all" and level not in LEVELS:
        await call.answer("Неизвестный уровень", show_alert=True)
        return
    await state.update_data(level=level)
    await state.set_state(CreatePostFSM.content)
    await call.message.edit_text(
        f"Ок, уровень: <b>{level}</b>\n\n"
        "Теперь отправьте <b>сообщение поста</b> (текст / фото / видео / кружочек / аудио / голос):"
    )
    await call.answer()


@admin_router.message(CreatePostFSM.content)
async def create_content(message: Message, state: FSMContext, settings: Settings):
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        return
    text, media_type, file_id = _extract_message_content(message)
    if not text.strip() and not file_id:
        await message.answer("Сообщение пустое. Пришлите текст или медиа ещё раз:")
        return
    await state.update_data(text=text, media_type=media_type, file_id=file_id)
    await state.set_state(CreatePostFSM.send_at)
    await message.answer(
        "Введите <b>время отправки</b> в формате:\n"
        "<code>YYYY-MM-DD HH:MM</code>\n\n"
        f"Часовой пояс: <b>{settings.tz}</b>"
    )


@admin_router.message(CreatePostFSM.send_at)
async def create_send_at(message: Message, state: FSMContext, settings: Settings, session_factory, scheduler: AsyncIOScheduler):
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        return
    try:
        send_at = parse_moscow_datetime(message.text or "", settings.tz)
    except Exception:
        await message.answer("Не понял дату/время. Формат: <code>YYYY-MM-DD HH:MM</code>. Попробуйте ещё раз:")
        return

    data = await state.get_data()
    title = data["title"]
    text = data["text"]
    level = data.get("level", "all")
    media_type = data.get("media_type")
    file_id = data.get("file_id")

    db = session_factory()
    try:
        post = create_post(db, title=title, text=text, send_at=send_at, level=level)
        post = update_post_content(db, post.id, text=text, media_type=media_type, file_id=file_id) or post
    finally:
        db.close()

    schedule_or_send_now(bot=message.bot, scheduler=scheduler, session_factory=session_factory, post=post, tz=settings.tz)

    await state.clear()
    await message.answer(
        f"✅ Создан пост <b>#{post.id}</b>\n"
        f"🎚 {post.level}\n"
        f"⏰ {format_dt(post.send_at, settings.tz)}",
        reply_markup=post_actions_kb(post.id, back_cb="admin:back"),
    )


@admin_router.callback_query(F.data.startswith("post:"))
async def open_post(call: CallbackQuery, settings: Settings, session_factory):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    parts = call.data.split(":")
    post_id = int(parts[1])
    back_cb = "admin:back"
    if len(parts) == 5:
        _, _, ctx, ctx_value, page = parts
        back_cb = f"plist:{ctx}:{ctx_value}:{page}"
    db = session_factory()
    try:
        post = get_post(db, post_id)
    finally:
        db.close()
    if not post:
        await call.answer("Пост не найден", show_alert=True)
        return

    status = "✅ отправлен" if post.sent else "🕒 ожидает"
    media = (post.media_type or "text")
    await call.message.edit_text(
        f"<b>Пост #{post.id}</b> ({status})\n"
        f"⏰ {format_dt(post.send_at, settings.tz)}\n"
        f"🎚 {post.level}\n"
        f"📎 {media}\n"
        f"📝 <b>{post.title or '(без названия)'}</b>\n\n"
        f"{post.text}",
        reply_markup=post_actions_kb(post.id, back_cb=back_cb),
    )
    # Send media preview (photo/video/voice/video_note/etc) as separate message
    try:
        await _send_post_preview(call.message, post)
    except Exception:
        pass
    await call.answer()


@admin_router.callback_query(F.data.startswith("pact:"))
async def post_action(call: CallbackQuery, settings: Settings, state: FSMContext, session_factory, scheduler: AsyncIOScheduler):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return

    _, action, post_id_raw = call.data.split(":", 2)
    post_id = int(post_id_raw)

    if action == "del":
        await call.message.edit_text("Точно удалить пост?", reply_markup=confirm_delete_kb(post_id))
        await call.answer()
        return

    if action == "del_yes":
        unschedule_post(scheduler, post_id)
        db = session_factory()
        try:
            ok = delete_post(db, post_id)
        finally:
            db.close()
        await call.message.edit_text("✅ Удалено." if ok else "Пост уже удалён.", reply_markup=admin_menu_kb())
        await call.answer()
        return

    if action == "del_no":
        # show post again
        await open_post(call, settings, session_factory)
        return

    await state.clear()
    await state.update_data(post_id=post_id)

    if action == "title":
        await state.set_state(EditPostFSM.title)
        await call.message.edit_text("Введите новое <b>название</b> поста:")
    elif action == "level":
        await state.set_state(EditPostFSM.level)
        await call.message.edit_text("Выберите новый <b>уровень</b> для поста:", reply_markup=admin_post_level_kb())
    elif action == "content":
        await state.set_state(EditPostFSM.content)
        await call.message.edit_text("Пришлите новое <b>сообщение поста</b> (текст / фото / видео / кружочек / аудио / голос):")
    elif action == "text":
        await state.set_state(EditPostFSM.text)
        await call.message.edit_text("Введите новый <b>текст/подпись</b> поста (для медиа это будет caption):")
    elif action == "time":
        await state.set_state(EditPostFSM.send_at)
        await call.message.edit_text(
            "Введите новое <b>время отправки</b>:\n"
            "<code>YYYY-MM-DD HH:MM</code>\n\n"
            f"Часовой пояс: <b>{settings.tz}</b>"
        )
    else:
        await call.answer("Неизвестное действие", show_alert=True)
        return

    await call.answer()


@admin_router.callback_query(F.data.startswith("plevel:"), EditPostFSM.level)
async def edit_pick_level(call: CallbackQuery, settings: Settings, state: FSMContext, session_factory):
    if not _is_admin(call.from_user.id, settings):
        await call.answer("Нет доступа", show_alert=True)
        return
    level = call.data.split(":", 1)[1]
    if level != "all" and level not in LEVELS:
        await call.answer("Неизвестный уровень", show_alert=True)
        return

    data = await state.get_data()
    post_id = int(data["post_id"])
    db = session_factory()
    try:
        post = update_post_level(db, post_id, level=level)
    finally:
        db.close()

    await state.clear()
    if not post:
        await call.message.edit_text("Пост не найден.", reply_markup=admin_menu_kb())
        await call.answer()
        return
    await call.message.edit_text(
        f"✅ Уровень обновлён: <b>{post.level}</b>\n\n"
        f"<b>Пост #{post.id}</b>\n"
        f"⏰ {format_dt(post.send_at, settings.tz)}\n"
        f"🎚 {post.level}\n"
        f"📝 <b>{post.title or '(без названия)'}</b>\n\n"
        f"{post.text}",
        reply_markup=post_actions_kb(post.id),
    )
    await call.answer("Сохранено ✅")


@admin_router.message(EditPostFSM.title)
async def edit_title(message: Message, state: FSMContext, settings: Settings, session_factory):
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не должно быть пустым. Введите ещё раз:")
        return
    data = await state.get_data()
    post_id = int(data["post_id"])
    db = session_factory()
    try:
        post = update_post_text_title(db, post_id, title=title)
    finally:
        db.close()
    await state.clear()
    await message.answer("✅ Название обновлено.")
    # show updated
    if post:
        await message.answer(
            f"<b>Пост #{post.id}</b>\n"
            f"⏰ {format_dt(post.send_at, settings.tz)}\n"
            f"📝 <b>{post.title}</b>\n\n"
            f"{post.text}",
            reply_markup=post_actions_kb(post.id),
        )


@admin_router.message(EditPostFSM.text)
async def edit_text(message: Message, state: FSMContext, settings: Settings, session_factory):
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        return
    # Preserve Telegram formatting: store HTML-rendered text (entities -> HTML)
    text = message.html_text or message.text or ""
    if not text.strip():
        await message.answer("Текст не должен быть пустым. Введите ещё раз:")
        return
    data = await state.get_data()
    post_id = int(data["post_id"])
    db = session_factory()
    try:
        post = update_post_text_title(db, post_id, text=text)
    finally:
        db.close()
    await state.clear()
    await message.answer("✅ Текст обновлён.")
    if post:
        await message.answer(
            f"<b>Пост #{post.id}</b>\n"
            f"⏰ {format_dt(post.send_at, settings.tz)}\n"
            f"📝 <b>{post.title or '(без названия)'}</b>\n\n"
            f"{post.text}",
            reply_markup=post_actions_kb(post.id),
        )


@admin_router.message(EditPostFSM.content)
async def edit_content(message: Message, state: FSMContext, settings: Settings, session_factory):
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        return
    text, media_type, file_id = _extract_message_content(message)
    if not text.strip() and not file_id:
        await message.answer("Сообщение пустое. Пришлите текст или медиа ещё раз:")
        return
    data = await state.get_data()
    post_id = int(data["post_id"])
    db = session_factory()
    try:
        post = update_post_content(db, post_id, text=text, media_type=media_type, file_id=file_id)
    finally:
        db.close()
    await state.clear()
    await message.answer("✅ Контент обновлён.")
    if post:
        media = post.media_type or "text"
        await message.answer(
            f"<b>Пост #{post.id}</b>\n"
            f"⏰ {format_dt(post.send_at, settings.tz)}\n"
            f"🎚 {post.level}\n"
            f"📎 {media}\n"
            f"📝 <b>{post.title or '(без названия)'}</b>\n\n"
            f"{post.text}",
            reply_markup=post_actions_kb(post.id),
        )
        try:
            await _send_post_preview(message, post)
        except Exception:
            pass


@admin_router.message(EditPostFSM.send_at)
async def edit_send_at(message: Message, state: FSMContext, settings: Settings, session_factory, scheduler: AsyncIOScheduler):
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        return
    try:
        send_at = parse_moscow_datetime(message.text or "", settings.tz)
    except Exception:
        await message.answer("Не понял дату/время. Формат: <code>YYYY-MM-DD HH:MM</code>. Попробуйте ещё раз:")
        return

    data = await state.get_data()
    post_id = int(data["post_id"])

    db = session_factory()
    try:
        post = update_post_send_time(db, post_id, send_at=send_at)
    finally:
        db.close()

    await state.clear()

    if not post:
        await message.answer("Пост не найден.")
        return

    schedule_or_send_now(bot=message.bot, scheduler=scheduler, session_factory=session_factory, post=post, tz=settings.tz)
    await message.answer(f"✅ Время обновлено: ⏰ {format_dt(post.send_at, settings.tz)}", reply_markup=post_actions_kb(post.id))


