from datetime import timedelta

from app.core.clock import get_current_moment


def test_get_current_moment_returns_timezone_aware_datetime():
    moment = get_current_moment()

    assert moment.tzinfo is not None
    assert moment.utcoffset() is not None


def test_get_current_moment_utcoffset_is_nine_hours():
    moment = get_current_moment()

    assert moment.utcoffset() == timedelta(hours=9)
