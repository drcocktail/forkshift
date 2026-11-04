"""Run a Redshift Completion Kernel over a validated Forkshift action trace.

The bridge invokes the installed local Redshift v2 virtualenv in one fresh
process per Arcade branch. Each process gets a private EventStore, signing key,
Execution Cartridge, and fixture episode. A deterministic adapter reuses the
actions from the recorded live-green-trap trace; it makes zero planner/model
calls. The kernel issues its normal signed Completion Receipt, and the bridge
verifies that signature before publishing the trial report.

This is a manually authored signed Execution Cartridge run through Redshift's
native runtime and Completion Kernel. It is not an ExecutionMaker compilation
or registry promotion result. Selection in the output is local trial selection
after independent episode-oracle verification.

Run from the repository root:
    PYTHONPATH=forkshift /path/to/startup/v2/.venv/bin/python \\
        -m forkshift.redshift_bridge --engine fixture
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4


REPO = Path(__file__).resolve().parents[1]
V2_ROOT = Path(os.environ.get("REDSHIFT_V2_ROOT", "./redshift-v2")).expanduser().resolve()
V2_PYTHON = V2_ROOT / ".venv" / "bin" / "python"
OUTPUT = REPO / "redshift_evidence" / "branch-trial.json"
SOURCE_RECORDING = "live-green-trap"
SCENARIO = "stale-green"
PRINCIPAL = "forkshift.local.fixture"
VERIFIER = "forkshift://arcade-episode/v1"
EXEC_VERIFIER = "forkshift://arcade-execution/v1"
BRANCHES = (
    {
        "id": "trace-repair",
        "label": "Redshift replay · full recovery trace",
        "expected_success": True,
        "truncate": None,
    },
    {
        "id": "trace-shortcut",
        "label": "Redshift replay · incomplete shortcut",
        "expected_success": False,
        "truncate": 1,
    },
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _source_trace() -> dict[str, Any]:
    path = REPO / "arcade_evidence" / "final" / f"{SOURCE_RECORDING}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    source_hash = _sha(record["events"])
    if record.get("ledger_sha256") != source_hash:
        raise ValueError("Source recording ledger hash does not match its events.")
    if record.get("verdict") != "passed" or record.get("engine") != "ollama":
        raise ValueError("Source recording must be a passing live Ollama recording.")
    actions = []
    for event in record["events"]:
        if event.get("type") == "decision":
            actions.append({"step": len(actions) + 1,
                            "source_event_seq": event.get("seq"),
                            "action": event["data"].get("action")})
    if [item["action"] for item in actions] != ["try_backup", "repair_primary"]:
        raise ValueError("Source recording does not contain the expected validated action trace.")
    return {
        "source_recording_id": SOURCE_RECORDING,
        "source_ledger_sha256": source_hash,
        "source_agent": record.get("agent"),
        "source_engine": record.get("engine"),
        "actions": actions,
        "action_trace_sha256": _sha(actions),
    }


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    project_src = str(V2_ROOT / "src")
    forkshift_root = str(REPO)
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(p for p in (project_src, forkshift_root, prior) if p)
    # These branches are local-only. Do not forward API credential variables.
    for key in ("MODEL_API_KEY", "MUSE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(key, None)
    return env


def _run_branch_worker(branch: dict[str, Any], trace: dict[str, Any], engine: str,
                       workspace: Path, timeout: float) -> dict[str, Any]:
    command = [str(V2_PYTHON), "-m", "forkshift.redshift_bridge", "--branch-worker",
               json.dumps(branch, separators=(",", ":")),
               json.dumps(trace, separators=(",", ":")), engine, str(workspace)]
    started = time.monotonic()
    proc = subprocess.Popen(command, cwd=REPO.parent, env=_child_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True, close_fds=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 15)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate(timeout=3)
        return {"id": branch["id"], "label": branch["label"], "actions": [],
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "terminal_verified": False, "receipt_valid": False,
                "failure": "branch worker timed out", "stderr_tail": stderr[-2000:]}
    elapsed = round((time.monotonic() - started) * 1000)
    if proc.returncode != 0:
        return {"id": branch["id"], "label": branch["label"], "actions": [],
                "elapsed_ms": elapsed, "terminal_verified": False,
                "receipt_valid": False, "failure": f"branch worker exited {proc.returncode}",
                "stderr_tail": stderr[-2000:]}
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {"id": branch["id"], "label": branch["label"], "actions": [],
                "elapsed_ms": elapsed, "terminal_verified": False,
                "receipt_valid": False, "failure": f"invalid worker JSON: {exc}",
                "stderr_tail": stderr[-2000:]}
    result["elapsed_ms"] = elapsed
    return result


def run_trial(*, engine: str = "fixture", output: Path = OUTPUT) -> dict[str, Any]:
    if engine not in {"fixture", "ollama"}:
        raise ValueError("engine must be fixture or ollama")
    if not V2_PYTHON.is_file():
        raise FileNotFoundError(f"Redshift v2 virtualenv Python not found: {V2_PYTHON}")
    trace = _source_trace()
    trial_id = uuid4().hex[:12]
    workspace = REPO / ".redshift_work" / "forkshift" / trial_id
    branches = []
    # Run in serial to bound local worker/model memory while preserving branch isolation.
    for spec in BRANCHES:
        selected_actions = trace["actions"]
        if spec["truncate"] is not None:
            selected_actions = selected_actions[:spec["truncate"]]
        branch_trace = {**trace, "actions": selected_actions,
                        "action_trace_sha256": _sha(selected_actions)}
        branch_root = workspace / spec["id"]
        branches.append(_run_branch_worker(spec, branch_trace, engine, branch_root,
                                           timeout=240 if engine == "ollama" else 90))
    selected = next((branch["id"] for branch in branches if branch.get("terminal_verified")
                     and branch.get("receipt_valid") and branch.get("episode", {}).get("verdict") == "passed"), None)
    report = {
        "schema": "forkshift.redshift-branch-trial/v1",
        "trial_id": trial_id,
        "engine": engine,
        "output_path": str(output.expanduser().resolve()),
        "source": trace,
        "branches": branches,
        "selected_branch_id": selected,
        "selection_mode": "local_verified_trial_selection",
        "registry_promotion": "not_run",
        "claims": {
            "reused_actions": True,
            "planner_calls": 0,
            "runtime_model_calls": 0,
            "speed_claim": None,
            "cartridge_origin": "manually_authored_signed_execution_cartridge",
            "execution_maker_compiled": False,
        },
    }
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{trial_id}.tmp")
    data = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output)
    return report


def _run_native_branch(branch: dict[str, Any], trace: dict[str, Any], engine: str,
                       workspace: Path) -> dict[str, Any]:
    from redshift.completion import CompletionContract, CompletionKernel, CompletionRequest
    from redshift.dispatcher import TurnText
    from redshift.execution import ExecutionArtifact, ExecutionRuntime
    from redshift.registry import ArtifactRegistry
    from redshift.signing import DeviceSigner, verify_document
    from redshift.store import EventStore
    from redshift import __version__ as redshift_version

    from forkshift.arcade import run as run_arcade
    from forkshift.rle_oracle import judge
    from forkshift.rle_scenarios import SCENARIOS

    workspace.mkdir(parents=True, exist_ok=False)
    store = EventStore(workspace / "redshift.db")
    signer = DeviceSigner.load_or_create(workspace / "device.key")
    registry = ArtifactRegistry(store, signer=signer)
    artifact_id = f"forkshift-{branch['id']}"
    version = "0.1.0"
    input_schema = {
        "type": "object",
        "properties": {
            "branch_id": {"const": branch["id"]},
            "actions": {"type": "array", "items": {"type": "string", "enum": ["try_backup", "repair_primary"]}},
            "action_trace": {"type": "array", "items": {"type": "object", "properties": {
                "step": {"type": "integer"}, "source_event_seq": {"type": "integer"},
                "action": {"type": "string", "enum": ["try_backup", "repair_primary"]}},
                "required": ["step", "source_event_seq", "action"], "additionalProperties": False}},
            "action_trace_sha256": {"type": "string"},
            "source_ledger_sha256": {"type": "string"},
            "scenario": {"const": SCENARIO},
            "engine": {"enum": ["fixture", "ollama"]},
        },
        "required": ["branch_id", "actions", "action_trace", "action_trace_sha256", "source_ledger_sha256", "scenario", "engine"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "branch_id": {"const": branch["id"]},
            "source_ledger_sha256": {"type": "string"},
            "action_trace_sha256": {"type": "string"},
            "actions": {"type": "array", "items": {"type": "string"}},
            "action_trace": {"type": "array", "items": {"type": "object"}},
            "target_ledger_sha256": {"type": "string"},
            "episode": {"type": "object"},
        },
        "required": ["branch_id", "source_ledger_sha256", "action_trace_sha256", "actions", "action_trace", "target_ledger_sha256", "episode"],
        "additionalProperties": False,
    }
    document = {
        "schema": "redshift.execution-cartridge/v0.2",
        "artifact_id": artifact_id,
        "version": version,
        "capability": "Replay a provenance-bound Forkshift action trace in an isolated local episode",
        "contract": {"input_schema": input_schema, "output_schema": output_schema},
        "bindings": {"arcade": {
            "tool": "forkshift.arcade.run",
            "effect": "write",
            "permissions": ["forkshift.fixture.execute"],
            "idempotency": True,
        }},
        "procedure": {"entrypoint": artifact_id, "steps": [
            {"id": "arcade_episode", "op": "tool.call", "binding": "arcade",
             "arguments": {
                 "branch_id": "$input.branch_id", "actions": "$input.actions", "action_trace": "$input.action_trace",
                 "action_trace_sha256": "$input.action_trace_sha256",
                 "source_ledger_sha256": "$input.source_ledger_sha256",
                 "scenario": "$input.scenario", "engine": "$input.engine",
             }},
            {"id": "terminal_result", "op": "emit", "value": "$steps.arcade_episode"},
        ]},
        "policy": {"authority": {"scopes": ["forkshift-fixture"]}, "budgets": {"tool_calls": 1}},
        "runtime": {"model_calls": 0, "arbitrary_code": False},
        "verifier": {"ref": EXEC_VERIFIER, "independent": True},
        "provenance": {
            "source_recording_id": trace["source_recording_id"],
            "source_ledger_sha256": trace["source_ledger_sha256"],
            "action_trace": trace["actions"],
            "executed_action_trace": trace["actions"],
            "action_trace_sha256": trace["action_trace_sha256"],
            "bridge": "forkshift.redshift_bridge/v1",
        },
        "compiler": {"proposer": "forkshift.redshift_bridge", "admitted_by": "local-owner-constructed"},
        "admission": {"stage": "candidate", "required_successful_canaries": 5, "automatic": True},
        "completion": {"terminal": True},
    }
    artifact = ExecutionArtifact(signer.sign_document(document))
    artifact.validate()
    artifact_path = artifact.save(workspace / "artifacts")
    registry.register("execution", artifact.document, path=artifact_path)

    class ArcadeConnector:
        def call(self, operation: str, arguments: dict[str, Any], *, principal: str,
                 idempotency_key: str | None = None) -> dict[str, Any]:
            if operation != "forkshift.arcade.run" or principal != PRINCIPAL:
                raise ValueError("connector authority denied")
            if (arguments["action_trace_sha256"] != _sha(arguments["action_trace"])
                    or arguments["actions"] != [row["action"] for row in arguments["action_trace"]]):
                raise ValueError("action trace digest mismatch")
            sequence = list(arguments["actions"])

            class TraceChooser:
                def __init__(self) -> None:
                    self.index = 0

                def __call__(self, _agent: str, _brief: str, _observations: list[dict[str, Any]]) -> dict[str, str]:
                    if self.index >= len(sequence):
                        return {"action": "stop", "reason": "Recorded candidate trace ended."}
                    action = sequence[self.index]
                    self.index += 1
                    return {"action": action, "reason": "Replayed provenance-bound recorded action."}

            episode = run_arcade(arguments["scenario"], "policy", arguments["engine"],
                                 chooser=TraceChooser())
            spec = SCENARIOS[arguments["scenario"]]
            checks, verdict, summary = judge(
                episode["events"], forbidden=spec.forbidden,
                expected_route=spec.expected_route,
                requires_rollback=spec.crash_after_switch,
            )
            target_hash = _sha(episode["events"])
            if episode.get("ledger_sha256") != target_hash or episode.get("verdict") != verdict:
                raise ValueError("Arcade episode ledger failed independent re-grade.")
            if episode.get("checks") != checks or episode.get("summary") != summary:
                raise ValueError("Arcade episode summaries do not match oracle re-grade.")
            return {
                "branch_id": arguments["branch_id"],
                "source_ledger_sha256": arguments["source_ledger_sha256"],
                "action_trace_sha256": arguments["action_trace_sha256"],
                "action_trace": list(arguments["action_trace"]),
                "actions": list(arguments["actions"]),
                "target_ledger_sha256": target_hash,
                "episode": episode,
            }

    class TraceAgent:
        identity = "forkshift-recorded-action-adapter/v1"

        def __init__(self) -> None:
            self.sent = False

        def next_action(self, context: dict[str, Any]) -> dict[str, Any]:
            if not self.sent:
                self.sent = True
                state = context["task"].get("state", {})
                args = {
                    "branch_id": branch["id"], "actions": list(state["actions"]),
                    "action_trace": list(state["action_trace"]),
                    "action_trace_sha256": state["action_trace_sha256"],
                    "source_ledger_sha256": state["source_ledger_sha256"],
                    "scenario": SCENARIO, "engine": engine,
                }
                return {"kind": "invoke_cartridge", "name": artifact_id, "arguments": args,
                        "_usage": {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}}
            return {"kind": "fail", "code": "terminal_verifier_failed",
                    "message": "The candidate did not satisfy the Arcade terminal oracle.",
                    "_usage": {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}}

    runtime = ExecutionRuntime(
        store,
        verifiers={EXEC_VERIFIER: lambda output, inputs: (
            output.get("branch_id") == inputs.get("branch_id") == branch["id"]
            and output.get("source_ledger_sha256") == trace["source_ledger_sha256"]
            and output.get("action_trace_sha256") == trace["action_trace_sha256"]
            and output.get("action_trace") == trace["actions"]
            and output.get("target_ledger_sha256") == _sha(output.get("episode", {}).get("events", []))
            and output.get("episode", {}).get("ledger_sha256") == output.get("target_ledger_sha256")
        )},
        authority_resolver=lambda principal, scopes, permissions: (
            principal == PRINCIPAL and set(scopes) == {"forkshift-fixture"}
            and set(permissions) == {"forkshift.fixture.execute"}
        ),
        registry=registry, signer=signer,
    )

    def terminal_verifier(candidate: dict[str, Any], request: Any,
                          evidence: tuple[dict[str, Any], ...]) -> bool:
        episode = candidate.get("episode") or {}
        events = episode.get("events") or []
        spec = SCENARIOS[SCENARIO]
        checks, verdict, summary = judge(
            events, forbidden=spec.forbidden,
            expected_route=spec.expected_route,
            requires_rollback=spec.crash_after_switch,
        )
        return (
            candidate.get("branch_id") == branch["id"]
            and candidate.get("source_ledger_sha256") == trace["source_ledger_sha256"]
            and candidate.get("action_trace_sha256") == trace["action_trace_sha256"]
            and candidate.get("action_trace") == trace["actions"]
            and candidate.get("target_ledger_sha256") == _sha(events) == episode.get("ledger_sha256")
            and episode.get("verdict") == verdict == "passed"
            and episode.get("checks") == checks
            and episode.get("summary") == summary
            and summary.get("recovered") is True and summary.get("safe") is True
            and episode.get("scenario", {}).get("id") == SCENARIO
            and len(evidence) > 1
            and any(event.get("type") == "compiled.completed" for event in evidence)
        )

    kernel = CompletionKernel(
        store,
        agent=TraceAgent(),
        verifiers={VERIFIER: terminal_verifier},
        runtime=runtime,
        artifacts=[artifact],
        connectors={"arcade": ArcadeConnector()},
        signer=signer,
    )
    request_state = {
        "branch_id": branch["id"],
        "actions": [item["action"] for item in trace["actions"]],
        "action_trace": trace["actions"],
        "action_trace_sha256": trace["action_trace_sha256"],
        "source_ledger_sha256": trace["source_ledger_sha256"],
        "expected_success": branch["expected_success"],
    }
    request = CompletionRequest(
        turn=TurnText("Replay the validated local incident-recovery action trace and verify the terminal route."),
        contract=CompletionContract(
            verifier_ref=VERIFIER,
            output_schema=output_schema,
            max_agent_steps=2,
            max_cartridge_calls=1,
            allowed_artifacts=(artifact_id,),
        ),
        principal=PRINCIPAL,
        task_id=f"forkshift-{branch['id']}-{uuid4().hex[:10]}",
        state=request_state,
    )
    outcome = kernel.complete(request)
    raw_receipt = store.get("completion_receipt", f"rcpt_{outcome.completion_id.removeprefix('cmp_')}")
    receipt_valid = bool(raw_receipt and verify_document(raw_receipt))
    raw_episode = store.get("completion_episode", outcome.completion_id) or {}
    execution_event = next((event for event in outcome.events if event.get("type") == "compiled.completed"), None)
    run_result = ((execution_event or {}).get("execution") or {}).get("result") or {}
    arcade_record = run_result.get("episode")
    checks, verdict, summary = ([], "ungraded", {})
    if isinstance(arcade_record, dict):
        spec = SCENARIOS[SCENARIO]
        checks, verdict, summary = judge(
            arcade_record.get("events") or [], forbidden=spec.forbidden,
            expected_route=spec.expected_route,
            requires_rollback=spec.crash_after_switch,
        )
    return {
        "id": branch["id"], "label": branch["label"],
        "workspace_id": workspace.name,
        "actions": request_state["actions"],
        "action_trace_sha256": trace["action_trace_sha256"],
        "source_ledger_sha256": trace["source_ledger_sha256"],
        "target_ledger_sha256": run_result.get("target_ledger_sha256"),
        "terminal_verified": bool(outcome.status == "completed" and outcome.verified),
        "receipt_valid": receipt_valid,
        "route": outcome.route,
        "model_calls": outcome.runtime_model_calls,
        "agent_steps": raw_episode.get("counts", {}).get("agent_steps"),
        "cartridge_calls": raw_episode.get("counts", {}).get("cartridge_calls"),
        "completion_status": outcome.status,
        "completion_failure": outcome.failure,
        "redshift_version": redshift_version,
        "episode_verdict": verdict,
        "checks": checks,
        "summary": summary,
        "artifact": {"artifact_id": artifact.artifact_id, "version": artifact.version,
                     "digest": artifact.digest, "stage": registry.show("execution", artifact_id, version)["stage"],
                     "signature_valid": verify_document(artifact.document),
                     "provenance": artifact.document["provenance"]},
        "episode": arcade_record,
        "completion_events": list(outcome.events),
        "receipt": raw_receipt,
    }


def _branch_worker(branch_json: str, trace_json: str, engine: str, workspace: str) -> None:
    branch = json.loads(branch_json)
    trace = json.loads(trace_json)
    result = _run_native_branch(branch, trace, engine, Path(workspace))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("fixture", "ollama"), default="fixture")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--branch-worker", nargs=4, metavar=("BRANCH_JSON", "TRACE_JSON", "ENGINE", "WORKSPACE"))
    args = parser.parse_args()
    if args.branch_worker:
        _branch_worker(*args.branch_worker)
        return
    report = run_trial(engine=args.engine, output=args.output)
    print(json.dumps({key: value for key, value in report.items() if key != "branches"}, indent=2))
    for branch in report["branches"]:
        print(f"{branch['id']}: {branch.get('completion_status')} verified={branch.get('terminal_verified')} receipt={branch.get('receipt_valid')} elapsed_ms={branch.get('elapsed_ms')}")


if __name__ == "__main__":
    main()
