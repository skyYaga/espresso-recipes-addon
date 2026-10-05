from fastapi.testclient import TestClient

from app import db
from app.main import create_app
from conftest import recipe_form


def recipes():
    with db.connect() as conn:
        return [dict(r) for r in db.list_recipes(conn)]


def test_create_accepts_decimal_comma(client, espresso):
    response = client.post("/recipes", data=recipe_form(espresso, dose_g="16,5", temperature_c="92"))
    assert response.status_code == 200
    (recipe,) = recipes()
    assert recipe["dose_g"] == 16.5
    assert recipe["temperature_c"] == 92
    assert "16.5 g in → 36 g out" in " ".join(client.get("/").text.split())


def test_create_rejects_bad_input(client, espresso):
    response = client.post("/recipes", data=recipe_form(espresso, name=" ", dose_g="lots"))
    assert response.status_code == 400
    assert "Name is required" in response.text
    assert "Dose must be a number" in response.text
    assert 'value="lots"' in response.text
    assert recipes() == []


def test_update(client, espresso):
    client.post("/recipes", data=recipe_form(espresso))
    client.post("/recipes/1", data=recipe_form(espresso, name="Kimbo Pompei", grind_setting="0.1"))
    (recipe,) = recipes()
    assert (recipe["name"], recipe["grind_setting"]) == ("Kimbo Pompei", "0.1")


def test_inline_new_equipment_and_free_text_profile(client, espresso):
    form = recipe_form(
        espresso, basket_id="new", basket_new="IMS Competizione", profile_id="other", profile_text="Roma?"
    )
    client.post("/recipes", data=form)
    client.post("/recipes", data={**form, "name": "Second"})
    first, second = recipes()
    assert first["basket"] == "IMS Competizione"
    assert first["profile"] == "Roma?"
    assert first["basket_id"] == second["basket_id"]


def test_archive_hides_and_delete_removes(client, espresso):
    client.post("/recipes", data=recipe_form(espresso))
    client.post("/recipes/1/archive")
    assert recipes() == []
    assert "Kimbo" not in client.get("/").text
    assert "Kimbo" in client.get("/?archived=true").text

    client.post("/recipes/1/delete")
    assert "Kimbo" not in client.get("/?archived=true").text
    with db.connect() as conn:
        assert db.list_versions(conn, 1) == []


def test_duplicate(client, espresso):
    client.post("/recipes", data=recipe_form(espresso))
    client.post("/recipes/1/duplicate")
    original, copy = recipes()
    assert copy["name"] == "Kimbo (copy)"
    assert copy["grind_setting"] == original["grind_setting"]
    with db.connect() as conn:
        assert len(db.list_versions(conn, copy["id"])) == 1


def test_archived_equipment_stays_on_its_recipe(client, espresso):
    client.post("/recipes", data=recipe_form(espresso, basket_id="new", basket_new="Lelit 18g"))
    basket_id = recipes()[0]["basket_id"]
    client.post(f"/equipment/{basket_id}/archive")
    assert "Lelit 18g" in client.get("/recipes/1").text
    assert "Lelit 18g" not in client.get("/recipes/new").text


def test_equipment_rename_conflict(client, espresso):
    client.post("/equipment", data={"kind": "basket", "name": "A"})
    client.post("/equipment", data={"kind": "basket", "name": "B"})
    with db.connect() as conn:
        a, b = db.list_equipment(conn, "basket")
    response = client.post(f"/equipment/{b['id']}", data={"name": "a"})
    assert response.status_code == 400
    assert "already exists" in response.text


def test_ingress_prefix_on_links_and_redirects(client, espresso):
    headers = {"X-Ingress-Path": "/api/hassio_ingress/token"}
    page = client.get("/", headers=headers).text
    assert 'href="/api/hassio_ingress/token/static/app.css"' in page
    assert 'href="/api/hassio_ingress/token/recipes/new"' in page

    response = client.post(
        "/recipes", data=recipe_form(espresso), headers=headers, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/api/hassio_ingress/token/recipes/1"
    assert 'action="/api/hassio_ingress/token/recipes/1"' in client.get("/recipes/1", headers=headers).text


def test_ingress_only_rejects_other_clients(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INGRESS_ONLY", "1")
    with TestClient(create_app(seed_recipes=False)) as client:
        assert client.get("/").status_code == 403
    with TestClient(create_app(seed_recipes=False), client=("172.30.32.2", 50000)) as client:
        assert client.get("/").status_code == 200


def test_first_start_imports_notes_once(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for _ in range(2):
        with TestClient(create_app()) as client:
            page = client.get("/").text
    assert len(recipes()) == 5
    assert page.index("Espresso") < page.index("Drip")
    assert "Roma Profile?" in page

    export = client.get("/export.json").json()
    assert len(export["recipe"]) == 5
    assert len(export["recipe_version"]) == 5
