"""Operational CLI: ``python -m app.cli <command>`` (run inside the container via exec)."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.models import AdminUser, HealthRecord, IngestToken
from app.security import hash_password, new_ingest_token
from app.seed.loader import load_synthetic
from app.seed.synthetic import SeedConfig, generate
from app.services import maintenance

MIN_PASSWORD_LEN = 12

SessionMaker = async_sessionmaker[AsyncSession]


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)


async def _with_db[T](settings: Settings, fn: Callable[[SessionMaker], Awaitable[T]]) -> T:
    engine = make_engine(settings.sqlalchemy_url)
    try:
        return await fn(make_sessionmaker(engine))
    finally:
        await engine.dispose()


def cmd_create_admin(args: argparse.Namespace, settings: Settings) -> int:
    password = os.environ.get("SBH_ADMIN_PASSWORD") or getpass.getpass("New admin password: ")
    if len(password) < MIN_PASSWORD_LEN:
        print(f"Password must be at least {MIN_PASSWORD_LEN} characters.", file=sys.stderr)
        return 2
    if "SBH_ADMIN_PASSWORD" not in os.environ and password != getpass.getpass("Repeat: "):
        print("Passwords differ.", file=sys.stderr)
        return 2

    async def go(sm: SessionMaker) -> None:
        async with sm() as s:
            user = (
                await s.execute(select(AdminUser).where(AdminUser.username == args.username))
            ).scalar_one_or_none()
            if user is None:
                s.add(AdminUser(username=args.username, password_hash=hash_password(password)))
                print(f"Admin '{args.username}' created.")
            else:
                user.password_hash = hash_password(password)
                user.password_changed_at = func.now()
                print(f"Password of '{args.username}' updated.")
            await s.commit()

    _run(_with_db(settings, go))
    return 0


def cmd_create_token(args: argparse.Namespace, settings: Settings) -> int:
    async def go(sm: SessionMaker) -> None:
        plaintext, token_hash, prefix = new_ingest_token()
        async with sm() as s:
            s.add(
                IngestToken(
                    id=uuid.uuid4(), name=args.name, token_hash=token_hash, token_prefix=prefix
                )
            )
            await s.commit()
        print(plaintext)

    _run(_with_db(settings, go))
    return 0


def cmd_seed(args: argparse.Namespace, settings: Settings) -> int:
    async def go(sm: SessionMaker) -> None:
        async with sm() as s:
            if args.if_empty and (await s.execute(select(func.count(HealthRecord.id)))).scalar():
                print("Database already has records: skipping seed.")
                return
        data = generate(
            SeedConfig(days=args.days, seed=args.seed, unrecorded_nights=(2, 9), rest_weeks=True)
        )
        totals = await load_synthetic(sm, settings, data)
        print(f"Seeded synthetic data: {totals}")

    _run(_with_db(settings, go))
    return 0


def cmd_dev_bootstrap(args: argparse.Namespace, settings: Settings) -> int:
    """DEV ONLY: create a throw-away admin and ingest token so the stack is usable at once."""
    password = os.environ.get("SBH_DEV_ADMIN_PASSWORD", "dev-password-change-me")

    async def go(sm: SessionMaker) -> None:
        async with sm() as s:
            if not (await s.execute(select(func.count(AdminUser.id)))).scalar():
                s.add(AdminUser(username="admin", password_hash=hash_password(password)))
                print("DEV admin created: username 'admin' (password from SBH_DEV_ADMIN_PASSWORD).")
            if not (await s.execute(select(func.count(IngestToken.id)))).scalar():
                plaintext, token_hash, prefix = new_ingest_token()
                s.add(
                    IngestToken(
                        id=uuid.uuid4(), name="dev", token_hash=token_hash, token_prefix=prefix
                    )
                )
                print(f"DEV ingest token (dev stack only): {plaintext}")
            await s.commit()

    _run(_with_db(settings, go))
    return 0


def cmd_recompute(args: argparse.Namespace, settings: Settings) -> int:
    today = date.today()
    first = (
        date.fromisoformat(args.date_from) if args.date_from else today - timedelta(days=args.days)
    )
    last = date.fromisoformat(args.date_to) if args.date_to else today

    async def go(sm: SessionMaker) -> None:
        async with sm() as s:
            n = await maintenance.recompute_range(s, settings, first, last)
            print(f"Recomputed {n} daily metrics ({first}..{last}).")

    _run(_with_db(settings, go))
    return 0


def cmd_recompute_heart_points(args: argparse.Namespace, settings: Settings) -> int:
    first = date.fromisoformat(args.date_from) if args.date_from else None
    last = date.fromisoformat(args.date_to) if args.date_to else None

    async def go(sm: SessionMaker) -> None:
        async with sm() as s:
            n = await maintenance.recompute_heart_points(s, settings, first, last)
            print(f"Heart Points recomputed for {n} days.")

    _run(_with_db(settings, go))
    return 0


def cmd_export_openapi(args: argparse.Namespace, settings: Settings) -> int:
    from app.main import create_app

    schema = create_app(settings).openapi()
    Path(args.path).write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {args.path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="Create the admin user or reset its password")
    p.add_argument("--username", default="admin")
    p.set_defaults(fn=cmd_create_admin)

    p = sub.add_parser("create-token", help="Create an ingest token and print it once")
    p.add_argument("--name", required=True)
    p.set_defaults(fn=cmd_create_token)

    p = sub.add_parser("seed", help="Load synthetic data (never real data)")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--if-empty", action="store_true")
    p.set_defaults(fn=cmd_seed)

    p = sub.add_parser("dev-bootstrap", help="DEV ONLY: throw-away admin + token")
    p.set_defaults(fn=cmd_dev_bootstrap)

    p = sub.add_parser("recompute", help="Recompute computed daily metrics")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    p.set_defaults(fn=cmd_recompute)

    p = sub.add_parser(
        "recompute-heart-points",
        help="Recompute the Heart Points of the whole history (first deploy; after changing "
        "SBH_BIRTH_YEAR / SBH_HR_MAX)",
    )
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    p.set_defaults(fn=cmd_recompute_heart_points)

    p = sub.add_parser("export-openapi", help="Write the OpenAPI schema to a file")
    p.add_argument("path")
    p.set_defaults(fn=cmd_export_openapi)

    args = parser.parse_args(argv)
    return int(args.fn(args, get_settings()))


if __name__ == "__main__":
    raise SystemExit(main())
