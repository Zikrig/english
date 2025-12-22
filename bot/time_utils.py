import datetime as dt


def format_dt(d: dt.datetime, tz: str) -> str:
    # We store datetimes as naive (local time), so just format them.
    # `tz` is kept for UI clarity / future extension.
    return d.strftime("%Y-%m-%d %H:%M")


def parse_moscow_datetime(text: str, tz: str) -> dt.datetime:
    """
    Parses 'YYYY-MM-DD HH:MM' in provided timezone and returns naive datetime.
    """
    raw = text.strip()
    value = dt.datetime.strptime(raw, "%Y-%m-%d %H:%M")
    return value


