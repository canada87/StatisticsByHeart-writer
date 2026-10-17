"""Test harness: real PostgreSQL 16 (testcontainers or SBH_TEST_DATABASE_URL), Alembic-migrated."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.config import Settings
from app.main import create_app
from app.models import IngestToken
from app.security import hash_password, new_ingest_token
from app.seed.loader import load_synthetic
from app.seed.synthetic import SeedConfig, generate

if sys.platform == "win32":  # psycopg async cannot run on the default Proactor loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BACKEND = Path(__file__).resolve().parents[1]
ALL_TABLES = (
    "health_sample, health_record, daily_metric, sync_run, device, "
    "ingest_token, user_session, admin_user, exercise_override, user_preference"
)


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    explicit = os.environ.get("SBH_TEST_DATABASE_URL")
    if explicit:
        yield explicit
        return
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def migrated_url(database_url: str) -> str:
    command.upgrade(alembic_config(database_url), "head")
    return database_url


@pytest_asyncio.fixture(scope="session")
async def engine(migrated_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(migrated_url)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {ALL_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def settings(migrated_url: str) -> Settings:
    return Settings(
        database_url=migrated_url,
        enable_scheduler=False,
        cookie_secure=False,
        local_timezone="Europe/Rome",
    )


@pytest_asyncio.fixture
async def app(settings: Settings):  # type: ignore[no-untyped-def]
    application = create_app(settings)
    yield application
    await application.state.engine.dispose()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def token(app) -> str:  # type: ignore[no-untyped-def]
    plaintext, token_hash, prefix = new_ingest_token()
    async with app.state.sessionmaker() as s:
        s.add(IngestToken(id=uuid.uuid4(), name="test", token_hash=token_hash, token_prefix=prefix))
        await s.commit()
    return plaintext


@pytest.fixture
def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def ha_token(app) -> str:  # type: ignore[no-untyped-def]
    plaintext, token_hash, prefix = new_ingest_token()
    async with app.state.sessionmaker() as s:
        s.add(
            IngestToken(
                id=uuid.uuid4(),
                name="Home Assistant",
                token_hash=token_hash,
                token_prefix=prefix,
                scope="ha",
            )
        )
        await s.commit()
    return plaintext


@pytest_asyncio.fixture
async def admin_password(app) -> str:  # type: ignore[no-untyped-def]
    from app.models import AdminUser

    pw = "correct horse battery staple"
    async with app.state.sessionmaker() as s:
        s.add(AdminUser(username="admin", password_hash=hash_password(pw)))
        await s.commit()
    return pw


# ---- shared by the dashboard / trends / report API tests
TODAY = datetime.now(ZoneInfo("Europe/Rome")).date()


@pytest_asyncio.fixture
async def seeded(app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    data = generate(SeedConfig(days=10, seed=3, end_date=TODAY, hr_interval_min=10))
    await load_synthetic(app.state.sessionmaker, settings, data)


@pytest_asyncio.fixture
async def web(client: httpx.AsyncClient, admin_password: str) -> httpx.AsyncClient:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": admin_password},
        headers={"X-SBH-Client": "web"},
    )
    assert r.status_code == 200
    return client
