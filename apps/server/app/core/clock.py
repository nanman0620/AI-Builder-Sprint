from datetime import datetime
from zoneinfo import ZoneInfo

_SEOUL_TZ = ZoneInfo("Asia/Seoul")


def get_current_moment() -> datetime:
    return datetime.now(_SEOUL_TZ)
