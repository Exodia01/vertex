# iASPIRE — Anchor 1: Financial Journal / Customer Adversary

Status: **Anchor 1 J1–J11 built. Full gate green.**
Spec of record: `anchor/00_MASTER_ARCHITECTURE.md` + `anchor/01_FINANCIAL_JOURNAL.md`.
`anchor/03` and `anchor/04` are **reference only** — nothing from them is implemented.
Run: `python3 app.py` → http://127.0.0.1:8848
Gate: `python3 tools/gate.py` (contracts, linter, 7 suites, observability, live app)

## 0. Where we are

| Sprint | Modules | DoD |
|---|---|---|
| 1 | J1, J2 | met |
| 2 | J3, J4 (+J11) | met |
| 3 | J5, J6 | J6 partial — arithmetic not independently reviewed |
| 4 | J7, J8 | met (tone now authored in Hinglish at source) |
| 5 | J9 | met |
| 6 | J10 | met (incl. `priority.raised`) |

Anchor 1 §22 MVP boundary (J1–J8, basic J9, limited J10) is **complete**.
IM-1 is **not** met: it requires Anchor 2, whose spec does not exist in this repo.

## 1. What it is
A financial journal that is also an adversary. The customer says what they want in their own
words; the system infers the objective behind it, translates it into a financial mechanism,
tests that mechanism against the customer's *actual* behaviour with deterministic math, and
pushes back when it does not serve them. Nothing stabilizes until the customer confirms it.
The journal remembers everything, versioned, and re-analyses when life changes the numbers.

## 2. The hard rule
**No language model ever does arithmetic, and no narration layer invents a figure.** All
numbers originate in `j6_feasibility.py` against `policy/feasibility_policy.json`. J7 authors
the customer-facing text once, in the customer's language; narration no longer paraphrases it,
so the journal and the screen cannot disagree about what was said. `j4_llm.py` enforces the
same rule on the model path by discarding every numeric field a model returns.

## 3. Module map
| Module | File | Anchor 1 |
|---|---|---|
| Ingest, consent tags, access-controlled quarantine | `j1_ingest.py` | J1 |
| Snapshot: 12-month window, seasonal/irregular smoothing, FX, derived obligations | `j2_snapshot.py` | J2 |
| State machine + data-class tags | `j3_state.py` | J3 |
| Intent + **stated mechanism** + contradiction detection | `j4_intent.py` | J4 |
| Optional model layer, deterministic fallback | `j4_llm.py` | J4, §11 |
| Mechanism candidates from config, stated ranked first | `j5_mechanism.py` | J5 |
| Deterministic feasibility, policy-driven, seasonal stress | `j6_feasibility.py` | J6 |
| Challenge + nudge cap, Hinglish at source, J11 tone | `j7_challenge.py` | J7 |
| Stabilization + §21 event, contradiction note | `j8_stabilize.py` | J8 |
| Sealed append-only memory, customer-scoped, tombstone | `j9_memory.py` | J9 |
| Financial triggers + sentiment-only `priority.raised` | `j10_monitor.py` | J10 |
| Sentiment signal, never a gate | `j11_sentiment.py` | J11 |
| Orchestrator | `pipeline.py` | §9 |
| Shared audit store, audit-on-read, replay by goal | `audit.py` | §13, §17 |
| Contracts + boundary exclusion | `contracts.py`, `contracts/iaspire-contracts/` | §21 |
| Friend-voice narration (never invents numbers) | `narrate.py` | UX |
| HTTP + UI | `app.py` | §14 |
| Feasibility thresholds + mechanism rubric | `policy/*.json` | §12 |

## 4. Two version axes, deliberately not conflated
- `state_version` — record revision of a goal (v1, v2, v3…), threaded from J9 into J8 so an
  emitted event can never disagree with stored memory.
- `contract_version` — schema shape (v1 / v1.1), pinned by the shared registry.

`STABILIZED_JOURNAL_STATE` v1 rejects the v1.1 sentiment fields outright, which is what makes
the additive claim testable rather than aspirational.

