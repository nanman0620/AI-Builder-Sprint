import asyncio
from contextlib import asynccontextmanager

import pytest

from app.main import _app_lifespan


def test_app_lifespan_raises_when_solar_api_key_missing(monkeypatch):
    monkeypatch.delenv("SOLAR_API_KEY", raising=False)

    async def _run():
        async with _app_lifespan("fake-app"):
            pass

    with pytest.raises(RuntimeError):
        asyncio.run(_run())


def test_app_lifespan_starts_check_in_lifespan_when_key_present(monkeypatch):
    monkeypatch.setenv("SOLAR_API_KEY", "dummy-key")
    calls = []

    @asynccontextmanager
    async def _fake_check_in_lifespan(app):
        calls.append(app)
        yield

    monkeypatch.setattr("app.main.check_in_lifespan", _fake_check_in_lifespan)

    async def _run():
        async with _app_lifespan("fake-app"):
            pass

    asyncio.run(_run())

    assert calls == ["fake-app"]
