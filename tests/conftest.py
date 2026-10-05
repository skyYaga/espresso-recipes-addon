import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(create_app(seed_recipes=False)) as client:
        yield client


@pytest.fixture
def espresso(client):
    with db.connect() as conn:
        return db.find_or_create_equipment(conn, "method", "Espresso")


def recipe_form(method_id, **overrides):
    form = {
        "name": "Kimbo",
        "method_id": str(method_id),
        "grinder_id": "",
        "basket_id": "",
        "profile_id": "",
        "grind_setting": "0.4",
        "dose_g": "18",
        "yield_g": "36",
        "temperature_c": "",
        "notes": "",
    }
    form.update(overrides)
    return form
