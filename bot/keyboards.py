from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.time_utils import format_dt

LEVELS = {
    "starters": "🌱 Начинающие / Starters",
    "explorers": "🚀 Продолжающие / Explorers",
    "achievers": "🌟 Продолжающие сильные / Achievers",
}

POST_LEVELS = {
    **LEVELS,
    "admins": "АДМИНЫ (тест)",
}


def admin_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Создать пост", callback_data="admin:create"))
    kb.row(InlineKeyboardButton(text="🎁 Сюрприз (кнопка Открыть)", callback_data="admin:teaser"))
    kb.row(InlineKeyboardButton(text="🗓 Посты по датам", callback_data="admin:dates"))
    kb.row(InlineKeyboardButton(text="🎚 Посты по уровням", callback_data="admin:levels"))
    return kb.as_markup()


def open_post_kb(post_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Открыть", callback_data=f"openpost:{post_id}"))
    return kb.as_markup()


def posts_list_kb(posts, tz: str, *, back_cb: str, ctx: str, ctx_value: str, page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for post in posts:
        title = (post.title or "").strip() or "(без названия)"
        when = format_dt(post.send_at, tz)
        lvl = getattr(post, "level", "all")
        label = f"#{post.id} · {when} · {lvl} · {title}"
        if len(label) > 60:
            label = label[:57] + "..."
        kb.row(InlineKeyboardButton(text=label, callback_data=f"post:{post.id}:{ctx}:{ctx_value}:{page}"))

    nav = InlineKeyboardBuilder()
    if has_prev:
        nav.add(InlineKeyboardButton(text="⬅️", callback_data=f"plist:{ctx}:{ctx_value}:{page-1}"))
    nav.add(InlineKeyboardButton(text=f"{page+1}", callback_data="noop"))
    if has_next:
        nav.add(InlineKeyboardButton(text="➡️", callback_data=f"plist:{ctx}:{ctx_value}:{page+1}"))
    kb.row(*nav.buttons)

    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb))
    return kb.as_markup()


def post_actions_kb(post_id: int, *, back_cb: str = "admin:back") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✏️ Название", callback_data=f"pact:title:{post_id}"))
    kb.row(InlineKeyboardButton(text="🎚 Уровень", callback_data=f"pact:level:{post_id}"))
    kb.row(InlineKeyboardButton(text="📎 Контент", callback_data=f"pact:content:{post_id}"))
    kb.row(InlineKeyboardButton(text="✏️ Текст/подпись", callback_data=f"pact:text:{post_id}"))
    kb.row(InlineKeyboardButton(text="🔊 Аудио", callback_data=f"pact:audio:{post_id}"))
    kb.row(InlineKeyboardButton(text="⏰ Время", callback_data=f"pact:time:{post_id}"))
    kb.row(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"pact:del:{post_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ К списку", callback_data=back_cb))
    return kb.as_markup()


def confirm_delete_kb(post_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"pact:del_yes:{post_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"pact:del_no:{post_id}"),
    )
    return kb.as_markup()


def user_level_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, label in LEVELS.items():
        kb.row(InlineKeyboardButton(text=label, callback_data=f"ulevel:{key}"))
    return kb.as_markup()


def admin_post_level_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🌍 Все уровни (all)", callback_data="plevel:all"))
    for key, label in POST_LEVELS.items():
        kb.row(InlineKeyboardButton(text=label, callback_data=f"plevel:{key}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:back"))
    return kb.as_markup()


def dates_kb(dates: list[str], *, page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in dates:
        kb.row(InlineKeyboardButton(text=d, callback_data=f"adate:{d}"))

    nav = InlineKeyboardBuilder()
    if has_prev:
        nav.add(InlineKeyboardButton(text="⬅️", callback_data=f"dpage:{page-1}"))
    nav.add(InlineKeyboardButton(text=f"{page+1}", callback_data="noop"))
    if has_next:
        nav.add(InlineKeyboardButton(text="➡️", callback_data=f"dpage:{page+1}"))
    kb.row(*nav.buttons)

    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:back"))
    return kb.as_markup()


def levels_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🌍 Все (all)", callback_data="alevel:all"))
    for key, label in POST_LEVELS.items():
        kb.row(InlineKeyboardButton(text=label, callback_data=f"alevel:{key}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:back"))
    return kb.as_markup()


