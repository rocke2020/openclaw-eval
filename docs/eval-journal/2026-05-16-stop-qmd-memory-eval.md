# 2026-05-16 — Stop the QMD memory eval track

We are stopping the QMD LoCoMo eval track for now. The comparison target is not yet stable enough to justify another full run.

The core issue is product shape, not harness mechanics. QMD can be made to search vectors, but a fair eval needs a carefully scoped write path that mirrors builtin memory's durable `MEMORY.md` / `memory/*.md` behavior. Without that, the run either measures an adapter prompt, hidden transcript access, or an indexing policy difference rather than "same agent, different memory backend."

The better next step is to keep builtin memory as the baseline and build a native enhanced builtin-memory variant with semantic/vector retrieval layered onto the existing durable memory files. That gives us a second memory solution with the same write contract, same isolation rules, and comparable artifacts:

- builtin memory: durable markdown write path plus lexical/search retrieval
- builtin-vector memory: same durable write path, plus semantic vector retrieval

This avoids spending eval budget on a QMD row whose semantics are hard to explain and hard to defend. Reopen QMD only if it gets a first-class, scoped write contract and a manifest that proves no extra paths, transcript indexing, or hidden context were used.
