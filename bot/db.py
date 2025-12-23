import datetime as dt
import os
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


Level = str  # "starters" | "explorers" | "achievers"
PostLevel = str  # "all" | Level


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    level: Mapped[Optional[Level]] = mapped_column(String(20), nullable=True, index=True)
    joined_at: Mapped[dt.datetime] = mapped_column(DateTime(), default=lambda: dt.datetime.now())


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    level: Mapped[PostLevel] = mapped_column(String(20), default="all", nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    file_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    send_at: Mapped[dt.datetime] = mapped_column(DateTime(), nullable=False, index=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    sent_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(), default=lambda: dt.datetime.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(), default=lambda: dt.datetime.now())


def make_engine(database_url: str):
    # Ensure local folder exists for sqlite relative path
    if database_url.startswith("sqlite:///./"):
        os.makedirs("bot_data", exist_ok=True)
    return create_engine(database_url, future=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session, future=True)


def init_db(engine) -> None:
    os.makedirs("bot_data", exist_ok=True)
    Base.metadata.create_all(bind=engine)

    # Simple compatibility check: if an old schema exists (from previous iterations),
    # recreate our tables to avoid runtime "no such column" errors.
    try:
        with engine.connect() as conn:
            def table_columns(table: str) -> set[str]:
                rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
                return {r[1] for r in rows}  # (cid, name, type, notnull, dflt_value, pk)

            # posts
            posts_cols = table_columns("posts")
            expected_posts = {"id", "title", "level", "text", "media_type", "file_id", "send_at", "sent", "sent_at", "created_at", "updated_at"}
            if posts_cols and not expected_posts.issubset(posts_cols):
                conn.exec_driver_sql("DROP TABLE IF EXISTS posts")

            # users
            users_cols = table_columns("users")
            expected_users = {"id", "telegram_id", "level", "joined_at"}
            if users_cols and not expected_users.issubset(users_cols):
                conn.exec_driver_sql("DROP TABLE IF EXISTS users")

            conn.commit()
    except Exception:
        # don't block startup if PRAGMA isn't available (non-sqlite)
        pass

    Base.metadata.create_all(bind=engine)


def upsert_user(db: Session, telegram_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if user:
        return user
    user = User(telegram_id=telegram_id)
    db.add(user)
    db.commit()
    return user


def set_user_level(db: Session, telegram_id: int, level: Level) -> User:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        user = User(telegram_id=telegram_id, level=level)
        db.add(user)
        db.commit()
        return user
    user.level = level
    db.commit()
    return user


def get_all_users(db: Session) -> list[User]:
    return list(db.scalars(select(User)))


def get_users_by_level(db: Session, level: Level) -> list[User]:
    return list(db.scalars(select(User).where(User.level == level)))


def count_users(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(User)) or 0)


def create_post(db: Session, title: str, text: str, send_at: dt.datetime, level: PostLevel = "all") -> Post:
    post = Post(title=title.strip(), text=text, send_at=send_at, level=level, sent=False, media_type=None, file_id=None)
    db.add(post)
    db.commit()
    return post


def get_post(db: Session, post_id: int) -> Optional[Post]:
    return db.scalar(select(Post).where(Post.id == post_id))


def get_posts(db: Session, limit: int = 50) -> list[Post]:
    stmt = select(Post).order_by(Post.send_at.desc(), Post.id.desc()).limit(limit)
    return list(db.scalars(stmt))


def get_post_dates(db: Session) -> list[str]:
    """
    Returns distinct send_at dates as YYYY-MM-DD strings (sorted desc).
    SQLite-compatible via func.date().
    """
    stmt = select(func.date(Post.send_at)).distinct().order_by(func.date(Post.send_at).desc())
    return [str(x) for x in db.scalars(stmt).all() if x]


def count_posts_by_date(db: Session, date_str: str) -> int:
    stmt = select(func.count()).select_from(Post).where(func.date(Post.send_at) == date_str)
    return int(db.scalar(stmt) or 0)


def get_posts_by_date(db: Session, date_str: str, *, limit: int, offset: int) -> list[Post]:
    stmt = (
        select(Post)
        .where(func.date(Post.send_at) == date_str)
        .order_by(Post.send_at.asc(), Post.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))


def count_posts_by_level(db: Session, level: PostLevel) -> int:
    stmt = select(func.count()).select_from(Post).where(Post.level == level)
    return int(db.scalar(stmt) or 0)


def get_posts_by_level(db: Session, level: PostLevel, *, limit: int, offset: int) -> list[Post]:
    stmt = (
        select(Post)
        .where(Post.level == level)
        .order_by(Post.send_at.asc(), Post.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))


def get_unsent_future_posts(db: Session, now: dt.datetime) -> list[Post]:
    stmt = select(Post).where(Post.sent == False, Post.send_at > now)  # noqa: E712
    return list(db.scalars(stmt))


def get_unsent_due_posts(db: Session, now: dt.datetime) -> list[Post]:
    stmt = select(Post).where(Post.sent == False, Post.send_at <= now)  # noqa: E712
    return list(db.scalars(stmt))


def update_post_text_title(db: Session, post_id: int, *, title: Optional[str] = None, text: Optional[str] = None) -> Optional[Post]:
    post = get_post(db, post_id)
    if not post:
        return None
    if title is not None:
        post.title = title.strip()
    if text is not None:
        post.text = text
    post.updated_at = dt.datetime.now()
    db.commit()
    return post


def update_post_content(
    db: Session,
    post_id: int,
    *,
    text: str,
    media_type: Optional[str],
    file_id: Optional[str],
) -> Optional[Post]:
    post = get_post(db, post_id)
    if not post:
        return None
    post.text = text
    post.media_type = media_type
    post.file_id = file_id
    post.updated_at = dt.datetime.now()
    db.commit()
    return post


def update_post_send_time(db: Session, post_id: int, send_at: dt.datetime) -> Optional[Post]:
    post = get_post(db, post_id)
    if not post:
        return None
    post.send_at = send_at
    post.sent = False
    post.sent_at = None
    post.updated_at = dt.datetime.now()
    db.commit()
    return post


def update_post_level(db: Session, post_id: int, level: PostLevel) -> Optional[Post]:
    post = get_post(db, post_id)
    if not post:
        return None
    post.level = level
    post.updated_at = dt.datetime.now()
    db.commit()
    return post


def delete_post(db: Session, post_id: int) -> bool:
    post = get_post(db, post_id)
    if not post:
        return False
    db.delete(post)
    db.commit()
    return True


def mark_post_sent(db: Session, post_id: int, sent_at: dt.datetime) -> None:
    post = get_post(db, post_id)
    if not post:
        return
    post.sent = True
    post.sent_at = sent_at
    post.updated_at = dt.datetime.now()
    db.commit()
