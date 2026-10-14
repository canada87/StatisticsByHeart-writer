"""Migration vs models, contract doc vs registry, exported OpenAPI vs code, body guard limits."""

import gzip
import json
from pathlib import Path

import httpx
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.health_types import SPECS
from app.main import create_app
from app.models import Base
from tests.helpers import records_body

REPO = Path(__file__).resolve().parents[2]


def test_migration_matches_models(migrated_url: str) -> None:
    engine = create_engine(migrated_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], diff


def test_contract_documents_every_type_and_field() -> None:
    doc = (REPO / "docs" / "api-contract.md").read_text(encoding="utf-8")
    for name, spec in SPECS.items():
        assert f"`{name}`" in doc or f"**`{name}`**" in doc, f"{name} missing from api-contract.md"
        for field in spec.model.model_fields:
            assert field in doc, f"{name}.{field} missing from api-contract.md"


def test_exported_openapi_is_current(settings) -> None:  # type: ignore[no-untyped-def]
    path = REPO / "docs" / "openapi.json"
    current = json.loads(path.read_text(encoding="utf-8"))
    assert current == create_app(settings).openapi(), (
        "docs/openapi.json is stale: run `uv run python -m app.cli export-openapi "
        "../docs/openapi.json` "
        "and, if the contract changed, update docs/api-contract.md + its changelog"
    )


async def test_gzip_bomb_is_rejected(auth: dict[str, str], settings) -> None:  # type: ignore[no-untyped-def]
    settings.max_body_bytes = 10_000
    big = gzip.compress(b'{"x": "' + b"a" * 200_000 + b'"}')
    assert len(big) < 10_000
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/ingest/records",
            content=big,
            headers={**auth, "Content-Type": "application/json", "Content-Encoding": "gzip"},
        )
        assert r.status_code == 413 and r.json()["error"]["code"] == "body_too_large"
        plain = await c.post(
            "/api/v1/ingest/records", json=records_body([]) | {"pad": "a" * 20_000}, headers=auth
        )
        assert plain.status_code == 413
    await app.state.engine.dispose()


async def test_unsupported_content_encoding(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    r = await client.post(
        "/api/v1/ingest/records",
        content=b"{}",
        headers={**auth, "Content-Type": "application/json", "Content-Encoding": "br"},
    )
    assert r.status_code == 415
