import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("method", "grinder", "basket")

# Fields tracked in recipe_version, with their display label and unit.
VERSION_FIELDS = {
    "grinder": ("Grinder", ""),
    "grind_setting": ("Grind", ""),
    "dose_g": ("Dose", " g"),
    "yield_g": ("Yield", " g"),
    "temperature_c": ("Temperature", " °C"),
    "profile": ("Profile", ""),
    "basket": ("Basket", ""),
    "notes": ("Notes", ""),
}

RECIPE_FIELDS = (
    "name",
    "method_id",
    "grinder_id",
    "grind_setting",
    "dose_g",
    "yield_g",
    "temperature_c",
    "profile_id",
    "profile_text",
    "basket_id",
    "notes",
)

SCHEMA = """
CREATE TABLE equipment (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('method', 'grinder', 'basket')),
    name TEXT NOT NULL COLLATE NOCASE,
    archived INTEGER NOT NULL DEFAULT 0,
    UNIQUE (kind, name)
);

CREATE TABLE profile (
    id INTEGER PRIMARY KEY,
    gaggiuino_id TEXT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    last_seen_at TEXT
);

CREATE TABLE recipe (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    method_id INTEGER NOT NULL REFERENCES equipment(id),
    grinder_id INTEGER REFERENCES equipment(id),
    grind_setting TEXT,
    dose_g REAL,
    yield_g REAL,
    temperature_c REAL,
    profile_id INTEGER REFERENCES profile(id),
    profile_text TEXT,
    basket_id INTEGER REFERENCES equipment(id),
    notes TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE recipe_version (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
    saved_at TEXT NOT NULL,
    change_note TEXT,
    grinder TEXT,
    grinder_id INTEGER,
    grind_setting TEXT,
    dose_g REAL,
    yield_g REAL,
    temperature_c REAL,
    profile TEXT,
    profile_id INTEGER,
    basket TEXT,
    basket_id INTEGER,
    notes TEXT
);
"""

RECIPE_SELECT = """
SELECT r.*, m.name AS method, g.name AS grinder, b.name AS basket,
       COALESCE(p.name, r.profile_text) AS profile
FROM recipe r
JOIN equipment m ON m.id = r.method_id
LEFT JOIN equipment g ON g.id = r.grinder_id
LEFT JOIN equipment b ON b.id = r.basket_id
LEFT JOIN profile p ON p.id = r.profile_id
"""


def db_path():
    return Path(os.environ.get("DATA_DIR", "/data")) / "recipes.db"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init():
    """Create the schema if needed. Returns True when the database is new."""
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        is_new = conn.execute("PRAGMA user_version").fetchone()[0] == 0
        if is_new:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA user_version = 1")
    return is_new


def fmt_num(value):
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value)


# Equipment


def list_equipment(conn, kind, include_id=None, with_archived=False):
    """Entries of one kind. Archived ones only if asked for or if `include_id` matches."""
    return conn.execute(
        "SELECT * FROM equipment WHERE kind = ? AND (archived = 0 OR ? OR id = ?) ORDER BY id",
        (kind, with_archived, include_id),
    ).fetchall()


def find_or_create_equipment(conn, kind, name):
    row = conn.execute(
        "SELECT id FROM equipment WHERE kind = ? AND name = ?", (kind, name)
    ).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        "INSERT INTO equipment (kind, name) VALUES (?, ?)", (kind, name)
    ).lastrowid


def rename_equipment(conn, equipment_id, name):
    conn.execute("UPDATE equipment SET name = ? WHERE id = ?", (name, equipment_id))


def toggle_equipment_archived(conn, equipment_id):
    conn.execute("UPDATE equipment SET archived = NOT archived WHERE id = ?", (equipment_id,))


# Profiles


def list_profiles(conn):
    return conn.execute("SELECT * FROM profile ORDER BY name").fetchall()


def find_or_create_profile(conn, name):
    row = conn.execute("SELECT id FROM profile WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO profile (name) VALUES (?)", (name,)).lastrowid


def upsert_profiles(conn, items):
    """Merge profiles reported by the machine into the cache.

    Matching is by name: the machine's ids are not guaranteed to be stable, and
    a recipe must never silently point at a different profile.
    """
    now = _now()
    for item in items:
        profile_id = find_or_create_profile(conn, item["name"])
        conn.execute(
            "UPDATE profile SET gaggiuino_id = ?, name = ?, last_seen_at = ? WHERE id = ?",
            (item["id"], item["name"], now, profile_id),
        )


# Recipes


def list_recipes(conn, archived=False):
    return conn.execute(
        RECIPE_SELECT + "WHERE r.archived = ? ORDER BY m.id, r.name COLLATE NOCASE",
        (archived,),
    ).fetchall()


def get_recipe(conn, recipe_id):
    return conn.execute(RECIPE_SELECT + "WHERE r.id = ?", (recipe_id,)).fetchone()


