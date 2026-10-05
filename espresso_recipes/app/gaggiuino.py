import httpx


class GaggiuinoError(Exception):
    pass


def parse_profiles(payload):
    if isinstance(payload, dict):
        payload = payload.get("profiles")
    if not isinstance(payload, list):
        raise GaggiuinoError("Unexpected response from the Gaggiuino")
    profiles = []
    for item in payload:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        name = str(item.get("name") or "").strip()
        if name:
            profiles.append({"id": str(item["id"]), "name": name})
    return profiles


def fetch_profiles(base_url, timeout=3.0, transport=None):
    """Profiles stored on the machine as [{"id", "name"}]. Raises GaggiuinoError."""
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.get(f"{base_url.rstrip('/')}/api/profiles/all")
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise GaggiuinoError(f"Gaggiuino not reachable at {base_url}") from exc
    except ValueError as exc:
        raise GaggiuinoError("Unexpected response from the Gaggiuino") from exc
    return parse_profiles(payload)
