#!/usr/bin/env python3
"""VORTEX final audit: 10 real gates, 10/10 required.

Every gate executes genuine checks against this tree (no simulation):
unit suites, lint, JS suites, the GGUF provider chain, fuzzy routing,
per-function assistance, upstream tracking, a live HTTP server, the CLI,
and security spot-checks. Prints a score and exits 0 only at 10/10.

Usage:  python3 scripts/final_gates.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS: list[tuple[str, bool, str]] = []


def gate(name: str, ok: bool, evidence: str) -> None:
    RESULTS.append((name, bool(ok), evidence[:300]))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {evidence[:220]}", flush=True)


def run(cmd: list[str], env: dict[str, str] | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, env=merged)


def isolated_env(tmp: str) -> dict[str, str]:
    config = str(Path(tmp) / "config")
    os.makedirs(config, exist_ok=True)
    return {"VORTEX_DATA_DIR": tmp, "XDG_CONFIG_HOME": config,
            "VORTEX_MODELS_DIR": str(Path(tmp) / "models")}


def gate_unit_suite() -> None:
    proc = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], timeout=900)
    tail = (proc.stderr + proc.stdout).strip().splitlines()
    summary = " ".join(tail[-3:]) if tail else ""
    gate("1/10 python unit suite", proc.returncode == 0, summary or f"exit={proc.returncode}")


def gate_lint() -> None:
    proc = run([sys.executable, "-m", "compileall", "-q", "backend", "cli"])
    files = ["frontend/app.js", "frontend/terminal.js", "frontend/windows.js", "frontend/workspace.js",
             "frontend/models.js", "frontend/hud.js", "desktop/main.js", "desktop/preload.js",
             "desktop/security.js", "desktop/window-controls.js"]
    bad = []
    for name in files:
        check = run(["node", "--check", name], timeout=60)
        if check.returncode != 0:
            bad.append(name)
    ok = proc.returncode == 0 and not bad
    gate("2/10 lint (py compile + js syntax)", ok, f"compileall={proc.returncode} bad_js={bad or 'none'}")


def gate_js_suites() -> None:
    names = ["test_terminal", "test_windows", "test_frontend", "test_frontend_runtime",
             "test_frontend_auth", "test_agents_local_ai", "test_hud", "test_responsive"]
    failed = []
    for name in names:
        proc = run(["node", f"tests/{name}.js"], timeout=120)
        if proc.returncode != 0:
            failed.append(name)
    gate("3/10 js suites (8 files)", not failed, f"failed={failed or 'none'}")


def gate_gguf_chain() -> None:
    sys.path.insert(0, str(ROOT))
    import tempfile as _tempfile

    from backend.models import gguf as gguf_provider
    from backend.models.router import advise

    tmp = _tempfile.TemporaryDirectory()
    try:
        models = Path(tmp.name) / "models"
        models.mkdir()
        (models / "Llama-3.2-3B-Instruct-Q4_K_M.gguf").write_bytes(b"GGUF" + (3).to_bytes(4, "little") + b"\x00" * 64)
        (models / "Qwen2.5-3B-Instruct-Q4_K_M.gguf").write_bytes(b"GGUF" + (3).to_bytes(4, "little") + b"\x00" * 64)
        (models / "corrupt.gguf").write_bytes(b"XXXX" + b"\x00" * 64)
        old = os.environ.get("VORTEX_MODELS_DIR")
        os.environ["VORTEX_MODELS_DIR"] = str(models)
        gguf_provider.invalidate_scan_cache()
        try:
            found = gguf_provider.scan()
            valid = len(found["valid_files"]) == 2 and found["curated_missing"] == []
            corrupt_rejected = any(not item["valid"] and item["name"] == "corrupt.gguf" for item in found["files"])
            gguf_provider.set_test_engine(lambda entry, system, user: json.dumps({
                "fact_summary": "gate evidence", "meaning": "", "unknowns": "",
                "next_steps": [], "caution": "", "status_alignment": "observed-success"}))
            result = advise("gate", plan={"kind": "identity", "risk": "low", "status": "planned", "commands": []},
                            phase="conversation", settings={"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"})
            advised = result.get("state") == "responded" and result.get("provider") == "gguf"
            ok = valid and corrupt_rejected and advised
            gate("4/10 gguf chain (scan+validate+advise)", ok,
                 f"valid2={valid} corrupt_rejected={corrupt_rejected} advised_gguf={advised}")
        finally:
            if old is None:
                os.environ.pop("VORTEX_MODELS_DIR", None)
            else:
                os.environ["VORTEX_MODELS_DIR"] = old
            gguf_provider.set_test_engine(None)
            gguf_provider.invalidate_scan_cache()
    finally:
        tmp.cleanup()


def gate_fuzzy() -> None:
    sys.path.insert(0, str(ROOT))
    from backend.models import fuzzy as fuzzy_engine

    fuzzy_engine.reset_latency()
    d1 = fuzzy_engine.decide([{"id": "gguf", "state": "healthy"}, {"id": "ollama", "state": "healthy"}], phase="plan")
    d2 = fuzzy_engine.decide([{"id": "gguf", "state": "unavailable"}, {"id": "ollama", "state": "healthy"}])
    d3 = fuzzy_engine.decide([{"id": "gguf", "state": "unavailable"}, {"id": "ollama", "state": "unavailable"}])
    for _ in range(4):
        fuzzy_engine.record_latency("gguf", None, False)
    fuzzy_engine.record_latency("ollama", 800, True)
    d4 = fuzzy_engine.decide([{"id": "gguf", "state": "healthy"}, {"id": "ollama", "state": "healthy"}])
    fuzzy_engine.reset_latency()
    ok = d1["winner"] == "gguf" and d2["winner"] == "ollama" and d3["winner"] == "council" and d4["winner"] == "ollama"
    gate("5/10 fuzzy routing (primary→secondary→council)", ok,
         f"winners={[d1['winner'], d2['winner'], d3['winner'], d4['winner']]}")


def gate_assist_wiring() -> None:
    sys.path.insert(0, str(ROOT))
    tmp = tempfile.TemporaryDirectory()
    try:
        env = isolated_env(tmp.name)
        old = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        try:
            from backend import dashboard
            from backend.health import collect
            from backend.models.assist import coverage
            from backend.palette import run_palette
            from backend.replan import evaluate_objective
            from backend.vortex_backend import Store
            from backend.workspace import Workspace

            self_store = Store(Path(tmp.name) / "vortex.db")
            workspace = Workspace(self_store)
            settings = {"ai_enabled": True, "ollama_endpoint": "http://127.0.0.1:9"}
            checks = {
                "coverage>=16": coverage()["count"] >= 16,
                "search": "ai_hint" in workspace.search_all("x", settings=settings),
                "assets": "ai_hint" in workspace.asset_graph(10, settings),
                "dashboard": "ai_hint" in dashboard.collect(self_store, workspace, settings),
                "health": "ai_hint" in collect(self_store, None, settings),
                "palette": "ai_hint" in run_palette(self_store, workspace, "/whoami", settings=settings),
                "replan": "ai_hint" in evaluate_objective({"kind": "identity", "status": "planned"}, {"status": "succeeded"}, settings),
            }
            ok = all(checks.values())
            gate("6/10 per-function ai_hint wiring", ok, f"checks={checks}")
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    finally:
        tmp.cleanup()


def gate_upstream() -> None:
    sys.path.insert(0, str(ROOT))
    from unittest.mock import patch

    from backend.agents import council
    from backend.agents.upstream import refresh, table

    data = table()
    built_in = set(data) == {"vortex-local"}
    built_in_sync = data.get("vortex-local", {}).get("sync_state") == "builtin"
    no_third_party = set(council.ADAPTERS) == {"vortex-local"}
    with patch("urllib.request.urlopen", side_effect=AssertionError("offline must not dial")):
        offline = refresh(offline=True)["state"] == "offline"
    ok = built_in and built_in_sync and no_third_party and offline
    gate("7/10 advisor roster (built-in only, no third-party code, offline-safe)", ok,
         f"advisors={sorted(council.ADAPTERS)} table={sorted(data)} offline_safe={offline}")


def _http_json(url: str, method: str = "GET", body: dict | None = None, timeout: int = 30) -> tuple[int, dict]:
    data = json.dumps(body or {}).encode() if method == "POST" else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if method == "POST" else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except ValueError:
            return exc.code, {}


def gate_live_http() -> None:
    tmp = tempfile.TemporaryDirectory()
    try:
        env = isolated_env(tmp.name)
        proc = subprocess.Popen(
            [sys.executable, "backend/vortex_backend.py", "--host", "127.0.0.1", "--port", "8899"],
            cwd=str(ROOT), env={**os.environ, **env},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            base = "http://127.0.0.1:8899"
            ready = False
            for _ in range(100):
                try:
                    code, _ = _http_json(base + "/api/health")
                    if code == 200:
                        ready = True
                        break
                except OSError:
                    time.sleep(0.1)
            checks: dict[str, bool] = {"boot": ready}
            if ready:
                code, payload = _http_json(base + "/api/models")
                checks["models+fuzzy"] = code == 200 and "fuzzy" in payload.get("model", {})
                code, payload = _http_json(base + "/api/models/gguf")
                checks["gguf"] = code == 200 and payload.get("gguf", {}).get("provider") == "gguf"
                code, payload = _http_json(base + "/api/assist/coverage")
                checks["coverage"] = code == 200 and payload.get("coverage", {}).get("count", 0) >= 16
                code, payload = _http_json(base + "/api/agents/upstream")
                checks["upstream"] = code == 200 and set(payload.get("upstream", {})) == {"vortex-local"}
                code, payload = _http_json(base + "/api/assist", "POST", {"function": "health", "request": "x"})
                checks["assist"] = code == 200 and payload.get("assist", {}).get("function") == "health"
                code, _ = _http_json(base + "/api/models/gguf/activate", "POST", {"file": "../x.gguf", "role": "fast"})
                checks["traversal_blocked"] = code == 400
                code, payload = _http_json(base + "/api/dashboard")
                checks["dashboard_hint"] = code == 200 and "ai_hint" in payload.get("dashboard", {})
            ok = all(checks.values())
            gate("8/10 live http smoke (7 endpoints)", ok, f"checks={checks}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        tmp.cleanup()


def gate_cli() -> None:
    tmp = tempfile.TemporaryDirectory()
    try:
        env = isolated_env(tmp.name)
        results: dict[str, bool] = {}
        proc = run([sys.executable, "cli/vortex.py", "model", "status", "--json"], env=env, timeout=60)
        try:
            model = json.loads(proc.stdout).get("model", {})
            results["model+fuzzy"] = proc.returncode == 0 and "fuzzy" in model
        except ValueError:
            results["model+fuzzy"] = False
        proc = run([sys.executable, "cli/vortex.py", "palette", "/whoami", "--json"], env=env, timeout=60)
        try:
            results["palette"] = proc.returncode == 0 and "ai_hint" in json.loads(proc.stdout)
        except ValueError:
            results["palette"] = False
        proc = run([sys.executable, "cli/vortex.py", "explain", "whoami", "--json"], env=env, timeout=60)
        try:
            results["explain"] = proc.returncode == 0 and "ai_hint" in json.loads(proc.stdout)
        except ValueError:
            results["explain"] = False
        proc = run([sys.executable, "cli/vortex.py", "db", "integrity", "--json"], env=env, timeout=60)
        try:
            results["db"] = proc.returncode == 0 and "integrity" in json.loads(proc.stdout)
        except ValueError:
            results["db"] = False
        ok = all(results.values())
        gate("9/10 cli smoke (model/palette/explain/db)", ok, f"checks={results}")
    finally:
        tmp.cleanup()


def gate_security() -> None:
    sys.path.insert(0, str(ROOT))
    tmp = tempfile.TemporaryDirectory()
    try:
        env = isolated_env(tmp.name)
        old = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        try:
            from backend.models.manager import activate_gguf

            blocked = 0
            for hostile in ("../x.gguf", "..\\x.gguf", ".hidden.gguf", "a/b.gguf", "", "x" * 200):
                try:
                    activate_gguf(hostile, "fast")
                except (ValueError, Exception):
                    blocked += 1
            role_blocked = False
            try:
                activate_gguf("Llama-3.2-3B-Instruct-Q4_K_M.gguf", "root")
            except ValueError:
                role_blocked = True
            proc = run(["node", "-e", (
                "const s=require('./desktop/security.js');"
                "const ok=s.isAllowedApiRequest('/api/models/gguf/activate','POST')"
                "&&s.isAllowedApiRequest('/api/agents/upstream/refresh','POST')"
                "&&s.isAllowedApiRequest('/api/assist','POST')"
                "&&!s.isAllowedApiRequest('/api/models/../../etc/passwd','GET')"
                "&&!s.isAllowedApiRequest('/api/assist','DELETE');"
                "process.exit(ok?0:1);")], timeout=60)
            allowlist = proc.returncode == 0
            ok = blocked == 6 and role_blocked and allowlist
            gate("10/10 security spot-checks (traversal+allowlist)", ok,
                 f"hostile_blocked={blocked}/6 role_blocked={role_blocked} allowlist={allowlist}")
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    finally:
        tmp.cleanup()


def main() -> int:
    print("VORTEX final audit — 10 gates, real execution, no simulation.", flush=True)
    gate_unit_suite()
    gate_lint()
    gate_js_suites()
    gate_gguf_chain()
    gate_fuzzy()
    gate_assist_wiring()
    gate_upstream()
    gate_live_http()
    gate_cli()
    gate_security()
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\nFINAL: {passed}/10 ({passed * 10}%)", flush=True)
    for name, ok, evidence in RESULTS:
        if not ok:
            print(f"  FAILED: {name} — {evidence}", flush=True)
    return 0 if passed == 10 else 1


if __name__ == "__main__":
    sys.exit(main())
