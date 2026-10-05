# Espresso Recipes

A Home Assistant add-on for keeping coffee recipes: grind, dose, yield, temperature, basket and Gaggiuino profile per coffee, with a history of every change.

## Install

1. Push this repository to GitHub.
2. In Home Assistant open **Settings > Add-ons > Add-on store**, then **⋮ > Repositories**, and add the repository URL.
3. Install **Espresso Recipes**, start it, and enable **Show in sidebar**.

Home Assistant builds the image on the host. To try it without GitHub, copy the `espresso_recipes/` folder to `/addons/` on the host (Samba or SSH add-on) and reload the add-on store.

The app has no login of its own. It only accepts connections from Home Assistant's ingress proxy, so it is reachable wherever your Home Assistant is.

## Configuration

| Option | Default | |
| --- | --- | --- |
| `gaggiuino_url` | `http://gaggiuino.local` | Address of the machine. Use its IP address if the profile list stays empty: `.local` names often do not resolve inside add-on containers. |

The profile dropdown is filled from the machine (`GET /api/profiles/all`) whenever a recipe is opened while the machine is on. Profiles are remembered, so the dropdown also works when it is off. "Other…" accepts any name.

## Data

Everything is stored in `/data/recipes.db` (SQLite), which is part of the add-on's Home Assistant backup. **Equipment > Export all data as JSON** downloads a full dump.

On first start the database is filled with the recipes from the original notes.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest

cd espresso_recipes
DATA_DIR=../.data GAGGIUINO_URL=http://<machine-ip> ../.venv/bin/uvicorn app.main:app --reload
```

Build the image the way Home Assistant does:

```sh
docker build --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.21 espresso_recipes
```
