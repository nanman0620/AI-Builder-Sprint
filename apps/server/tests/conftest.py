import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise RuntimeError("네트워크 접근이 테스트에서 시도됨 — mocking 누락 가능성이 있다.")

    monkeypatch.setattr("urllib.request.urlopen", _blocked)


@pytest.fixture(autouse=True)
def default_solar_api_key(monkeypatch):
    """SOLAR_API_KEY startup 검증(app.main._app_lifespan)이나 get_solar_api_key()를 직접
    호출하는 테스트가 로컬 .env 유무와 무관하게 항상 통과하도록 기본값을 준다."""
    monkeypatch.setenv("SOLAR_API_KEY", "test-solar-api-key")
