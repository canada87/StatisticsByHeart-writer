"""Admin login/session, token lifecycle (hash only, revocable), rate limiting."""

import httpx
from fastapi import FastAPI

from tests.helpers import rows, scalar

CSRF = {"X-SBH-Client": "web"}


async def _login(client: httpx.AsyncClient, password: str) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": password}, headers=CSRF
    )


async def test_login_sets_httponly_cookie_and_session_works(
    client: httpx.AsyncClient, admin_password: str, app: FastAPI
) -> None:
    r = await _login(client, admin_password)
    assert r.status_code == 200 and r.json()["username"] == "admin"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert (await client.get("/api/v1/auth/me")).json()["username"] == "admin"
    # only a hash of the session secret is stored
    secret = client.cookies.get("sbh_session")
    assert secret and secret not in str(await rows(app, "SELECT token_hash FROM user_session"))

    out = await client.post("/api/v1/auth/logout", headers=CSRF)
    assert out.status_code == 204
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_wrong_password_and_unknown_user_are_indistinguishable(
    client: httpx.AsyncClient, admin_password: str
) -> None:
    bad = await _login(client, "nope-nope-nope")
    ghost = await client.post(
        "/api/v1/auth/login", json={"username": "ghost", "password": "x" * 14}, headers=CSRF
    )
    assert bad.status_code == ghost.status_code == 401
    assert bad.json() == ghost.json()
    assert "set-cookie" not in bad.headers


async def test_login_rate_limit(client: httpx.AsyncClient, admin_password: str) -> None:
    for _ in range(5):
        assert (await _login(client, "wrong-wrong-wrong")).status_code == 401
    locked = await _login(client, admin_password)  # even the right password is refused now
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0


async def test_state_changing_admin_calls_need_the_csrf_header(
    client: httpx.AsyncClient, admin_password: str
) -> None:
    await _login(client, admin_password)
    r = await client.post("/api/v1/admin/tokens", json={"name": "phone"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
    assert (await client.get("/api/v1/admin/tokens")).status_code == 200  # reads need none


async def test_admin_endpoints_require_a_session(client: httpx.AsyncClient, auth: dict) -> None:
    assert (await client.get("/api/v1/admin/tokens")).status_code == 401
    # an ingest token is not an admin credential
    assert (await client.get("/api/v1/admin/tokens", headers=auth)).status_code == 401
    assert (await client.get("/api/openapi.json")).status_code == 401


async def test_token_lifecycle_hash_only_and_revocable(
    client: httpx.AsyncClient, admin_password: str, app: FastAPI
) -> None:
    await _login(client, admin_password)
    created = await client.post("/api/v1/admin/tokens", json={"name": "Xiaomi"}, headers=CSRF)
    assert created.status_code == 201
    body = created.json()
    plaintext = body["token"]
    assert plaintext.startswith("sbh_") and body["prefix"] == plaintext[:8]

    # plaintext is never stored, never listed again
    assert plaintext not in str(await rows(app, "SELECT * FROM ingest_token"))
    listed = (await client.get("/api/v1/admin/tokens")).json()
    assert len(listed) == 1 and "token" not in listed[0] and listed[0]["revoked_at"] is None

    ingest = {"Authorization": f"Bearer {plaintext}"}
    ok = await client.get("/api/v1/ping", headers=ingest)
    assert ok.status_code == 200 and ok.json()["token"]["name"] == "Xiaomi"
    assert await scalar(app, "SELECT last_used_at IS NOT NULL FROM ingest_token") is True

    revoked = await client.delete(f"/api/v1/admin/tokens/{body['id']}", headers=CSRF)
    assert revoked.status_code == 204
    again = await client.get("/api/v1/ping", headers=ingest)
    assert again.status_code == 401 and again.json()["error"]["code"] == "token_revoked"
    # idempotent
    assert (
        await client.delete(f"/api/v1/admin/tokens/{body['id']}", headers=CSRF)
    ).status_code == 204
    missing = await client.delete(
        "/api/v1/admin/tokens/00000000-0000-0000-0000-000000000000", headers=CSRF
    )
    assert missing.status_code == 404


async def test_unknown_or_malformed_bearer_is_401(client: httpx.AsyncClient) -> None:
    for header in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"}):
        r = await client.get("/api/v1/ping", headers=header)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_token"
        assert r.headers["www-authenticate"] == "Bearer"


async def test_sync_runs_visible_to_admin(
    client: httpx.AsyncClient, admin_password: str, auth: dict
) -> None:
    from tests.helpers import post_records, steps

    await post_records(
        client, auth, [steps("s", "2026-10-14T08:00:00+02:00", "2026-10-14T08:15:00+02:00", 1)]
    )
    await _login(client, admin_password)
    runs = (await client.get("/api/v1/admin/sync-runs")).json()
    assert runs[0]["server_counts"]["records_inserted"] == 1
    assert (await client.get("/api/openapi.json")).status_code == 200


async def test_responses_are_not_cacheable(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
