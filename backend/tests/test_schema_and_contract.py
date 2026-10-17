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


def test_migration_0003_upgrades_and_downgrades_cleanly(database_url: str) -> None:
    """exercise_override can be added and removed on a scratch database (data untouched)."""
    from sqlalchemy import inspect, text
    from sqlalchemy.engine import make_url

    from alembic import command
    from tests.conftest import alembic_config

    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS migration_probe"))
        conn.execute(text("CREATE DATABASE migration_probe"))
    url = make_url(database_url).set(database="migration_probe").render_as_string(False)
    try:
        cfg = alembic_config(url)
        command.upgrade(cfg, "0002")
        engine = create_engine(url)
        assert "exercise_override" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "0003")
        columns = {c["name"]: c for c in inspect(engine).get_columns("exercise_override")}
        assert set(columns) == {"hc_id", "is_real", "updated_at"}
        assert not columns["is_real"]["nullable"]
        assert inspect(engine).get_pk_constraint("exercise_override")["constrained_columns"] == [
            "hc_id"
        ]
        command.downgrade(cfg, "0002")
        assert "exercise_override" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")
        assert "exercise_override" in inspect(engine).get_table_names()
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS migration_probe WITH (FORCE)"))
        admin.dispose()


def test_migration_0004_upgrades_and_downgrades_cleanly(database_url: str) -> None:
    """Preferences + token scope: existing tokens become ingest tokens, downgrade drops both."""
    from sqlalchemy import inspect, text
    from sqlalchemy.engine import make_url

    from alembic import command
    from tests.conftest import alembic_config

    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS migration_probe4"))
        conn.execute(text("CREATE DATABASE migration_probe4"))
    url = make_url(database_url).set(database="migration_probe4").render_as_string(False)
    try:
        cfg = alembic_config(url)
        command.upgrade(cfg, "0003")
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ingest_token (id, name, token_hash, token_prefix) "
                    "VALUES (gen_random_uuid(), 'old', 'h', 'p')"
                )
            )
        command.upgrade(cfg, "0004")
        assert "user_preference" in inspect(engine).get_table_names()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT scope FROM ingest_token")).scalar() == "ingest"
        command.downgrade(cfg, "0003")
        assert "user_preference" not in inspect(engine).get_table_names()
        assert "scope" not in {c["name"] for c in inspect(engine).get_columns("ingest_token")}
        command.upgrade(cfg, "head")
        assert "user_preference" in inspect(engine).get_table_names()
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS migration_probe4 WITH (FORCE)"))
        admin.dispose()
