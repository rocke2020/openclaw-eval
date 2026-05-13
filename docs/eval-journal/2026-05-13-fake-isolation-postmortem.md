# 2026-05-13 — How a run we called "per-sample isolated" wasn't isolated at all

## What we claimed

The `--per-sample-agent` flag's help: *"Provision a separate agent+workspace per sample for **full memory isolation**."*

The principles doc, the harness logs, the manifest, the verification artifact — every one of them said "isolation". The user asked for isolation. The harness reported running with isolation. The provisioning step created 10 isolated agents and 10 isolated workspaces.

## What we did

Wrote 272 sessions of conversation memory into one shared workspace. Answered 1986 QA from that one shared memory. Stamped each artifact record with a per-sample agent name that no request ever carried.

The wire saw a single agent. The artifacts saw 10. Nothing reconciled the two.

## Surface cause (pre-`d525884`)

Before commit `d525884`, `lib/backends.py` `OpenClawBackend.ingest/answer` used `self.agent` (fixed at backend construction from `--builtin-agent`). The per-sample harness code in `main.py:212-213` set `sample_args.agent = sample_agent` and called `_call_ingest(sample_args, …)` — but `_call_ingest` routed through `backend.ingest(user, message)` which ignored `args.agent`. The override was a no-op for every wire call.

`d525884` adds an `agent` kwarg to `OpenClawBackend.ingest/answer` that falls back to `self.agent`, and `_call_ingest`/`_call_answer` forward `args.agent` to it. Two regression tests cover the backend in isolation (`tests/test_eval_backends.py`). The harness-path integration (`_ingest_one_sample` → `_call_ingest` → backend → wire) is **not** yet covered by a test; a future change in `main.py` that drops the forwarding would pass the existing tests.

## Root cause — the deep one

We built **two parallel agent-routing mechanisms and never decided which one is authoritative for the wire.**

- Mechanism A: `args.agent`, mutated per-sample in `_ingest_one_sample`, used by `_maybe_reset_session`, used by snapshot-diff paths, stamped into ingest/qa records, written to manifest.
- Mechanism B: `backend.agent`, fixed at construction, used by `send_message_with_retry`, encoded into the `model: openclaw/<agent>` payload that the gateway routes on.

Both mechanisms started from the same value (`args.builtin_agent`) at backend construction. Per-sample provisioning then mutated only A. The code worked for non-per-sample runs because A and B were identical. The bug appeared the moment they diverged — and nothing checked that they hadn't.

A wire-routing decision belongs in exactly one place. We had it in two, with the wrong one winning silently. The `d525884` fix doesn't collapse the two — it lets A override B when present and falls back to B otherwise. Override-plus-fallback is the right minimal patch but leaves the same shape of bug possible: any new call site that fails to forward `args.agent` will silently route to B. Eliminating the dual mechanism (e.g. construct backends per-sample, or carry the agent inside a request value object) is the real long-term fix.

## How the verification harness failed to catch this

Memory-write verification was designed for this. It snapshots the per-sample workspace before/after ingest and reports `write_detected`. For every one of the 10 samples it correctly reported `write_detected: false` — and the harness correctly raised `Backend oo-builtin is non-publishable`.

It detected the failure. It did not *prevent* it. By the time it fired:

- 272 ingest sessions had already run (~19 min parallel, ~3 hours serial).
- 1986 QA had already run (~52 min parallel, ~4.5 hours serial).
- 30 canaries had run (the prior run).
- All deepseek API tokens spent.

There was no early-cycle probe — nothing that ingested one session, snapshotted, and asserted `write_detected=true` *before* committing the rest of the budget. The full-run principles doc has the right gate ("at least one selected sample has `write_detected=true`") but only as a post-hoc accept/reject check, not as a pre-flight fast-fail.

The `memory_write_verification.json` `status` field says `"ok"` despite `write_detected: false` on every sample, because `status` means "the verification ran without error", not "the system is healthy". Two distinct concepts collapsed into one word.

## How the visual signals reinforced the false belief

The run printed loudly throughout ingest:

```
=== Sample conv-26 ===
    user: eval-conv-26
    agent: eval-locomo-builtin-full-20260513-111321-conv-26
    19 session(s) to ingest
```

```
    [provision] created agent eval-locomo-builtin-full-20260513-111321-conv-26 -> /Users/.../workspace-locomo-builtin-full-20260513-111321-conv-26
```

Both lines are true statements that imply something false. The agent named in the log is `args.agent` (mechanism A), which is what the user *intended*. The agent on the wire is `backend.agent` (mechanism B), which is what actually got routed. The log spoke to A. The wire spoke to B. Neither labelled itself as "what actually hits the gateway".

## How the artifacts reinforced the false belief

`manifest.json.openclaw_agent` and every line of `ingest.jsonl` / `qa.jsonl` recorded the per-sample agent name. The artifact format encodes A. Anyone auditing the run after the fact (us, this morning) sees 10 distinct agent IDs and concludes isolation happened. The OpenClaw gateway's actual session files live under `~/.openclaw-eval/agents/<base-agent>/sessions/`, completely outside the artifact set — only the base agent's directory has session JSONLs; the per-sample agents' session dirs are empty. That ground truth was a `find` command away the whole time and nobody checked.

