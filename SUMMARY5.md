# SUMMARY5 — The Underwriting Agent (Run 5)

Twelve commits (K0..K11 plus one mid-run bug fix), each gated on pytest,
the three-way parity CLI, tsc -b, oxlint, vitest, and — from K11 onward —
the Playwright e2e suite. **No engine formula changed**: `engine.compute`'s
math is byte-identical to before this run; everything here is new
orchestration, a new HTTP surface, and new UI around the existing engine.
**BLOCKED.md delta:** `OPENAI_API_KEY` added to the pre-existing
"unset, degrades gracefully" list — same shape as every other optional key
in this app, nothing new blocked.

## 0. Why this run looks different from Runs 1–4

The build brief was written as a direct continuation of "Runs 1–5,"
assuming a `SUMMARY5.md`, a goal-seek endpoint, Monte Carlo, Docker, and
mezzanine debt already existed as prerequisites. None of that was true —
verified directly against the repo (file checks, git log, targeted greps)
before any code was touched: history runs `SUMMARY.md`→`SUMMARY4.md`, then
directly into a separate session's `P0`–`P3` extraction/UX fixes, with
none of the assumed Run-5 groundwork in between. Rather than proceed on a
false premise, the mismatch was flagged and the plan was re-scoped to what
the repo actually has: the native pro-forma engine, extraction, Quick
Screen, comps — no goal-seek, no Monte Carlo, no Docker, no mezz. This
file is that re-scoped plan's record, numbered `SUMMARY5` (the real next
entry in the sequence) rather than the brief's assumed `SUMMARY6`.

Three scope decisions were made explicit up front and held for the whole
run: **both Anthropic and OpenAI**, not Anthropic-only (an explicit
override of the recommendation to descope); **non-streaming v1** (agreed);
**core agent only** — no extraction-narration, no memo-drafting, both
flagged as real follow-on work, not silently dropped.

## 1. What got built (tool surface, in place of Run 5's would-be algebra)

No BEFORE/AFTER algebra section this run — nothing in `app/services/proforma/`
changed. Instead, the deliverable is a typed tool surface with a hard,
structurally-enforced privilege split:

| Tool | Privilege | Wraps |
|---|---|---|
| `get_deal` | read | `Deal` (dealId forced to the current thread's deal — K9 fix, see below) |
| `list_scenarios` | read | `Scenario` (same forced scoping) |
| `get_scenario` | read | `Scenario` by id |
| `compute` | read | `compute_cache.cached_compute` (existing, unchanged) |
| `solve` | read | **new** `compute_solver.solve` — bisection goal-seek (K0) |
| `run_sensitivity` | read | `sensitivity_service.run_native_sensitivity` (existing) |
| `run_tornado` | read | `tornado_service.run_tornado` (existing) |
| `get_market_context` | read | `market_context.get_market_context` (existing) |
| `list_comps` | read | `SaleComp`/`RentComp` query (existing tables) |
| `get_schema` | read | `mapping_service.load_flat_fields` (existing) |
| `propose_input_changes` | **write** | validates + previews, returns a `Proposal` — no DB access, ever |
| `propose_scenario` | **write** | same, with a `scenarioName` |

`solve` is the one genuinely new piece of engine-adjacent code
(`POST /api/compute/solve`): the brief assumed a goal-seek endpoint already
existed for the full engine; it didn't (only Quick Screen had client-side
`solve*` functions). Bisection over one input field vs. one output metric,
calling the existing pure `engine.compute` repeatedly — the regression
baseline and parity suite, which pin `engine.compute`'s formulas, needed
zero changes.

**Provider abstraction** (K2): `app/services/agent/providers/` — a
vendor-neutral `ChatResult`/`Message`/`ToolCall`/`ToolSpec` shape, an
Anthropic adapter (mirrors the existing `document_classifier.py` call
pattern), an OpenAI adapter (Chat Completions, function-calling), and a
`scripted` adapter (K11, deterministic/network-free, e2e-only). Selected
by `AGENT_PROVIDER`; missing key degrades to a typed "unavailable" result,
never a crash.

**Orchestration loop** (K4): `POST /api/agent/threads/{dealId}/messages` —
one call in, one full JSON turn out. Hard caps (25 tool calls, 15
compute-family calls, 60s wall-clock) stop the loop cleanly with a visible
"stopped early" note rather than looping silently. New tables
(`AgentThread`, `AgentMessage`, `AgentToolCall`, `AgentProposal`) needed no
migration — new tables never do in this app.

**Provenance checker** (K5): `app/services/agent/provenance.py` extracts
every dollar/percent/multiple/keyword-anchored-decimal claim from the
assistant's text and cross-checks it against every number that appeared in
that turn's own tool calls, with rounding-aware tolerance. This — not the
system prompt — is the actual anti-hallucination guarantee.

**UI** (K6/K7): a floating chat dock (outside `Layout`'s column flow, so
it survives every tab switch without touching its width math) and a full
Agent tab, both driven by one `useAgentThread` hook instance from
`App.tsx` so a conversation started in one continues in the other.
Proposal cards reuse `snapshotDiff`/`SnapshotDiffView` (I12) — no parallel
diff renderer. Approve routes through the same audit trail every other
edit uses (`deal_history.record_snapshot(..., kind="agent")`), visible in
the History drawer with a new indigo "Agent-applied" badge.

