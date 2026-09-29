"""After lead review and the 79-case gate, capture the existing fixture CLI exit."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import BinaryIO, Never

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from c1.config import Settings  # noqa: E402
from probes.config import environment  # noqa: E402
from tests.integration.m03.conftest import live_case  # noqa: E402

EVIDENCE = ROOT / "docs/evidence/M07"
ARTIFACTS = {
    "stdout": EVIDENCE / "fixture-cli-stdout.log",
    "stderr": EVIDENCE / "fixture-cli-stderr.log",
    "result": EVIDENCE / "fixture-cli-result.json",
    "exit": EVIDENCE / "fixture-cli-exit.txt",
}
PROVIDER_VARIABLES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "HF_TOKEN",
    "AZURE_OPENAI_API_KEY",
)
UNSET_VARIABLES = (*PROVIDER_VARIABLES, "C1_API_URL", "C1_CRASH_AFTER", "C1_PROBE_CRASH_AFTER")


def child_environment(settings: Settings, trusted: dict[str, str]) -> dict[str, str]:
    """Use the factory's entire deployment, never the development database defaults."""
    values = {**os.environ, **trusted}
    for name in UNSET_VARIABLES:
        values.pop(name, None)
    values.update(
        {
            "C1_INSTANCE_ID": settings.instance_id,
            "C1_INSTANCE_IRI_BASE": settings.instance_base,
            "C1_ISSUER": settings.issuer,
            "C1_ISSUER_ALIAS": settings.issuer_alias,
            "C1_AUDIENCE": settings.audience,
            "C1_FGA_URL": settings.fga_url,
            "C1_FGA_TOKEN": settings.fga_token,
            "C1_FGA_STORE": settings.fga_store,
            "C1_FGA_MODEL": settings.fga_model,
            "C1_TERMINUS_URL": settings.terminus_url,
            "C1_TERMINUS_PASSWORD": settings.terminus_password,
            "C1_ORGANIZATION": settings.organization,
            "C1_KNOWLEDGE_DATABASE": settings.knowledge_database,
            "C1_WORKFLOW_DATABASE": settings.workflow_database,
            "C1_LOCK_PATH": str(settings.lock_path),
            "C1_INDEPENDENT_REVIEW": str(settings.independent_review).lower(),
            # The loader uses ordinary APIs; synthetic probe routes are unnecessary.
            "C1_ENABLE_PROBE_ROUTES": "false",
            "C1_CURSOR_SECRET": settings.cursor_secret,
            "C1_QUERY_CANDIDATE_LIMIT": str(settings.query_candidate_limit),
            "C1_MAX_READABLE_SCOPES": str(settings.max_readable_scopes),
            "C1_QUERY_TIME_BUDGET_MS": str(settings.query_time_budget_ms),
            "UV_OFFLINE": "1",
            "UV_CACHE_DIR": str(ROOT / ".uv-cache"),
            "UV_PYTHON_INSTALL_DIR": str(ROOT / ".uv-python"),
            "UV_PYTHON_BIN_DIR": str(ROOT / ".uv-python/bin"),
        }
    )
    return values


