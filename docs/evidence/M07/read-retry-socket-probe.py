"""Exercise the product client against a synthetic HTTP peer, never real data."""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from c1.storage.terminus import StorageConfig, Terminus  # noqa: E402


class Peer:
    def __init__(self, actions: list[str]) -> None:
        self.actions = actions
        self.requests: list[tuple[str, str, bytes]] = []
        self.tasks: set[asyncio.Task[None]] = set()
        self.writers: set[asyncio.StreamWriter] = set()
        self.errors: list[str] = []
        self.release = asyncio.Event()
        self.drained = False

    def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.add(writer)
        task = asyncio.create_task(self.handle(reader, writer))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(2):
                header = await reader.readuntil(b"\r\n\r\n")
                assert len(header) <= 8192
                lines = header.split(b"\r\n")
                method, target, version = lines[0].decode("ascii").split()
                assert version == "HTTP/1.1"
                size = 0
                for line in lines[1:]:
                    if line.lower().startswith(b"content-length:"):
                        size = int(line.split(b":", 1)[1])
                assert 0 <= size <= 8192
                body = await reader.readexactly(size)
                self.requests.append((method, target, body))
                index = len(self.requests) - 1
                assert index < len(self.actions)
                action = self.actions[index]
                if action == "wait":
                    await self.release.wait()
                elif action == "ok":
                    payload = b'[{"@id":"Binding/synthetic"}]'
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        b"TerminusDB-Data-Version: branch:synthetic\r\n"
                        b"Connection: close\r\nContent-Length: "
                        + str(len(payload)).encode("ascii")
                        + b"\r\n\r\n"
                        + payload
                    )
                    await writer.drain()
                else:
                    assert action == "drop"
                    # Consume the request, then disconnect without response headers.
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.errors.append(type(error).__name__)
        finally:
            writer.close()
            await writer.wait_closed()
            self.writers.discard(writer)


@asynccontextmanager
async def peer(actions: list[str]) -> AsyncIterator[tuple[Peer, str]]:
    state = Peer(actions)
    server = await asyncio.start_server(state.accept, "127.0.0.1", 0, limit=8192)
    port = server.sockets[0].getsockname()[1]
    try:
        yield state, f"http://127.0.0.1:{port}"
    finally:
        server.close()
        # Python 3.13 waits for active connections too: drain ours first.
        for writer in tuple(state.writers):
            writer.close()
        owned = tuple(state.tasks)
        for task in owned:
            task.cancel()
        await asyncio.gather(*owned, return_exceptions=True)
        await server.wait_closed()
        await asyncio.sleep(0)
        state.drained = not state.tasks and not state.writers


def config(url: str) -> StorageConfig:
    return StorageConfig(
        url=url,
        password="synthetic-peer-value",
        organization="admin",
        database="c1_m02_socket_probe",
        instance_base="urn:c1:instance:dev:",
    )


async def probe() -> dict[str, object]:
    results: list[dict[str, object]] = []
    async with peer(["drop", "ok"]) as (state, url):
        async with Terminus(config(url)) as client:
            record = await client.get("Binding/synthetic", commit="branch:synthetic")
            assert record == {"@id": "Binding/synthetic"}
        assert len(state.requests) == 2
        assert state.requests[0] == state.requests[1]
        assert all(item[0] == "GET" for item in state.requests)
    assert state.drained and not state.errors
    results.append({"case": "GET_disconnect_then_success", "attempts": 2, "result": "PASS"})

    async with peer(["drop", "drop"]) as (state, url):
        async with Terminus(config(url)) as client:
            try:
                await client.get("Binding/synthetic")
            except httpx.RemoteProtocolError:
                pass
            else:
                raise AssertionError("second_disconnect_did_not_fail")
        assert len(state.requests) == 2 and state.requests[0] == state.requests[1]
    assert state.drained and not state.errors
    results.append({"case": "GET_two_disconnects", "attempts": 2, "result": "PASS"})

    async with peer(["drop"]) as (state, url):
        async with Terminus(config(url)) as client:
            try:
                await client._request("POST", client._document_path, json={"synthetic": True})
            except httpx.RemoteProtocolError:
                pass
            else:
                raise AssertionError("mutation_disconnect_did_not_fail")
        assert len(state.requests) == 1 and state.requests[0][0] == "POST"
        assert json.loads(state.requests[0][2]) == {"synthetic": True}
    assert state.drained and not state.errors
    results.append({"case": "consumed_POST_is_not_replayed", "attempts": 1, "result": "PASS"})

    for actions in (["wait"], ["drop", "wait"]):
        async with peer(actions) as (state, url):
            async with Terminus(config(url)) as client:
                try:
                    async with asyncio.timeout(0.2):
                        await client.get("Binding/synthetic")
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("caller_deadline_did_not_fail")
            assert len(state.requests) == len(actions)
        assert state.drained and not state.errors
        results.append(
            {"case": f"deadline_attempt_{len(actions)}", "attempts": len(actions), "result": "PASS"}
        )
    return {"peer": "synthetic_loopback_HTTP1.1", "cases": results, "result": "PASS"}


if __name__ == "__main__":
    try:
        output = asyncio.run(probe())
    except Exception as failure:
        frames = [
            {"function": frame.name, "line": frame.lineno}
            for frame in traceback.extract_tb(failure.__traceback__)
            if Path(frame.filename).resolve() == Path(__file__).resolve()
        ]
        print(
            json.dumps({"result": "FAIL", "error_type": type(failure).__name__, "frames": frames})
        )
        raise SystemExit(1) from None
    print(json.dumps(output, indent=2, sort_keys=True))