**Context + plays** (K8): a compact deal summary seeded into the system
prompt (name/status/type/market/key inputs) so the model doesn't need a
throwaway `get_deal` just to know what deal it's looking at — labeled
explicitly as database-sourced, not tool-verified. Four canned "plays"
(Screen, Explain-metric, Stress-test, Find-target), each a versioned
prompt + a restricted tool subset, surfaced as one-click suggestion chips.

**Security** (K9): every tool result sent to the provider is wrapped in a
labeled DATA envelope before serialization, so injected text in a deal
field or comp note reads as data next to an explicit warning, not a bare
instruction. A worst-case scripted test (the "model" fully complies with
injected adversarial text) confirms `Deal.inputs` still can't be touched.
Secret-scan tests confirm neither API key ever reaches the assembled
context.

**Cost logging** (K10): per-turn token totals accumulate on `AgentThread`
and log through a dedicated `app.agent` logger — no budget UI or hard-stop
yet; that's cheap to add later precisely because the data's been collected
from turn one.

**E2E gate** (K11): a hand-written deterministic `scripted` provider reads
real tool-result values rather than fabricating them, so it drives the
real loop/propose/approve flow exactly like a live model would, plus one
deliberate hallucination scenario. Two new Playwright specs against the
real backend + real frontend: the propose-and-approve happy path, and the
anti-hallucination gate (unverified claim renders in the UI) — the second
is a first-class, build-failing gate, same tier as the parity CLI.

## 2. Decisions and the one real bug found along the way

Nine new DECISIONS.md entries under "K-series — Underwriting Agent"
(structural privilege split over convention; provenance in code over
prompt-only; both providers per explicit override; non-streaming;
no-tool-replay-across-turns; the `get_deal` scoping fix; data-fencing for
injection; `solve` as new orchestration not new math; the scripted e2e
provider). One real bug, not just a test gap: neither the system prompt
nor the K8 context seed ever gave the model a raw deal id, so `get_deal`/
`list_scenarios` were unreachable by a real model — fixed by dropping the
`dealId` argument entirely and having the runner always bind these tools
to the thread's own deal, which also closes a cross-deal-read vector as a
bonus.

## 3. What was explicitly deferred (not silently dropped)

- **K7 (original brief) — extraction-wizard agent narration.** Not part of
  this pass; the extraction review UI is unchanged.
- **K8 (original brief) — agent-drafted IC-memo text.** Not part of this
  pass; `Generate IC Memo` is unchanged.
- **Streaming.** Every response here is one full JSON turn; SSE/WebSocket
  is a clean v2 addition on top of this once it's proven live on a real
  deal, not a redesign.
- **Cost budget UI / hard-stop.** Token totals are captured per thread
  from turn one (K10); the enforcement UI wasn't worth building before
  there's real usage to size a budget against.

## 4. Manual QA checklist (risk-ordered)

1. **No unverified number reaches the user silently.** Ask the agent
   something requiring a real figure; every number in the reply should be
   citable to a tool call shown in that message's tool-chip log. Force a
   fabricated claim (e.g. via the `scripted` provider's `fabricate`
   trigger, or by prompting a real model to guess) → the amber
   "Unverified" badge must render inline, not just log server-side.
2. **A write tool call never mutates the deal directly.** Ask for a
   proposal; confirm `Deal.inputs` (Deal Inputs tab) is unchanged until you
   explicitly click Approve. Reject a proposal → still unchanged, and if a
   note was given, it lands in the thread.
3. **Neither API key ever reaches the client.** Open browser devtools
   network tab while chatting; inspect the `/api/agent/*` response bodies
   and the rendered tool-call chips — no `ANTHROPIC_API_KEY`/
   `OPENAI_API_KEY` substring anywhere.
4. **`solve` doesn't touch the regression baseline.** Run
   `pytest tests/regression` and the parity CLI after any future change
   near `compute_solver.py` — both must stay green untouched, since solve
   only calls `engine.compute` in a loop.
5. **Approve → real audit trail.** After approving a proposal, open Input
   History (Deal Inputs tab) — the new entry reads "Agent-applied" in
   indigo, distinct from ordinary edits/restores.
6. **Provider switch is a config change, not a code change.** Set
   `AGENT_PROVIDER=openai` with a real `OPENAI_API_KEY`, restart the
   backend, and confirm the Agent still works — no frontend change needed,
   confirming the provider abstraction actually is vendor-neutral end to
   end.
7. **Caps stop cleanly.** Hard to trigger with a well-behaved model, but
   the tool-call/compute-family/wall-clock caps should always produce a
   visible "Stopped early — ..." message, never a silent truncation or a
   hung request.
8. **Dock and tab share state.** Send a message from the floating dock,
   then open the Agent tab (or vice versa) — the same conversation must be
   there, not a second empty thread.

## 5. Suite status at wrap-up

- pytest **499 passed** (incl. K0–K11's ~140 new agent tests: providers,
  tools, runner, provenance, router, context, plays, security, scripted
  provider, cost accumulation)
- parity CLI: **7 workbook cases, zero deltas** — `engine.compute` is
  untouched
- vitest **115 passed** · tsc -b clean · oxlint clean
- Playwright: **4 passed** (2 pre-existing smoke specs + 2 new Agent
  specs — the propose/approve happy path and the anti-hallucination gate)
