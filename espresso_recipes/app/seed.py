from . import db

METHODS = ("Espresso", "Drip")

# The recipes from the iOS note this app replaces.
RECIPES = (
    {
        "name": "Kimbo Barista Espresso Napoli",
        "method": "Espresso",
        "grind_setting": "0.4",
        "dose_g": 16.5,
        "yield_g": 26,
        "temperature_c": 92,
        "profile": "Napoli 3",
        "basket": "Lelit 18g",
    },
    {
        "name": "Kimbo Pompei",
        "method": "Espresso",
        "grind_setting": "0.1",
        "dose_g": 18,
        "yield_g": 26,
        "profile": "Napoli 3",
        "basket": "Gaggia standard",
    },
    {
        "name": "Hayb Konesso Milk Blend",
        "method": "Espresso",
        "grind_setting": "0.2",
        "dose_g": 18,
        "yield_g": 36,
        "profile": "7 bar curve",
        "basket": "IMS Competizione",
    },
    {
        "name": "Arcaffe Roma",
        "method": "Espresso",
        "grind_setting": "0.5",
        "dose_g": 18,
        "yield_g": 36,
        "profile_text": "Roma Profile?",
        "basket": "IMS Competizione",
    },
    {
        "name": "Finca Milan Colombian Paradise",
        "method": "Drip",
        "grind_setting": "14",
    },
)


def seed(conn, recipes=True):
    for method in METHODS:
        db.find_or_create_equipment(conn, "method", method)
    if not recipes:
        return
    for recipe in RECIPES:
        data = dict(recipe)
        data["method_id"] = db.find_or_create_equipment(conn, "method", data.pop("method"))
        if "basket" in data:
            data["basket_id"] = db.find_or_create_equipment(conn, "basket", data.pop("basket"))
        if "profile" in data:
            data["profile_id"] = db.find_or_create_profile(conn, data.pop("profile"))
        db.save_recipe(conn, None, data, "Imported from notes")
