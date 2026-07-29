from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_returns_ok_without_auth():
    response = client.get("/api/v1/health")

    assert response.status_code == 200

    body = response.json()
    assert "data" in body

    data = body["data"]
    assert data["status"] == "ok"
    assert "timestamp" in data

    timestamp = datetime.fromisoformat(data["timestamp"])
    assert timestamp.utcoffset() is not None
    assert timestamp.utcoffset().total_seconds() == 9 * 3600