async def finish_owned[T](task: asyncio.Task[T]) -> T:
    """Retrieve completion even if another cancellation arrives during cleanup."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


def signal_owned_group(pgid: int, value: int) -> bool:
    try:
        os.killpg(pgid, value)
    except ProcessLookupError:
        return False
    return True


async def reap_child(child: asyncio.subprocess.Process) -> str:
    """Require group absence and a reaped child before resources can be dropped."""
    pgid = child.pid
    outcome = "REAPED_CHILD"
    failure: BaseException | None = None

    async def absent_within(seconds: float) -> bool:
        deadline = asyncio.get_running_loop().time() + seconds
        while signal_owned_group(pgid, 0):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(0.05, remaining))
        return True

    try:
        if signal_owned_group(pgid, signal.SIGTERM):
            outcome = "TERMINATED_GROUP_REAPED_CHILD"
            if not await absent_within(8):
                if signal_owned_group(pgid, signal.SIGKILL):
                    outcome = "KILLED_GROUP_REAPED_CHILD"
                if not await absent_within(2):
                    raise RuntimeError("owned_group_absence_unproven")
    except BaseException as exc:
        failure = exc
    try:
        # Even an unproven group receives a bounded attempt to reap our direct child.
        async with asyncio.timeout(2):
            await child.wait()
    except BaseException as exc:
        if failure is None:
            failure = exc
    if failure is not None:
        raise failure
    if signal_owned_group(pgid, 0):
        raise RuntimeError("owned_group_absence_unproven_after_reap")
    return outcome


def retain_and_exit(
    handles: Mapping[str, BinaryIO],
    metadata: dict[str, object],
    errors: list[dict[str, str]],
    failure: BaseException,
    child: asyncio.subprocess.Process | None,
) -> Never:
    """Persist uncertainty and bypass live_case's destructive async finalizers."""
    errors.append({"phase": "child_cleanup_proof", "type": type(failure).__name__})
    metadata.update(
        child_returncode=child.returncode if child is not None else None,
        child_cleanup_status="FAIL_OR_UNKNOWN",
        cleanup_status="NOT_RUN_RETAINED",
        wrapper_status="FAIL",
        wrapper_returncode=1,
        errors=errors,
    )
    try:
        # Flush available child output without treating this as completed output.
        for name in ("stdout", "stderr"):
            try:
                handles[name].flush()
                os.fsync(handles[name].fileno())
            except BaseException as exc:
                errors.append({"phase": "retained_output_fsync", "type": type(exc).__name__})
        try:
            handles["result"].write(
                (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode()
            )
            handles["result"].flush()
            os.fsync(handles["result"].fileno())
        except BaseException as exc:
            print(f"fixture_cli_retained_result_error={type(exc).__name__}", file=sys.stderr)
        try:
            observed = metadata["child_returncode"]
            handles["exit"].write(
                (
                    f"child_returncode={observed if observed is not None else 'NOT_OBSERVED'}\n"
                    "child_cleanup_status=FAIL_OR_UNKNOWN\n"
                    "cleanup_status=NOT_RUN_RETAINED\nwrapper_returncode=1\n"
                ).encode()
            )
            handles["exit"].flush()
            os.fsync(handles["exit"].fileno())
        except BaseException as exc:
            print(f"fixture_cli_retained_exit_error={type(exc).__name__}", file=sys.stderr)
    finally:
        # Raising/returning would execute live_case's database/store deletion finally.
        os._exit(1)


def terminal_result() -> bool:
    """Validate only the loader's final synthetic JSON line, without printing it."""
    with ARTIFACTS["stdout"].open(encoding="utf-8") as output:
        final = ""
        for line in output:
            if line.strip():
                final = line
    try:
        value = json.loads(final)
    except (ValueError, UnicodeError):
        return False
    return (
        isinstance(value, dict)
        and value.get("fixture") == "cross-project-batteries"
        and value.get("state") == "applied"
    )


async def run() -> int:
    # Refuse all preexisting artifacts, including dangling symlinks, before allocation.
    if any(path.exists() or path.is_symlink() for path in ARTIFACTS.values()):
        print("Existing fixture CLI evidence; refusing overwrite.", file=sys.stderr)
        return 73
    trusted = environment()
    # load_fixture.api_client reloads .env; unset keys must not be restored by setdefault.
    if any(name in trusted for name in UNSET_VARIABLES):
        print("Trusted configuration contains forbidden fixture gate flags.", file=sys.stderr)
        return 78
    try:
        gate_exit = dict(
            line.split("=", 1)
            for line in (EVIDENCE / "deadline-live-exit.txt").read_text().splitlines()
        )
        gate_xml = ET.parse(EVIDENCE / "deadline-live-junit.xml")
        terminal_cases = sum(int(suite.attrib["tests"]) for suite in gate_xml.iter("testsuite"))
        gate_passed = all(
            gate_exit.get(name) == "0"
            for name in ("pytest_exit", "tee_exit", "restore_exit", "script_exit")
        )
        gate_passed = gate_passed and all(
            int(suite.attrib.get(name, "0")) == 0
            for suite in gate_xml.iter("testsuite")
            for name in ("errors", "failures", "skipped")
        )
        cases = list(gate_xml.iter("testcase"))
        names = {(case.attrib["classname"], case.attrib["name"]) for case in cases}
        gate_passed = (
            gate_passed
            and len(cases) == len(names) == 79
            and all(classname and name for classname, name in names)
        )
        expected = json.loads((EVIDENCE / "corrected-live-expected-cases.json").read_text())
        if not isinstance(expected, list) or not all(isinstance(node, str) for node in expected):
            raise ValueError("Invalid expected node identities")
        actual_nodes = {f"{classname.replace('.', '/')}.py::{name}" for classname, name in names}
        gate_passed = (
            gate_passed
            and len(expected) == len(set(expected)) == 79
            and actual_nodes == set(expected)
        )
        gate_passed = gate_passed and not any(
            node.tag in {"failure", "error", "skipped"} for case in cases for node in case
        )
    except (OSError, ValueError, KeyError, ET.ParseError):
        gate_passed, terminal_cases = False, 0
    if not gate_passed or terminal_cases != 79:
        print("The ordered 79-case live gate lacks successful terminal evidence.", file=sys.stderr)
        return 75

    metadata: dict[str, object] = {
        "original_fixture_exit": "NOT_OBSERVED",
        "child_returncode": None,
        "child_cleanup_status": "NOT_RUN",
        "terminal_fixture_applied": False,
        "cleanup_status": "NOT_RUN",
        "wrapper_status": "NOT_RUN",
        "prerequisite_gate": "deadline-live-79",
        "errors": [],
    }
    errors: list[dict[str, str]] = []
    phase = "factory_setup"
    child: asyncio.subprocess.Process | None = None
    wrapper_exit = 1
    # Parent setup audit events add no useful CLI evidence; do not print them.
    logging.getLogger("c1.audit").disabled = True
    with ExitStack() as files:
        handles = {}
        for name, path in ARTIFACTS.items():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            handles[name] = files.enter_context(os.fdopen(fd, "wb"))
        parent = asyncio.current_task()
        assert parent is not None
        loop = asyncio.get_running_loop()
        # SIGTERM follows the same shielded owned-child cleanup path as cancellation.
        loop.add_signal_handler(signal.SIGTERM, parent.cancel)
        files.callback(loop.remove_signal_handler, signal.SIGTERM)
        try:
            metadata["cleanup_status"] = "IN_PROGRESS"
            async with live_case() as case:
                phase = "parent_runtime_close"
                try:
                    await case.runtime.close()
                    assert case.runtime.operations.writer.fd is None
                    metadata["parent_writer_released"] = True
                    argv = [
                        "uv",
                        "run",
                        "--locked",
                        "python",
                        "scripts/load_fixture.py",
                        "--fixture",
                        "cross-project-batteries",
                        "--database",
                        case.settings.knowledge_database,
                    ]
                    metadata["argv"] = argv
                    metadata["instance_id"] = case.settings.instance_id
                    metadata["knowledge_database"] = case.settings.knowledge_database
                    metadata["workflow_database"] = case.settings.workflow_database
                    metadata["fga_store"] = case.settings.fga_store
                    metadata["fga_model"] = case.settings.fga_model
                    phase = "child_spawn"
                    spawn = asyncio.create_task(
                        asyncio.create_subprocess_exec(
                            *argv,
                            cwd=ROOT,
                            env=child_environment(case.settings, trusted),
                            stdin=asyncio.subprocess.DEVNULL,
                            stdout=handles["stdout"],
                            stderr=handles["stderr"],
                            start_new_session=True,
                        )
                    )
                    try:
                        child = await asyncio.shield(spawn)
                        phase = "child_wait"
                        await child.wait()
                    finally:
                        # A cancelled spawn still belongs to us; obtain its process handle.
                        try:
                            if child is None:
                                child = await finish_owned(spawn)
                            metadata["owned_pgid"] = child.pid
                            metadata["child_cleanup_status"] = await finish_owned(
                                asyncio.create_task(reap_child(child))
                            )
                        except BaseException as cleanup_failure:
                            retain_and_exit(handles, metadata, errors, cleanup_failure, child)
                        metadata["child_returncode"] = child.returncode
                        handles["exit"].write(f"child_returncode={child.returncode}\n".encode())
                        handles["exit"].flush()
                        os.fsync(handles["exit"].fileno())
                    phase = "terminal_result"
                    metadata["terminal_fixture_applied"] = terminal_result()
                except BaseException as exc:
                    errors.append({"phase": phase, "type": type(exc).__name__})
                # The child is reaped before factory-owned clients drop its resources.
                phase = "factory_cleanup"
            metadata["cleanup_status"] = "PASS"
        except BaseException as exc:
            errors.append({"phase": phase, "type": type(exc).__name__})
            metadata["cleanup_status"] = "FAIL_OR_INCOMPLETE"
        metadata["errors"] = errors
        if errors:
            metadata["wrapper_status"] = "FAIL"
        elif child is not None and child.returncode == 0 and metadata["terminal_fixture_applied"]:
            metadata["wrapper_status"] = "PASS"
            wrapper_exit = 0
        else:
            metadata["wrapper_status"] = "FAIL"
            if child is not None and child.returncode is not None and child.returncode > 0:
                wrapper_exit = child.returncode
        metadata["wrapper_returncode"] = wrapper_exit
        handles["result"].write((json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode())
        handles["exit"].write(
            f"cleanup_status={metadata['cleanup_status']}\nwrapper_returncode={wrapper_exit}\n".encode()
        )
        for handle in handles.values():
            handle.flush()
            os.fsync(handle.fileno())
    print(f"fixture_cli_wrapper_returncode={wrapper_exit}")
    return wrapper_exit


if __name__ == "__main__":
    try:
        status = asyncio.run(run())
    except BaseException as failure:
        # Failure messages/tracebacks may contain private configuration or HTTP details.
        print(f"fixture_cli_wrapper_error={type(failure).__name__}", file=sys.stderr)
        status = 1
    raise SystemExit(status)