## How testing missed it

The full test suite (30 tests before this fix) covered: user-key derivation, manifest contracts, category policy, memory-verify diffs, backend selection. None of them asked: *"given the per-sample agent override, what agent name does the wire receive?"* The test that came closest (`test_eval_user_keys.py`) mocks `send_message_with_retry` and asserts on `user`, not on `agent`. The backend's existence is new (cf0ef97); tests treated it as a config carrier and never as a router.

## The deeper deep cause — semantics not enforced by types or invariants

"Memory isolation" is a *semantic* requirement: writes from sample A must not be visible to sample B. The code expressed it through a *syntactic* convention: per-sample agent IDs in `args.agent`. The convention had no enforcement. There was no type that guaranteed "this thing is what the gateway will receive". There was no contract that backend implementations must honor per-call agent overrides. There was no fast-path probe that verified the gateway actually routed to the agent the harness named.

A semantic invariant without enforcement is a wish. The harness was full of wishes that the wire chose to ignore.

## Lessons

1. **Single source of truth for the wire.** Whatever value the gateway routes on (here: the `model: openclaw/<agent>` payload) must be derivable from exactly one place in code. If two mechanisms can produce it, code must assert they agree before sending.

2. **Fast-fail probes before budget commit.** A per-sample-isolated run claims an invariant that is checkable in seconds: ingest one sample's one session, snapshot, assert `write_detected=true` on its workspace and only its workspace. We had the snapshot machinery and didn't use it as a gate. Two implementation constraints to handle: (a) `ingest_parallel>1` fans samples out concurrently, so a probe inside `_ingest_one_sample` doesn't run "before sample 2 starts" unless a serial gate runs sample-1-session-1 before the parallel fanout; (b) the probe ingests a real session that counts toward the measured run, so the harness needs to treat that session as the first measured session (idempotent) or reset the workspace afterward — neither is free.

3. **Distrust artifacts that mirror the harness instead of the wire.** Manifest values copied from `args` confirm what the harness *intended*. To confirm what *happened*, read the gateway's session files, the per-workspace memory directory, the actual on-disk side effects. Artifact integrity is whatever the producer chooses to put in.

4. **`status: "ok"` should not collide with `write_detected: false`.** When a verification fires its alarm, that alarm should not be co-located with a "status: ok" field. Either the verification means something or it doesn't.

5. **Logs that announce intent must distinguish intent from outcome.** `agent: <per-sample-name>` printed at sample start is fine if labelled `agent (intended for wire)`. Without that label it acts as a confirmation that didn't happen.

6. **Strong product claims need adversarial tests.** `--per-sample-agent` is marketed as "full memory isolation". The test we needed was: "after a per-sample run, assert that sample A's workspace contains zero references to sample B's content." We didn't write it. The bug would have died in minutes instead of surviving until the score gap forced an investigation.

## Concrete follow-ups

Marked **[done]** when implemented in this commit; the rest are open.

- **[done]** Verification field separation: `verification.invariant_held` distinguished from `verification.status` ("ran without crashing" vs. "writes detected as expected").
- **[done]** Publishability gate hardened: per-sample mode now requires `all(write_detected)`, not `any(write_detected)`. One sample writing while nine sit empty is exactly the bug pattern this postmortem exists for.
- **[done]** Harness-path integration test: assert that `_ingest_one_sample` actually forwards the per-sample agent through `_call_ingest` → backend → wire (not just the backend method in isolation).
- **[open]** Pre-flight probe (sequenced before parallel fanout): ingest sample-1-session-1 serially, snapshot, assert `write_detected=true` *and* that sibling per-sample workspaces are untouched, then start the parallel fanout for the remaining sessions/samples. Requires care so the probe session counts toward the real run rather than being a thrown-away ingest.
- **[open]** Cross-workspace snapshot check at the verification layer: snapshot every per-sample workspace before any sample starts, compare after each sample's ingest, fail if sample A's writes appear in sample B's directory.
- **[open]** Rename `args.agent` and `backend.agent` so their roles are visible. Today both read as "the agent". Better: `args.agent` → `args.requested_agent`, `backend.agent` → `backend.default_agent`.
- **[open]** Logging convention: every line that prints an agent name labels which mechanism it came from (`intended:`, `wire:`, `verified:`).
- **[open]** Manifest schema: distinguish `base_agent` from per-sample agents in per-sample-mode runs, so an auditor can tell at a glance whether the run used isolation.

## What this changes about prior numbers

Both `output/runs/builtin-memory-full-20260512-225733/` (56%) and `output/runs/builtin-memory-full-20260513-111321/` (73%) measured the same flawed config: single shared base agent. Neither was the isolated benchmark we believed we were running. The score gap between them has multiple plausible contributors (writing-policy drift from the IDENTITY.md seed is the largest single factor we identified — see `2026-05-13-mixed-memory-run-comparison.md` — but parallelism, harness commit, and silent-failure rate also differ); it is not a clean isolated measurement of any one axis.

The first valid per-sample-isolated LoCoMo row needs more than the `d525884` wiring fix. Minimum gates: all-sample write verification (not just any), route verification against the gateway's actual session files, fixed IDENTITY.md seed policy, zero failed ingest sessions, and a manifest that records both the base agent and the per-sample agents used.
