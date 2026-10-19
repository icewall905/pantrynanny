import asyncio
import re

from pantrynanny.cli import main

from .conftest import PASSWORD


async def run_cli(*argv: str) -> int:
    return await asyncio.to_thread(main, list(argv))


async def test_cli_bootstrap_flow(client, capsys):
    assert await run_cli("list-users") == 0
    assert await run_cli("create-kiosk-code", "--name", "x") == 1  # no household yet
    assert "No household" in capsys.readouterr().err

    assert await run_cli("create-user", "--username", "Anna", "--password", PASSWORD) == 0
    out = capsys.readouterr().out
    assert "Created household" in out and "owner" in out

    assert (
        await run_cli("create-user", "--username", "bo", "--display-name", "Bo", "--generate") == 0
    )
    generated = re.search(
        r"Generated password \(shown once\): (\S+)", capsys.readouterr().out
    ).group(1)
    r = await client.post(
        "/api/auth/token", json={"username": "bo", "password": generated, "device_name": "t"}
    )
    assert r.status_code == 200 and r.json()["me"]["user"]["role"] == "member"
    token = r.json()["token"]

    assert await run_cli("create-user", "--username", "bo", "--password", PASSWORD) == 1  # taken
    capsys.readouterr()

    assert (
        await run_cli("reset-password", "--username", "bo", "--password", "brand-new-password") == 0
    )
    assert (
        await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 401
    r = await client.post(
        "/api/auth/token",
        json={"username": "bo", "password": "brand-new-password", "device_name": "t"},
    )
    assert r.status_code == 200

    assert await run_cli("list-users") == 0
    listing = capsys.readouterr().out
    assert "anna\towner" in listing and "bo\tmember" in listing

    assert await run_cli("create-kiosk-code", "--name", "Hall iPad") == 0
    code = re.search(r": ([A-Z0-9]{8})", capsys.readouterr().out).group(1)
    r = await client.post("/api/auth/kiosk", json={"code": code})
    assert r.status_code == 200 and r.json()["kiosk"] is True

    assert await run_cli("create-household", "--name", "Andet hjem") == 0
    assert await run_cli("create-kiosk-code", "--name", "x") == 1  # ambiguous household
    assert await run_cli("create-user", "--username", "cy", "--password", "short") == 1
