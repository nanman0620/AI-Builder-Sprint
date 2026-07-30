import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise RuntimeError("네트워크 접근이 테스트에서 시도됨 — mocking 누락 가능성이 있다.")

    monkeypatch.setattr("urllib.request.urlopen", _blocked)
