import json
import math
import os
import sqlite3
from contextlib import asynccontextmanager
from itertools import groupby
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, gaggiuino, seed

APP_DIR = Path(__file__).parent
INGRESS_PROXY = "172.30.32.2"
DEFAULT_GAGGIUINO_URL = "http://gaggiuino.local"

templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["num"] = db.fmt_num


def gaggiuino_url():
    """From the environment, else the add-on options, else the default."""
    if os.environ.get("GAGGIUINO_URL"):
        return os.environ["GAGGIUINO_URL"]
    options = Path(os.environ.get("DATA_DIR", "/data")) / "options.json"
    try:
        return json.loads(options.read_text()).get("gaggiuino_url") or DEFAULT_GAGGIUINO_URL
    except (OSError, ValueError):
        return DEFAULT_GAGGIUINO_URL


def base_path(request):
    # Home Assistant Ingress serves the app under a per-install prefix.
    return request.headers.get("x-ingress-path", "").rstrip("/")


def render(request, name, status_code=200, **context):
    context["base"] = base_path(request)
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(request, path):
    return RedirectResponse(base_path(request) + path, status_code=303)


def _text(form, key):
    value = form.get(key)
    return value.strip() or None if isinstance(value, str) else None


def _number(form, key, label, errors):
    raw = _text(form, key)
    if raw is None:
        return None
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value < 0:
        errors.append(f"{label} must be a number")
        return raw
    return value


def _equipment_id(conn, form, kind):
    value = form.get(f"{kind}_id") or ""
    if value == "new":
        name = _text(form, f"{kind}_new")
        return db.find_or_create_equipment(conn, kind, name) if name else None
    return int(value) if value.isdigit() else None


def _recipe_from_form(conn, form):
    errors = []
    data = {
        "name": _text(form, "name"),
        "method_id": _equipment_id(conn, form, "method"),
        "grinder_id": _equipment_id(conn, form, "grinder"),
        "basket_id": _equipment_id(conn, form, "basket"),
        "grind_setting": _text(form, "grind_setting"),
        "dose_g": _number(form, "dose_g", "Dose", errors),
        "yield_g": _number(form, "yield_g", "Yield", errors),
        "temperature_c": _number(form, "temperature_c", "Temperature", errors),
        "profile_id": None,
        "profile_text": None,
        "notes": _text(form, "notes"),
    }
    profile = form.get("profile_id") or ""
    if profile == "other":
        data["profile_text"] = _text(form, "profile_text")
    elif profile.isdigit():
        data["profile_id"] = int(profile)
    if not data["name"]:
        errors.append("Name is required")
    if not data["method_id"]:
        errors.append("Method is required")
    return data, errors


def _form_page(request, conn, recipe, errors=(), status_code=200):
    return render(
        request,
        "form.html",
        status_code=status_code,
        r=recipe,
        errors=errors,
        options={
            kind: db.list_equipment(conn, kind, include_id=recipe.get(f"{kind}_id"))
            for kind in db.KINDS
        },
        profiles=db.list_profiles(conn),
        history=db.history(conn, recipe["id"]) if recipe.get("id") else [],
    )


def _equipment_page(request, conn, error=None, status_code=200):
    return render(
        request,
        "equipment.html",
        status_code=status_code,
        error=error,
        groups=[
            ("method", "Brew methods", db.list_equipment(conn, "method", with_archived=True)),
            ("grinder", "Grinders", db.list_equipment(conn, "grinder", with_archived=True)),
            ("basket", "Baskets", db.list_equipment(conn, "basket", with_archived=True)),
        ],
    )