def _snapshot(row):
    return {field: row[field] for field in VERSION_FIELDS}


def save_recipe(conn, recipe_id, data, change_note=None):
    """Insert or update a recipe. Appends a version if a brewing field changed."""
    now = _now()
    values = {field: data.get(field) for field in RECIPE_FIELDS}
    before = None
    if recipe_id is None:
        columns = ", ".join(RECIPE_FIELDS)
        placeholders = ", ".join(f":{field}" for field in RECIPE_FIELDS)
        recipe_id = conn.execute(
            f"INSERT INTO recipe ({columns}, created_at, updated_at) "
            f"VALUES ({placeholders}, :now, :now)",
            {**values, "now": now},
        ).lastrowid
    else:
        before = _snapshot(get_recipe(conn, recipe_id))
        assignments = ", ".join(f"{field} = :{field}" for field in RECIPE_FIELDS)
        conn.execute(
            f"UPDATE recipe SET {assignments}, updated_at = :now WHERE id = :id",
            {**values, "now": now, "id": recipe_id},
        )

    row = get_recipe(conn, recipe_id)
    if _snapshot(row) != before:
        conn.execute(
            "INSERT INTO recipe_version (recipe_id, saved_at, change_note, grinder, grinder_id,"
            " grind_setting, dose_g, yield_g, temperature_c, profile, profile_id, basket,"
            " basket_id, notes) VALUES (:id, :now, :change_note, :grinder, :grinder_id,"
            " :grind_setting, :dose_g, :yield_g, :temperature_c, :profile, :profile_id, :basket,"
            " :basket_id, :notes)",
            {**dict(row), "now": now, "change_note": change_note},
        )
    return recipe_id


def duplicate_recipe(conn, recipe_id):
    row = get_recipe(conn, recipe_id)
    return save_recipe(conn, None, {**dict(row), "name": f"{row['name']} (copy)"})


def toggle_recipe_archived(conn, recipe_id):
    conn.execute("UPDATE recipe SET archived = NOT archived WHERE id = ?", (recipe_id,))


def delete_recipe(conn, recipe_id):
    conn.execute("DELETE FROM recipe WHERE id = ?", (recipe_id,))


# Versions


def list_versions(conn, recipe_id):
    return conn.execute(
        "SELECT * FROM recipe_version WHERE recipe_id = ? ORDER BY id DESC", (recipe_id,)
    ).fetchall()


def _fmt_field(field, value):
    if value is None:
        return "–"
    return fmt_num(value) + VERSION_FIELDS[field][1]


def history(conn, recipe_id):
    """Versions newest first, each with the fields that changed against the one before."""
    versions = list_versions(conn, recipe_id)
    entries = []
    for index, version in enumerate(versions):
        older = versions[index + 1] if index + 1 < len(versions) else None
        changes = [
            {
                "label": label,
                "old": _fmt_field(field, older[field]) if older else None,
                "new": _fmt_field(field, version[field]),
            }
            for field, (label, _) in VERSION_FIELDS.items()
            if (version[field] != older[field] if older else version[field] is not None)
        ]
        entries.append(
            {
                "id": version["id"],
                "saved_at": version["saved_at"],
                "change_note": version["change_note"],
                "is_initial": older is None,
                "is_current": index == 0,
                "changes": changes,
            }
        )
    return entries


def _restore_equipment(conn, kind, equipment_id, name):
    if name is None:
        return None
    if conn.execute("SELECT 1 FROM equipment WHERE id = ?", (equipment_id,)).fetchone():
        return equipment_id
    return find_or_create_equipment(conn, kind, name)


def restore_version(conn, recipe_id, version_id):
    """Write an old version's values back to the recipe, as a new version."""
    version = conn.execute(
        "SELECT * FROM recipe_version WHERE id = ? AND recipe_id = ?", (version_id, recipe_id)
    ).fetchone()
    recipe = get_recipe(conn, recipe_id)
    if version is None or recipe is None:
        return False

    profile_id = profile_text = None
    if version["profile"] is not None:
        if conn.execute("SELECT 1 FROM profile WHERE id = ?", (version["profile_id"],)).fetchone():
            profile_id = version["profile_id"]
        else:
            profile_text = version["profile"]

    data = {
        **dict(recipe),
        "grinder_id": _restore_equipment(conn, "grinder", version["grinder_id"], version["grinder"]),
        "basket_id": _restore_equipment(conn, "basket", version["basket_id"], version["basket"]),
        "grind_setting": version["grind_setting"],
        "dose_g": version["dose_g"],
        "yield_g": version["yield_g"],
        "temperature_c": version["temperature_c"],
        "profile_id": profile_id,
        "profile_text": profile_text,
        "notes": version["notes"],
    }
    save_recipe(conn, recipe_id, data, f"Restored version from {version['saved_at'][:10]}")
    return True


def export(conn):
    return {
        table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
        for table in ("equipment", "profile", "recipe", "recipe_version")
    }