## 4b. Bucket A hardening
- **Boundary is structural, not a deny-list.** `contracts.project_event()` builds every emitted
  payload by explicit allow-list, so internal fields (evidence refs, risk notes, monthly need)
  are dropped by construction. `assert_boundary_clean` now also rejects any field outside the
  projection, so even a hand-rolled payload fails loudly.
- **No route can drop a socket.** A global handler guard returns `500` + error JSON and writes
  an `http.handler_error` audit envelope. A deliberate-fault route exists behind
  `IASPIRE_TEST_ROUTES=1` and is 404 by default.
- **`priority.raised` has a real effect.** A raised goal jumps ahead of routine goals in
  `ordered_checkins()`.
- **One owner per constant.** The emergency basis lives only in
  `policy/feasibility_policy.json`; `benchmarks.json` holds external market figures only.

## 5. Controls now enforced (and tested in `test_failure_modes.py`)
- **Privacy (§13/§21).** Only coarse bands and an opaque `customer_ref` leave. Boundary
  exclusion is asserted on every emit.
- **Memory at rest.** Records are sealed with a per-tenant derived key. `CRYPTO_NOTE` states
  plainly that this is HMAC-based demonstration crypto, **not** a compliance-grade cipher,
  and names the AEAD/KMS seam it must be replaced with. `/api/health` reports `PLAINTEXT_NO_
  SECRET_SET` rather than silently running unsealed.
- **Tenant isolation.** A record sealed for one tenant fails its integrity check for another.
- **Access control (§9).** Memory reads are refused for anyone but the owning customer or an
  auditor role.
- **Quarantine access control.** Reading quarantined records requires an explicit grant.
- **Audit-on-read (§13).** Every read of financial data emits an envelope naming the fields
  touched and the purpose. One store, no parallel log.
- **Replay (§17).** `audit.replay(goal_id)` reconstructs the decision path.
- **Degradation (§15).** Engine failure defers with `analysis_pending` and tells the customer;
  nudge governor fails closed; model failure falls back to the deterministic classifier;
  sentiment failure cannot change an outcome.
- **Data hygiene.** `tools/synthetic_linter.py` gates the whole repo in CI.

## 6. UX flow — the ritual
Single column, one decision at a time. No dashboards.
Raat ka Hisaab → Maine sunha → Maine dekha (real numbers, collapsed) → Mera faisla
(`GO AHEAD` / `YE HO NHI SAKTA AS IS` / `EK GALTI MILI`) → Rasta ye bhi hai → Tera faisla →
Locked in → Yaad rakh liya → Jab kuch badle.

The verdict is judged on the customer's **worst** observed month, not their average, and the
copy says so. The neighbour knows the household obligations, because that is what makes it
read as a friend rather than a bank app.

## 7. Why the adversary is not a yes-machine
J4 extracts the customer's **stated** mechanism, not just their objective. J5 ranks it first.
J6 judges it on its own merits, so "I will save 3L for medical emergencies" is challenged even
though a feasible alternative exists. A modify response re-runs **J5 and J6** — switching
mechanism regenerates the candidate set and flips the verdict — rather than just redoing the
arithmetic on the old construct.

## 7b. The customer-facing flow (U1-U4)

The advice engine was finished before the interface for acting on it was, which was the wrong
order. These four closed that gap:

- **U1 - the choice step is editable, not a canned button.** A challenged customer is handed
  three real inputs prefilled with the engine's own numbers: target amount, timeline in months,
  and the mechanisms actually considered. The panel shows live arithmetic as they type
  ("Rs 20,833/mo chahiye, tera limit Rs 44,000, Rs 23,167 bachega"), so the consequence of a
  change is visible before it is committed. `_editable()` builds the block; the backend already
  accepted target/timeline/mechanism, so this exposed no new contract surface.
