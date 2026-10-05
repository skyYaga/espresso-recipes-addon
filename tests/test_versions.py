from app import db
from conftest import recipe_form


def history():
    with db.connect() as conn:
        return db.history(conn, 1)


def test_changed_save_adds_one_version(client, espresso):
    client.post("/recipes", data=recipe_form(espresso))
    client.post(
        "/recipes/1", data=recipe_form(espresso, grind_setting="0.3", change_note="too sour")
    )
    newest, initial = history()
    assert newest["change_note"] == "too sour"
    assert newest["changes"] == [{"label": "Grind", "old": "0.4", "new": "0.3"}]
    assert initial["is_initial"]

    page = " ".join(client.get("/recipes/1").text.split())
    assert "0.4 → 0.3" in page
    assert "too sour" in page


def test_unchanged_save_and_rename_add_no_version(client, espresso):
    client.post("/recipes", data=recipe_form(espresso))
    client.post("/recipes/1", data=recipe_form(espresso))
    client.post("/recipes/1", data=recipe_form(espresso, name="Renamed"))
    assert len(history()) == 1


def test_restore_adds_new_version_with_old_values(client, espresso):
    client.post("/recipes", data=recipe_form(espresso))
    client.post("/recipes/1", data=recipe_form(espresso, grind_setting="0.3", dose_g="17,5"))
    initial_id = history()[-1]["id"]

    client.post(f"/recipes/1/versions/{initial_id}/restore")

    with db.connect() as conn:
        recipe = db.get_recipe(conn, 1)
    assert (recipe["grind_setting"], recipe["dose_g"]) == ("0.4", 18)
    entries = history()
    assert len(entries) == 3
    assert entries[0]["change_note"].startswith("Restored version from ")
    assert {"label": "Dose", "old": "17.5 g", "new": "18 g"} in entries[0]["changes"]


def test_restore_of_other_recipes_version_is_rejected(client, espresso):
    client.post("/recipes", data=recipe_form(espresso))
    client.post("/recipes", data=recipe_form(espresso, name="Other"))
    other_version = 2
    assert client.post(f"/recipes/1/versions/{other_version}/restore").status_code == 404


def test_history_survives_equipment_rename(client, espresso):
    client.post("/recipes", data=recipe_form(espresso, basket_id="new", basket_new="Lelit"))
    with db.connect() as conn:
        basket_id = db.get_recipe(conn, 1)["basket_id"]
    client.post("/recipes/1", data=recipe_form(espresso, basket_id=""))
    client.post(f"/equipment/{basket_id}", data={"name": "Lelit 18g"})

    newest, initial = history()
    assert newest["changes"] == [{"label": "Basket", "old": "Lelit", "new": "–"}]

    # Restoring reattaches the same basket, under its current name.
    client.post(f"/recipes/1/versions/{initial['id']}/restore")
    with db.connect() as conn:
        recipe = db.get_recipe(conn, 1)
    assert (recipe["basket_id"], recipe["basket"]) == (basket_id, "Lelit 18g")
