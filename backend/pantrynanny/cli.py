"""``pantrynanny-admin`` command line tool for bootstrapping and recovery."""

import argparse
import asyncio
import getpass
import secrets
import sys
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import make_engine, make_sessionmaker
from .errors import AppError
from .models import Household, KioskCode, Session, User
from .security import ROLES, hash_password, hash_token, new_kiosk_code, now
from .services.households import count_households, create_household, create_user


class CliError(Exception):
    pass


async def _household(session: AsyncSession, ref: str | None) -> Household:
    rows = (await session.execute(select(Household).order_by(Household.created_at))).scalars().all()
    if not rows:
        raise CliError("No household exists yet. Run create-household or create-user first.")
    if ref:
        for h in rows:
            if str(h.id) == ref or h.name == ref:
                return h
        raise CliError(f"Household {ref!r} not found")
    if len(rows) > 1:
        raise CliError("Several households exist; pass --household <id or name>")
    return rows[0]


def _password(args: argparse.Namespace) -> tuple[str, bool]:
    if getattr(args, "generate", False):
        return secrets.token_urlsafe(12), True
    if args.password:
        return args.password, False
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Repeat password: "):
        raise CliError("Passwords do not match")
    return pw, False


def _check_password(pw: str) -> None:
    if len(pw) < 8:
        raise CliError("Password must be at least 8 characters")


async def _run(args: argparse.Namespace) -> None:
    engine = make_engine(get_settings())
    sm = make_sessionmaker(engine)
    try:
        async with sm() as session:
            await _dispatch(session, args)
            await session.commit()
    finally:
        await engine.dispose()


async def _dispatch(session: AsyncSession, args: argparse.Namespace) -> None:
    cmd = args.command
    if cmd == "create-household":
        hh = await create_household(session, args.name)
        print(f"Created household {hh.name} ({hh.id})")
    elif cmd == "create-user":
        first = await count_households(session) == 0
        if first:
            hh = await create_household(session, args.household or "Hjemmet")
            print(f"Created household {hh.name} ({hh.id})")
        else:
            hh = await _household(session, args.household)
        has_users = await session.scalar(select(User.id).where(User.household_id == hh.id).limit(1))
        role = args.role or ("member" if has_users else "owner")
        pw, generated = _password(args)
        _check_password(pw)
        user = await create_user(
            session,
            household_id=hh.id,
            username=args.username,
            display_name=args.display_name or args.username,
            role=role,
            password=pw,
        )
        print(f"Created {role} {user.username!r} in household {hh.name!r}")
        if generated:
            print(f"Generated password (shown once): {pw}")
    elif cmd == "reset-password":
        user = (
            await session.execute(
                select(User).where(
                    User.username == args.username.strip().lower(), User.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise CliError(f"No such user {args.username!r}")
        pw, generated = _password(args)
        _check_password(pw)
        user.password_hash = hash_password(pw)
        user.is_active = True
        await session.execute(
            update(Session)
            .where(Session.user_id == user.id, Session.revoked_at.is_(None))
            .values(revoked_at=now())
        )
        print(f"Password reset for {user.username!r}; existing sessions revoked")
        if generated:
            print(f"Generated password (shown once): {pw}")
    elif cmd == "list-users":
        rows = await session.execute(
            select(User, Household.name)
            .join(Household, Household.id == User.household_id)
            .where(User.deleted_at.is_(None))
            .order_by(Household.name, User.created_at)
        )
        for user, hh_name in rows.all():
            state = "active" if user.is_active else "disabled"
            print(f"{user.username}\t{user.role}\t{state}\t{user.display_name}\t{hh_name}")
    elif cmd == "create-kiosk-code":
        hh = await _household(session, args.household)
        code = new_kiosk_code()
        session.add(
            KioskCode(
                household_id=hh.id,
                name=args.name,
                code_hash=hash_token(code),
                expires_at=now() + timedelta(minutes=15),
            )
        )
        print(f"Kiosk pairing code (valid 15 minutes, single use): {code}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pantrynanny-admin", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser(
        "create-household", help="Create a household with default locations/categories"
    )
    s.add_argument("--name", required=True)

    s = sub.add_parser("create-user", help="Create a user (and a household if none exists)")
    s.add_argument("--username", required=True)
    s.add_argument("--display-name")
    s.add_argument("--role", choices=ROLES, help="default: owner for the first user, else member")
    s.add_argument("--household", help="household id or name (when several exist)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--password", help="visible in shell history; prefer the prompt")
    g.add_argument("--generate", action="store_true", help="generate and print a password once")

    s = sub.add_parser("reset-password", help="Set a new password and revoke the user's sessions")
    s.add_argument("--username", required=True)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--password")
    g.add_argument("--generate", action="store_true")

    sub.add_parser("list-users", help="List users")

    s = sub.add_parser("create-kiosk-code", help="Print a 15 minute kiosk pairing code")
    s.add_argument("--name", required=True, help="device label, e.g. 'Kitchen iPad'")
    s.add_argument("--household")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(_run(args))
    except (CliError, AppError) as exc:
        print(f"error: {getattr(exc, 'detail', exc)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
