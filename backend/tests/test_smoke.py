import httpx


async def test_health_is_public(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_ping_requires_token(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    assert (await client.get("/api/v1/ping")).status_code == 401
    r = await client.get("/api/v1/ping", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["limits"]["max_batch_records"] == 500
