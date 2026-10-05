import httpx
import pytest

from app import db, gaggiuino
from conftest import recipe_form


def transport(handler):
    return httpx.MockTransport(handler)


def test_fetch_profiles():
    def handler(request):
        assert request.url == "http://gaggia/api/profiles/all"
        return httpx.Response(
            200,
            json=[
                {"id": 1, "name": "Napoli 3", "selected": "false"},
                {"id": 2, "name": " 7 bar curve ", "selected": "true"},
                {"id": 3, "name": ""},
                "junk",
            ],
        )

    assert gaggiuino.fetch_profiles("http://gaggia/", transport=transport(handler)) == [
        {"id": "1", "name": "Napoli 3"},
        {"id": "2", "name": "7 bar curve"},
    ]


def test_fetch_profiles_timeout():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(gaggiuino.GaggiuinoError, match="not reachable"):
        gaggiuino.fetch_profiles("http://gaggia", transport=transport(handler))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"error": "nope"}),
        httpx.Response(404),
    ],
)
def test_fetch_profiles_malformed(response):
    with pytest.raises(gaggiuino.GaggiuinoError):
        gaggiuino.fetch_profiles("http://gaggia", transport=transport(lambda request: response))


def test_refresh_merges_into_cache_by_name(client, espresso, monkeypatch):
    with db.connect() as conn:
        napoli = db.find_or_create_profile(conn, "Napoli 3")
    client.post("/recipes", data=recipe_form(espresso, profile_id=str(napoli)))

    machine = [{"id": "7", "name": "napoli 3"}, {"id": "8", "name": "Roma"}]
    monkeypatch.setattr(gaggiuino, "fetch_profiles", lambda url: machine)
    result = client.post("/profiles/refresh").json()

    assert result["ok"]
    assert result["profiles"] == [{"id": napoli, "name": "napoli 3"}, {"id": napoli + 1, "name": "Roma"}]
    with db.connect() as conn:
        assert db.get_recipe(conn, 1)["profile"] == "napoli 3"


def test_refresh_falls_back_to_cache_when_machine_is_off(client, monkeypatch):
    with db.connect() as conn:
        db.find_or_create_profile(conn, "Napoli 3")

    def unreachable(url):
        raise gaggiuino.GaggiuinoError("Gaggiuino not reachable at http://gaggiuino.local")

    monkeypatch.setattr(gaggiuino, "fetch_profiles", unreachable)
    result = client.post("/profiles/refresh").json()

    assert not result["ok"]
    assert "not reachable" in result["error"]
    assert [p["name"] for p in result["profiles"]] == ["Napoli 3"]
