from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

router = APIRouter()

_SEOUL_TZ = ZoneInfo("Asia/Seoul")


@router.get("/health")
def get_health() -> dict:
    return {
        "data": {
            "status": "ok",
            "timestamp": datetime.now(_SEOUL_TZ).isoformat(),
        }
    }
