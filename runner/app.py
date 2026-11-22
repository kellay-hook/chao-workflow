from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

RUNNER_SECRET = os.environ.get("RUNNER_HMAC_SECRET", "dev-runner-secret")
MAX_SOURCE_BYTES = 200_000
MAX_OUTPUT_BYTES = 1_000_000

app = FastAPI(title="FlowMind Runner", version="0.1.0")


class ExecuteRequest(BaseModel):
    source: str = Field(max_length=MAX_SOURCE_BYTES)
    input: dict = Field(default_factory=dict)
    timeout_sec: int = Field(default=30, ge=1, le=120)
    memory_mb: int = Field(default=256, ge=64, le=1024)


def _signature(timestamp: str, body: bytes) -> str:
    return hmac.new(
        RUNNER_SECRET.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()


WRAPPER = r'''
import builtins
import contextlib
import io
import json
import socket
import sys

ALLOWED = {
    "json", "math", "re", "datetime", "collections", "itertools", "statistics",
    "csv", "io", "base64", "hashlib", "uuid", "decimal", "random", "string",
    "textwrap", "typing", "dataclasses", "enum", "functools", "operator",
    "time", "calendar", "zoneinfo", "bisect", "heapq", "copy", "pprint",
}

_original_import = builtins.__import__

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root not in ALLOWED:
        raise ImportError("module not allowed in code node: " + root)
    return _original_import(name, globals, locals, fromlist, level)

builtins.__import__ = _safe_import

class _NoSocket:
    def __init__(self, *args, **kwargs):
        raise OSError("network access is disabled in code nodes")

socket.socket = _NoSocket
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(OSError("network access is disabled"))

payload = json.loads(sys.stdin.read())
input_data = payload.get("input", {})
source = payload.get("source", "")
namespace = {"input": input_data, "__name__": "flowmind_code_node"}
stdout = io.StringIO()
stderr = io.StringIO()
try:
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exec(compile(source, "<code-node>", "exec"), namespace, namespace)
    output = namespace.get("result", namespace.get("output"))
    print(json.dumps({"output": output, "stdout": stdout.getvalue()[:20000], "stderr": stderr.getvalue()[:20000]}, ensure_ascii=False, default=str))
except Exception as exc:
    print(json.dumps({"error": f"{type(exc).__name__}: {exc}", "stdout": stdout.getvalue()[:20000], "stderr": stderr.getvalue()[:20000]}, ensure_ascii=False, default=str))
    sys.exit(1)
'''


@app.post("/execute")
async def execute(
    payload: ExecuteRequest,
    request: Request,
    x_runner_timestamp: str | None = Header(default=None),
    x_runner_signature: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    if not x_runner_timestamp or not x_runner_signature:
        raise HTTPException(status_code=401, detail="missing runner signature")
    if not hmac.compare_digest(_signature(x_runner_timestamp, body), x_runner_signature):
        raise HTTPException(status_code=401, detail="invalid runner signature")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="flowmind-code-") as tmp:
        tmp_path = Path(tmp)
        script = tmp_path / "runner_wrapper.py"
        script.write_text(WRAPPER, encoding="utf-8")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(tmp_path),
            "TMPDIR": str(tmp_path),
        }
        proc = subprocess.run(
            [sys.executable, "-I", str(script)],
            input=json.dumps({"source": payload.source, "input": payload.input}).encode(),
            cwd=tmp_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=payload.timeout_sec,
            check=False,
        )
    duration_ms = int((time.perf_counter() - started) * 1000)
    stdout = proc.stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
    stderr = proc.stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
    try:
        data = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
    except Exception:
        data = {"output": stdout}
    data["duration_ms"] = duration_ms
    data["exit_code"] = proc.returncode
    if stderr:
        data["process_stderr"] = stderr
    if proc.returncode != 0 and "error" not in data:
        data["error"] = stderr or "code node failed"
    return data