- **U2 - a clarifying question is answerable.** Previously the app asked a question and then
  orphaned the aspiration; the next message started a fresh one and the context was lost. Now
  `POST /api/aspirations/{id}/continue` merges the answer into the pending intent and re-enters
  J5 -> J6 on the same aspiration_id. The state machine gained one edge,
  `interpreted_expectation -> customer_response`, because a clarifying answer genuinely *is* a
  customer response; the merged intent rides that entry, since a self-loop is not a legal edge.
- **U3 - the thread is a real conversation.** The transcript persists in `sessionStorage` and
  re-renders on load, so it survives a page refresh and reads as one continuous conversation
  rather than a stack of disconnected cards.
- **U4 - goals have live standing.** `GET /api/goals` re-derives every goal against the current
  snapshot and reports `on_track` / `tight` / `behind` / `at_risk` with the reason and the next
  action, ordered by priority then severity. This is what gives a reason to return daily; a flat
  list of sentences did not.

All four are asserted in `tools/gate.py`, not just claimed.

## 8. The language layer (J4 / J11) and how it is arbitrated

Anchor 1 §11 assigns natural-language understanding and sentiment detection to the AI layer.
The shipped default is the deterministic classifier, which is the **floor, not the fallback**.

**Local Ollama provider** (`j4_llm.py`), enabled with `IASPIRE_LLM=1
IASPIRE_LLM_PROVIDER=ollama IASPIRE_LLM_MODEL=<model>`. Two findings from probing drove the
implementation: `:thinking` models spend the entire token budget reasoning and return nothing,
so `think:false` is mandatory; and free-form generation produced empty or truncated replies, so
output is constrained with Ollama's `format:<json schema>`.

**Arbitration** (`IASPIRE_ARBITRATION=disagreement_asks`):

| Condition | Behaviour |
|---|---|
| Ollama unreachable, slow, malformed or erroring | deterministic answer, silently |
| Model and deterministic agree | that answer, scores averaged within the agreed band |
| Model and deterministic **disagree** | clarifying question to the customer |

The model can never overrule the deterministic layer, and can never contribute a number —
every numeric field it returns is discarded. A disagreement is treated as genuine ambiguity,
which is what §15 asks for.

**Measured** (`tools/eval_arms.py`, 17 labeled intent cases, 25 sentiment dimensions):

| | deterministic | local model |
|---|---|---|
| J4 intent | **17/17 (100%)** | 15/17 (88%) |
| J11 sentiment | 23/25 (92%) | 23/25 (92%) |
| sentiment band disagreements | — | 0 |

Of the disagreements, **every one was a case where the deterministic layer was right and the
model was wrong** — the model over-called `contradictory` on `save 2L` and `close my loan
early`. An override design would have introduced those as errors; asking converts them into a
clarifying question instead.

These numbers are measured against fixtures authored in this repo, so treat them as a floor,
not an independent benchmark. The 88% model figure is also specific to one 35B model on one
machine; a different model will disagree differently, which is precisely why arbitration asks
rather than picks.

## 9. Known gaps (honest)
- **The deterministic layer is still keyword/lexicon based.** It scores 100% on fixtures I
  wrote. Free-form Hinglish with no matching keyword will still miss; the model path narrows
  that gap but has only been measured against those same fixtures.
- **J6 thresholds are PROVISIONAL** with no named product/actuarial owner, and the
  "reviewed by a human" DoD clause was satisfied by the same person who wrote the formulas.
- **The at-rest cipher is HMAC-based and explicitly not compliance-grade** (`CRYPTO_NOTE`).
  It provides integrity, tamper detection and tenant isolation, not semantic security. The
  AEAD/KMS replacement path is named but not taken.
- **Single-tenant, no authentication.** Access control is enforced in the store, not at a
  transport. Anyone who can reach the process can call the API as the customer. The transcript
  also lives in browser `sessionStorage`, so there is no server-side conversation history yet.
- **The model was evaluated on one machine with one model.** No cross-model comparison.
- `priority.raised` reorders check-ins in-process only; nothing persists the ordering.
- Anchor 2 has no spec, so IM-1 and the §21 consumer contract are untested end to end.

