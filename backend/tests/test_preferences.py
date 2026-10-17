"""Server-side preferences: default, save, replace, unknown keys, CSRF, auth, limits."""

from __future__ import annotations

import httpx

CSRF = {"X-SBH-Client": "web"}
URL = "/api/v1/preferences/report-sections"


async def test_unset_preference_is_null(web: httpx.AsyncClient) -> None:
    r = await web.get(URL)
    assert r.status_code == 200
    assert r.json() == {"key": "report-sections", "value": None, "updated_at": None}


async def test_save_replace_and_reset(web: httpx.AsyncClient) -> None:
    r = await web.put(URL, json={"value": {"summary": True, "hrv": False}}, headers=CSRF)
    assert r.status_code == 200
    assert r.json()["value"] == {"summary": True, "hrv": False}
    r = await web.put(URL, json={"value": {"charts": False}}, headers=CSRF)
    assert r.json()["value"] == {"charts": False}  # replaced, not merged
    assert (await web.get(URL)).json()["value"] == {"charts": False}
    assert (await web.delete(URL, headers=CSRF)).status_code == 204
    assert (await web.get(URL)).json()["value"] is None


async def test_unknown_values_are_stored_untouched(web: httpx.AsyncClient) -> None:
    """The server does not interpret a preference: an unknown id never breaks it."""
    value = {"future-section": False, "nested": {"a": [1, 2]}}
    await web.put(URL, json={"value": value}, headers=CSRF)
    assert (await web.get(URL)).json()["value"] == value


async def test_write_needs_csrf_header_and_login(
    client: httpx.AsyncClient, web: httpx.AsyncClient
) -> None:
    assert (await web.put(URL, json={"value": {}})).status_code == 403  # logged in, no CSRF header
    assert (await web.delete(URL)).status_code == 403
    anon = httpx.AsyncClient(transport=client._transport, base_url="http://test")
    try:
        assert (await anon.get(URL)).status_code == 401
        assert (await anon.put(URL, json={"value": {}}, headers=CSRF)).status_code == 401
    finally:
        await anon.aclose()


async def test_bad_key_and_limits(web: httpx.AsyncClient) -> None:
    assert (await web.get("/api/v1/preferences/Bad Key")).status_code == 422
    big = {"v": "x" * 20000}
    r = await web.put(URL, json={"value": big}, headers=CSRF)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "value_too_large"
    for i in range(100):
        r = await web.put(f"/api/v1/preferences/k{i}", json={"value": i}, headers=CSRF)
        assert r.status_code == 200
    r = await web.put("/api/v1/preferences/one-more", json={"value": 1}, headers=CSRF)
    assert r.status_code == 422
    # replacing an existing key is still allowed at the cap
    r = await web.put("/api/v1/preferences/k1", json={"value": 2}, headers=CSRF)
    assert r.status_code == 200