def create_app(seed_recipes=True):
    @asynccontextmanager
    async def lifespan(app):
        if db.init():
            with db.connect() as conn:
                seed.seed(conn, recipes=seed_recipes)
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    if os.environ.get("INGRESS_ONLY") == "1":
        # The add-on has no login of its own: only Home Assistant's ingress proxy may connect.
        @app.middleware("http")
        async def ingress_only(request, call_next):
            if request.client is None or request.client.host != INGRESS_PROXY:
                return PlainTextResponse("Forbidden", status_code=403)
            return await call_next(request)

    @app.get("/")
    def recipe_list(request: Request, archived: bool = False):
        with db.connect() as conn:
            recipes = db.list_recipes(conn, archived=archived)
        groups = [(method, list(rows)) for method, rows in groupby(recipes, lambda r: r["method"])]
        return render(request, "list.html", groups=groups, archived=archived)

    @app.get("/recipes/new")
    def recipe_new(request: Request):
        with db.connect() as conn:
            methods = db.list_equipment(conn, "method")
            recipe = {"id": None, "method_id": methods[0]["id"] if methods else None}
            return _form_page(request, conn, recipe)

    @app.get("/recipes/{recipe_id}")
    def recipe_edit(request: Request, recipe_id: int):
        with db.connect() as conn:
            recipe = db.get_recipe(conn, recipe_id)
            if recipe is None:
                raise HTTPException(404)
            return _form_page(request, conn, dict(recipe))

    @app.post("/recipes")
    async def recipe_create(request: Request):
        form = await request.form()
        with db.connect() as conn:
            data, errors = _recipe_from_form(conn, form)
            if errors:
                return _form_page(request, conn, {**data, "id": None}, errors, 400)
            recipe_id = db.save_recipe(conn, None, data, _text(form, "change_note"))
        return redirect(request, f"/recipes/{recipe_id}")

    @app.post("/recipes/{recipe_id}")
    async def recipe_update(request: Request, recipe_id: int):
        form = await request.form()
        with db.connect() as conn:
            recipe = db.get_recipe(conn, recipe_id)
            if recipe is None:
                raise HTTPException(404)
            data, errors = _recipe_from_form(conn, form)
            if errors:
                return _form_page(request, conn, {**dict(recipe), **data}, errors, 400)
            db.save_recipe(conn, recipe_id, data, _text(form, "change_note"))
        return redirect(request, f"/recipes/{recipe_id}")

    @app.post("/recipes/{recipe_id}/duplicate")
    def recipe_duplicate(request: Request, recipe_id: int):
        with db.connect() as conn:
            if db.get_recipe(conn, recipe_id) is None:
                raise HTTPException(404)
            new_id = db.duplicate_recipe(conn, recipe_id)
        return redirect(request, f"/recipes/{new_id}")

    @app.post("/recipes/{recipe_id}/archive")
    def recipe_archive(request: Request, recipe_id: int):
        with db.connect() as conn:
            db.toggle_recipe_archived(conn, recipe_id)
        return redirect(request, "/")

    @app.post("/recipes/{recipe_id}/delete")
    def recipe_delete(request: Request, recipe_id: int):
        with db.connect() as conn:
            db.delete_recipe(conn, recipe_id)
        return redirect(request, "/?archived=true")

    @app.post("/recipes/{recipe_id}/versions/{version_id}/restore")
    def version_restore(request: Request, recipe_id: int, version_id: int):
        with db.connect() as conn:
            if not db.restore_version(conn, recipe_id, version_id):
                raise HTTPException(404)
        return redirect(request, f"/recipes/{recipe_id}")

    @app.get("/equipment")
    def equipment_list(request: Request):
        with db.connect() as conn:
            return _equipment_page(request, conn)

    @app.post("/equipment")
    async def equipment_create(request: Request):
        form = await request.form()
        name = _text(form, "name")
        with db.connect() as conn:
            if form.get("kind") not in db.KINDS or not name:
                return _equipment_page(request, conn, "Name is required", 400)
            db.find_or_create_equipment(conn, form["kind"], name)
        return redirect(request, "/equipment")

    @app.post("/equipment/{equipment_id}")
    async def equipment_rename(request: Request, equipment_id: int):
        form = await request.form()
        name = _text(form, "name")
        with db.connect() as conn:
            if not name:
                return _equipment_page(request, conn, "Name is required", 400)
            try:
                db.rename_equipment(conn, equipment_id, name)
            except sqlite3.IntegrityError:
                return _equipment_page(request, conn, f"“{name}” already exists", 400)
        return redirect(request, "/equipment")

    @app.post("/equipment/{equipment_id}/archive")
    def equipment_archive(request: Request, equipment_id: int):
        with db.connect() as conn:
            db.toggle_equipment_archived(conn, equipment_id)
        return redirect(request, "/equipment")

    @app.post("/profiles/refresh")
    def profiles_refresh():
        error = None
        items = []
        try:
            items = gaggiuino.fetch_profiles(gaggiuino_url())
        except gaggiuino.GaggiuinoError as exc:
            error = str(exc)
        with db.connect() as conn:
            db.upsert_profiles(conn, items)
            profiles = [{"id": p["id"], "name": p["name"]} for p in db.list_profiles(conn)]
        return {"ok": error is None, "error": error, "profiles": profiles}

    @app.get("/export.json")
    def export():
        with db.connect() as conn:
            return db.export(conn)

    return app


app = create_app()
