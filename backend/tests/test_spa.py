"""SPA hosting: index + deep-link fallback, immutable assets, API 404s stay JSON."""

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app


@pytest.fixture
def spa_dir(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>SBH</title><div id=root></div>")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (tmp_path.parent / "secret.txt").write_text("outside")
    return tmp_path


@pytest.fixture
async def spa_client(settings: Settings, spa_dir: Path):  # type: ignore[no-untyped-def]
    settings.static_dir = str(spa_dir)
    app: FastAPI = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await app.state.engine.dispose()


async def test_index_and_deep_links(spa_client: httpx.AsyncClient) -> None:
    for path in ("/", "/sync?r=7d", "/login"):
        r = await spa_client.get(path)
        assert r.status_code == 200 and "<div id=root>" in r.text
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert r.headers["cache-control"] == "no-store"


async def test_static_files_and_asset_caching(spa_client: httpx.AsyncClient) -> None:
    asset = await spa_client.get("/assets/app-abc123.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert asset.headers["cache-control"].count("max-age") == 1
    assert (await spa_client.get("/favicon.svg")).status_code == 200


async def test_api_stays_json_and_traversal_is_contained(spa_client: httpx.AsyncClient) -> None:
    r = await spa_client.get("/api/v1/nothing")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert (await spa_client.get("/api/v1/health")).json() == {"status": "ok"}
    r = await spa_client.get("/%2e%2e/secret.txt")
    assert "outside" not in r.text
    r = await spa_client.get("/assets/../../secret.txt")
    assert "outside" not in r.text
