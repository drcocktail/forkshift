"""Lifecycle for two independent loopback inference workers.

Contract for the Forkshift integration:

    with WorkerFleet(engine="ollama" | "fixture") as fleet:
        fleet.kill("primary")  # evidence: {pool, pid, ...}
        fleet.probe("backup", "canary-1")  # status 200 only for exact ack+ID
        fleet.start("primary")  # restart a killed worker
        fleet.info()  # sanitized loopback endpoints, PIDs, models, and state

Ollama mode starts one private ``ollama serve`` process per pool, each bound to
its own loopback port with the inherited model directory. Fixture mode starts
the same module as a tiny deterministic HTTP worker, so process isolation and
kill/restart behavior can be exercised without model weights or network access.
No global daemon, account, or production configuration is changed.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


POOLS = ("primary", "backup")
MODEL = "llama3.2:3b"
DEFAULT_TIMEOUT = 45.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self._write(200, {"ready": True, "pid": os.getpid()})

    def do_POST(self) -> None:  # noqa: N802
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size))
            probe_id = body.get("probe_id")
            if not isinstance(probe_id, str) or not probe_id:
                raise ValueError("missing probe_id")
            self._write(200, {"status": "acknowledged", "probe_id": probe_id,
                              "model": "fixture-ack", "pid": os.getpid()})
        except (ValueError, TypeError, json.JSONDecodeError):
            self._write(400, {"error": "invalid probe request"})

    def _write(self, code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_: Any) -> None:
        pass


def _fixture_worker(port: int) -> None:
    HTTPServer(("127.0.0.1", port), _FixtureHandler).serve_forever()


class WorkerFleet:
    """Own two isolated Ollama or fixture subprocesses and their HTTP probes."""

    def __init__(self, engine: str = "ollama", *, timeout: float = DEFAULT_TIMEOUT,
                 model: str = MODEL, startup_timeout: float = 15.0):
        if engine not in ("ollama", "fixture"):
            raise ValueError("engine must be 'ollama' or 'fixture'")
        if timeout <= 0 or startup_timeout <= 0:
            raise ValueError("timeouts must be positive")
        self.engine = engine
        self.timeout = float(timeout)
        self.startup_timeout = float(startup_timeout)
        self.model = model if engine == "ollama" else "fixture-ack"
        self._workers: dict[str, dict[str, Any]] = {}
        self._closed = False

    def __enter__(self) -> "WorkerFleet":
        try:
            for pool in POOLS:
                self.start(pool)
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _check_pool(self, pool: str) -> None:
        if pool not in POOLS:
            raise ValueError("pool must be 'primary' or 'backup'")

    def start(self, pool: str) -> dict[str, Any]:
        self._check_pool(pool)
        existing = self._workers.get(pool)
        if existing and existing["process"].poll() is None:
            return {"pool": pool, "pid": existing["process"].pid,
                    "endpoint": existing["endpoint"], "model": self.model,
                    "started": False, "state": "running"}
        port = _free_port()
        endpoint = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        for name in ("MODEL_API_KEY", "MUSE_API_KEY"):
            env.pop(name, None)
        if self.engine == "ollama":
            env["OLLAMA_HOST"] = f"127.0.0.1:{port}"
            env.setdefault("OLLAMA_KEEP_ALIVE", "-1")
            command = ["ollama", "serve"]
        else:
            command = [sys.executable, "-m", "forkshift.rle_workers",
                       "--fixture-worker", str(port)]
        process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True,
                                   close_fds=True)
        entry = {"process": process, "endpoint": endpoint, "port": port}
        self._workers[pool] = entry
        if not self._wait_ready(entry):
            self._stop(entry)
            self._workers.pop(pool, None)
            raise RuntimeError(f"{pool} worker failed to become ready")
        return {"pool": pool, "pid": process.pid, "endpoint": endpoint,
                "model": self.model, "started": True, "state": "running"}

    def _wait_ready(self, entry: dict[str, Any]) -> bool:
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if entry["process"].poll() is not None:
                return False
            try:
                with urlopen(entry["endpoint"] + "/", timeout=0.5) as response:
                    if response.status == 200:
                        return True
            except (URLError, TimeoutError, OSError):
                time.sleep(0.05)
        return False

    def probe(self, pool: str, probe_id: str) -> dict[str, Any]:
        self._check_pool(pool)
        if not isinstance(probe_id, str) or not probe_id:
            raise ValueError("probe_id must be a nonempty string")
        entry = self._workers.get(pool)
        base = {"pool": pool, "probe_id": probe_id, "model": self.model,
                "pid": entry["process"].pid if entry else None}
        if not entry or entry["process"].poll() is not None:
            return {**base, "status": 0, "validated": False, "latency_ms": 0,
                    "error": "worker unavailable"}
        started = time.monotonic()
        try:
            if self.engine == "fixture":
                req = Request(entry["endpoint"] + "/probe",
                              data=json.dumps({"probe_id": probe_id}).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(req, timeout=self.timeout) as response:
                    payload = json.loads(response.read(65536))
                    status = response.status
            else:
                schema = {"type": "object", "properties": {
                    "status": {"type": "string", "enum": ["acknowledged"]},
                    "probe_id": {"type": "string"}},
                    "required": ["status", "probe_id"], "additionalProperties": False}
                prompt = (f'Return exactly a JSON acknowledgement for probe_id "{probe_id}". '
                          'Use status "acknowledged".')
                req_body = {"model": self.model, "prompt": prompt, "format": schema,
                            "stream": False, "keep_alive": -1,
                            "options": {"temperature": 0, "seed": 42, "num_predict": 64}}
                req = Request(entry["endpoint"] + "/api/generate",
                              data=json.dumps(req_body).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(req, timeout=self.timeout) as response:
                    raw = json.loads(response.read(1_000_000))
                    status = response.status
                payload = json.loads(raw.get("response", ""))
            latency = round((time.monotonic() - started) * 1000)
            if status != 200 or not isinstance(payload, dict) or payload.get("status") != "acknowledged" or payload.get("probe_id") != probe_id:
                return {**base, "status": 502, "validated": False, "latency_ms": latency,
                        "error": "worker response did not acknowledge the exact probe ID"}
            return {**base, "status": 200, "validated": True, "latency_ms": latency,
                    "ack": {"status": payload["status"], "probe_id": payload["probe_id"]},
                    "model": payload.get("model", self.model),
                    "worker_pid": payload.get("pid", entry["process"].pid)}
        except HTTPError:
            return {**base, "status": 502, "validated": False,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "error": "worker returned an HTTP failure"}
        except (URLError, TimeoutError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return {**base, "status": 502, "validated": False,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "error": f"worker probe failed: {type(exc).__name__}"}

    def kill(self, pool: str) -> dict[str, Any]:
        self._check_pool(pool)
        entry = self._workers.get(pool)
        if not entry:
            return {"pool": pool, "pid": None, "killed": False, "state": "not-started"}
        process = entry["process"]
        pid = process.pid
        was_running = process.poll() is None
        self._stop(entry)
        self._workers.pop(pool, None)
        return {"pool": pool, "pid": pid, "killed": was_running,
                "state": "stopped", "endpoint": entry["endpoint"]}

    @staticmethod
    def _stop(entry: dict[str, Any]) -> None:
        process = entry["process"]
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)

    def info(self) -> dict[str, Any]:
        return {pool: {"endpoint": entry["endpoint"],
                       "pid": entry["process"].pid,
                       "model": self.model,
                       "state": "running" if entry["process"].poll() is None else "stopped"}
                for pool, entry in self._workers.items()}

    def close(self) -> None:
        if self._closed:
            return
        for pool in tuple(self._workers):
            self.kill(pool)
        self._closed = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-worker", type=int)
    args = parser.parse_args()
    if args.fixture_worker is None:
        parser.error("this module is a worker lifecycle library")
    _fixture_worker(args.fixture_worker)
