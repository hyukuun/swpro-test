from app.config import ENGINE_VERSION
from tests.helpers import client


def test_health():
    assert client.get("/health").json() == {"status": "ok", "engineVersion": ENGINE_VERSION}
