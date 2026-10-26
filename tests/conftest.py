from pathlib import Path

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path: Path):
    fixtures = Path(__file__).parents[1] / "fixtures" / "contracts"
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "DATABASE": str(tmp_path / "test.sqlite3"),
        "FIXTURES_PATH": str(fixtures),
        "DRY_RUN": True,
        "CONTRACT_SOURCE": "fixture",
    })


@pytest.fixture
def client(app):
    return app.test_client()
