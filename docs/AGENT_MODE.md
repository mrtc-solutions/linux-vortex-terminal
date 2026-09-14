# Agent Mode

Goal-directed runs with a visible transcript: **think → plan → Guardian →
execute → observe**, looping until the goal is verified or a budget stops
the run. Implemented in `backend/agent_mode.py`, served at `/api/agent/*`,
rendered by the Agent Mode surface (`frontend/agent.js`).

## The loop

Each run is one worker thread driving bounded steps over the existing
reviewed orchestration — Agent Mode adds the loop and the transcript, not
new execution paths:

1. **THINK** — `models.router.advise(..., phase="plan")` consults local
   models. Routing is fuzzy and llamafile-first: a healthy llamafile
   server answers as primary, else an on-device GGUF file, else Ollama
   (`choose_route`). One primary model, tight timeouts. The transcript
   records provider, model, latency, summary, proposed next steps,
   unknowns, and cautions.
2. **PROPOSE** — the model's next-step text becomes the *request* to
   deterministic `build_plan` (step 0 always grounds the goal verbatim).
   Model text never becomes shell: unplannable proposals are recorded and
   the run moves on or stops.
3. **GUARDIAN** — every step carries the real Guardian decision.
   `auto` steps execute immediately; anything else pauses the run as
   `awaiting_approval` until the operator approves that exact step.
4. **EXECUTE** — approved/auto steps run through `ExecutionManager`
   with the same identity, digest, expiry, and scope enforcement as the
   manual flow. A mutation preflight (`awaiting_confirmation`) pauses the
   run for review in the Tasks view.
5. **OBSERVE** — the worker waits for the real operation, records
   truncated output plus the deterministic `evaluate_objective` verdict,
   and loops. A run finishes `achieved` only on verified evidence — a
   model "done" claim alone never finishes a run.

## Guardrails

- One active run at a time (a second start is `409`); STOP finishes the
  run and cancels its operation.
- Step budget (default 5, max 10), 10-minute run budget, per-operation
  wait cap.
- Repeat guard: a stable fingerprint over each plan's executable content
  (kind, cwd, adapters, argv) stops the run instead of looping. Note this
  deliberately does not use `plan_digest`, which covers `expires_at`.
- No local model means no run: the preflight refuses with `needs_model`
  and per-provider download guidance (see below), recorded in the
  transcript. Advisory disappearing mid-run stops the run as `unresolved`.
- Approval is exact: resume requires the waiting plan's id plus explicit
  confirmation; the approval token itself never leaves the sidecar.
- Runs survive sidecar restarts as data: `running` rows reconcile to
  `interrupted`; paused runs resume their worker on approve/resume.

## Local-model architecture (no cloud, no keys)

Thinking rides the same local-first stack as everything else:

- **llamafile (primary)** — an operator-registered GGUF model file served
  on loopback. When healthy it answers first.
- **GGUF direct** — model files in the models directory via the
  in-process engine.
- **Ollama (managed)** — the sidecar-installed runtime on loopback with
  curated catalog models.

If none is healthy, the refusal tells the operator exactly what to do in
the **Models view**: register a GGUF file for llamafile, download GGUF
files, or install Ollama → pull a catalog model → start the service. The
Agent Mode UI offers a one-click jump to Models. Nothing is downloaded
automatically and no text is ever fabricated in place of a model.

## API

- `POST /api/agent/runs` `{goal, max_steps?, cwd?, engagement_id?, conversation_id?, offline?}` → `202 {run, preflight}`
- `GET /api/agent/runs` → recent runs (reconciled)
- `GET /api/agent/runs/:id` → `{run, events}` full transcript
- `GET /api/agent/runs/:id/stream?since=N` → SSE transcript feed
- `POST /api/agent/runs/:id/approve` `{plan_id, confirm:true}` → resume
- `POST /api/agent/runs/:id/stop` → stop

Run statuses: `running`, `awaiting_approval`, `finished` with outcome in
`achieved | exhausted | unresolved | loop_guard | error | stopped |
needs_model | interrupted`. Event kinds: `run_started, think, note,
step_planned, guardian, step_started, step_finished, verdict, paused,
approved, resumed, stopped, finished, error`.

## Honest limits (v1)

- The think step proposes one next action per step; there is no
  multi-branch planning or tool-use loop beyond plan → execute → verdict.
- Approval covers one exact step; long mutation chains pause repeatedly
  by design.
- The transcript truncates outputs (1.5 KB per stream) — full output
  stays on the linked operation.
