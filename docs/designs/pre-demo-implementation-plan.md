# McCormick prototype: final engineering plan

2026-10-25 | master | baseline c0a633b | Review only; feature implementation has not started.

## Decision ledger

The user explicitly answered **A for all D24-D33**, and confirmed API access is not set up on the demo laptop. Earlier D1-D23 answers retain their exact recorded scope. In particular D9 B selects one CaptureAssistance component; D23 A selects one voice interaction with no queue. This document resolves the engineering questions in the approved design without changing its feedback-prototype objective.

| Decision | Approved behavior |
|---|---|
| D24 A | Submit waits until recording ends. |
| D25 A | Refresh preserves the basket and staged products; discards unfinished voice work with a notice. |
| D26 A | New products require a scanned UPC; voice can select existing catalog products by name. |
| D27 A | Existing catalog units; observe case conversions tomorrow. |
| D28 A | Positive whole quantities only. |
| D29 A | No operator or destination fields for this demo. |
| D30 A | Five-second lookup timeout, then manual fallback. |
| D31 A | Thirty-second interpretation timeout; retain basket. |
| D32 A | No automatic retries of new lookup/model calls. Existing Sheets recovery is unchanged. |
| D33 A | Up to $5 cumulative live model checks after implementation for this task. |

API setup is an execution prerequisite, not an unanswered design choice. No billing, key creation or live call occurred. Approval readiness: PASS — actual D4/D6-D33 answers checked against the historical decision records, including D9 B; required tests implement these approved contracts.

## Architecture review

Carry R1-R14 from the detailed working report plus its necessary persistence extension. These 15 findings have approved remedies, not implemented fixes.

- Unknown receiving UPC: check catalog and pending products first; use UPCitemdb Explorer. A unique complete result prefills editable draft fields without an extra confirmation. No-match, unavailable service, ambiguity and missing fields use the agreed manual completion, retaining any valid supplied fields. Unknown withdrawals cannot create products. Repeated scans consolidate one pending line with a stable product ID.
- Browser recognition supplies completed text to server-side OpenAI GPT-6.1 Sol, with selected direction, basket and full compact validated catalog. No formal MCP server or model lookup loop. Validate IDs, action semantics, positive whole quantities and direction. Untrusted catalog/provider text cannot authorize actions. The model proposes draft changes; it never saves stock.
- Voice adds/increments, sets quantities, removes lines, cancels the draft or requests clarification. Hold an ambiguous command's entire edit set until resolved; apply once. Discard removes the held command only. An unrelated edit invalidates its old context. Record barcode/voice/mixed from actual applied contributions, never model self-report; no-op/rejected/stale input contributes nothing.
- One recording/interpretation at a time. Submit waits through recording, processing and unresolved clarification. No queued save: require a fresh human click. Scanning/manual edits otherwise continue, invalidate stale responses, and retain ordinary recovery guards. Deduplicate browser completion callbacks and application. Timeout/refusal/malformed output/recognition failure leaves the basket intact. Late responses cannot apply after timeout or refresh.
- Proposed CaptureAssistance.lookup/interpret live in app/capture.py; proposed /api/capture/lookup and /api/capture/voice reuse local origin/session checks. Use server-only credentials, fixed provider URLs, bounded input/output and literal rendered text. Do not fetch provider image/link URLs. Keep provider calls outside the Inventory writer lock.

```text
scan -> known or staged? --yes--> increment visible draft
             | no
        receiving? --no--> visible rejection
             | yes
        lookup (5s) -> unique complete -> editable draft
             +--> none/conflict/incomplete/failure -> manual completion

mic -> final text -> one interpretation (30s) [EVAL]
  +-> unsupported/error/refusal/invalid -> unchanged basket + feedback
  +-> stale/duplicate -> do not apply
  +-> ambiguous -> hold ALL edits -> clarify or discard
  +-> valid and current -> apply edits once -> visible draft

human Submit [E2E]
 -> canonical identity + catalog reread under existing writer lock
 -> durable intent: catalog rows, transaction rows, expected balances
 -> ONE typed-cell Sheets batch
 -> verify catalog + ledger + formulas + balances -> saved receipt
 +-> definite rejection -> editable retained draft
 +-> uncertain outcome -> existing recovery lock, never blind retry
```

New rows have OpeningCount=0; their signed receiving rows supply the initial quantity once. Extend both tab capacities and formulas in that batch. Validate literal name/unit/UPC, ID/UPC uniqueness and referenced candidates; reject collisions found on reread rather than silently merging changed definitions. Canonical identity and evidence include new metadata and capture labels. Extend versioned payload parsing; preserve old maps/v2, stored evidence and immutable old receipts. The updated reader accepts new labels; an old binary rejects voice/mixed history and cannot be used as a transparent rollback.

Realistic failures: lookup quota/429 becomes manual entry; wrong model match requires validation/clarification and basket review; stale response is discarded; timeout after a committed batch requires exact readback recovery. Each has visible handling and required proof below. No planned failure is left both silent and untested. Single-writer assumptions do not protect against arbitrary concurrent workbook edits.

## Code quality review

CQ1: Unify draft mutation/version bookkeeping inside app/static/app.js. Existing changed():20 and direct quantity input:168-173 mutate identities through different paths. Proposed voice application and metadata edits must maintain the same invariant, including invalid transient numeric input disabling Submit. Proposed callers are assumptions, not existing code. No generic state framework is needed.

CQ2: Reuse pinned httpx, local-boundary middleware, Inventory.submit/verify/recover, Sheets typed-cell helpers/write and Journal.intent/state. Lookup and interpretation have different parsing/error contracts; keep their methods distinct within the selected component. No shared-library extraction proposed, no speculative line-savings claim. Added feature/tests will grow the code. Existing helpers have real callers in Inventory.submit and Sheets.write; their contracts remain stock authority and literal writes, respectively.

## Test review

Detected pytest from requirements.txt and tests/test_inventory.py. Dedicated source/test reads covered Inventory and Journal recovery. No browser framework is selected or installed. Baseline: 83 passed, one dependency warning; existing tests use simulated providers. They do not establish new-feature coverage.

```text
Existing canonical/submit/verify/recover
 [TESTED strong] quantity/type limits, identity conflicts, repeated submit
 [TESTED strong] direction/signs, capacity, literal text, legacy receipts
 [TESTED strong] timeout before/after, restart, history edits, API boundary
Proposed lookup
 [GAP G1] known/staged/unknown; receiving versus withdrawal
 [GAP G2] complete/incomplete/none/conflict; quota/network/5s/invalid data
Proposed interpretation [EVAL]
 [GAP G3] supported edits; ambiguity/unknown/direction/refusal/malformed
Browser draft and controls [E2E]
 [GAP G4] stale/duplicate/direct input and Submit gates
 [GAP G5] refresh/recognition errors/30s/late result/clarification discard
Extended stock persistence [E2E]
 [GAP G6] known+new rows, attribution, capacity/formulas, identity/recovery
```

These are six branch families, not measured coverage percentages. Extend existing test_inventory.py tables for storage/recovery and add tests/test_capture.py for provider/semantic boundaries. Browser checks exercise real controls without production-only test seams. No tests retired. Detailed assertions and value cards are in engineering-test-plan.md.

## Performance review

P1: Known and staged UPC checks precede lookup, so repeat scans do not consume quota. No persistent cache or provider fallback chain. External quota exhaustion uses manual entry; no retries. Actual lookup coverage/rate at the hotel is unknown.

P2: Measure actual full-catalog token/byte size against model budget before live voice use; do not silently truncate. An oversized context makes voice unavailable with feedback until evidence supports a revised design. One model request in flight, finite five/thirty-second bounds and no writer lock held over provider calls. Actual catalog size, latency and cost are unverified. Existing Sheets reads use bounded grids up to 100001 rows and may slow with ledger growth; no database rewrite for this prototype. Test representative 50-60-line baskets and the 200-line boundary. Metadata can hit the existing 65536-byte request guard first: reject oversized input definitively before dispatch, retain editability, and never label it an uncertain save. No larger cap or automatic splitting selected.

## What already exists

Reuse app/main.py local authentication, app/inventory.py guarded writer, app/sheets.py typed cells/formula validation, app/recovery.py durable journal, app/demo.py fault simulation and app/static/app.js basket/recovery UI. Existing withdrawal and receiving regressions remain mandatory. No schema/balance synchronization with the legacy voice workbook.

## NOT in scope

No-barcode creation, fractions, case conversions, operator/destination, multi-clerk deployment, offline cloud voice, formal MCP, continuous/queued voice, paid barcode service and production handoff are excluded. Observe real examples tomorrow for later decisions.

## Implementation Tasks

Rough estimates assume current fixtures and exclude account waiting; agent estimates are not delivery guarantees.

- [x] T1 (P1; human 4-6h / CC+gstack 1-2h): Extend payload/identity, new-item batch/evidence, capture labels and compatible recovery. Files: app/inventory.py, app/sheets.py, app/recovery.py if needed, tests/test_inventory.py. Source: persistence extension. Verify faults/restart, capacity and exact old receipts.
- [x] T2 (P1; human 2-3h / CC+gstack 30-60m): Add CaptureAssistance, configuration and guarded routes. Files: app/capture.py, app/config.py, app/main.py, tests/test_capture.py. Source: providers/context. Verify offline fixtures, validation, timeouts and hostile text.
- [x] T3 (P1; human 4-6h / CC+gstack 1-2h): Add editable staged items, microphone/clarification states and atomic draft mutation. Files: app/static/app.js, index.html and existing stylesheet (verify name). Source: CQ1 and voice lifecycle. Verify real controls, refresh and stale/duplicate responses.
- [ ] T4 (P1; human 1-2h / CC+gstack 30-60m plus target-device time): Run regressions, API setup and capped live semantic rehearsal. Source: G1-G6/P2. Verify catalog fit, device/scanner/browser and approved test workbook. Record actual cost and limits.
- [x] T5 (P2; human 30-60m / CC+gstack 10-20m): Update README, .env.example and demo runbook for setup, fallback, recovery and observations. Source: distribution/readiness. Verify no credentials in browser/repository/logs.

Sequential implementation, no parallelization opportunity: shared request contracts, app/main.py and app/static/app.js couple these tasks. T1/T2 establish contracts, T3 integrates, then T4 validates; T5 can be drafted early and verified last. No agent/worktree launch required.

## Laptop setup and acceptance

Help the user create/select an API project, enable API billing if needed, create a project key and store it only in local server configuration. User performs account/billing/key actions; never paste secrets into chat. Verify actual implemented setting names before supplying commands. No setup or expenditure happened in review. After implementation, verify model access and representative behavior within the approved cumulative $5 task cap, recording spend and stopping before the cap.

Rehearse known scan; complete/failed lookup; multiple new items; two-item voice; add versus set; remove/cancel; ambiguous vodka with one/multiple matches; stale response after manual edit; discard clarification; refresh/network failure; and verified receiving/withdrawal recovery. A model saying saved never substitutes for a verified receipt. Target laptop, microphone, scanner and approved test spreadsheet acceptance remain unverified.

Observe missing barcodes, case/portion handling, request sizes, noise/light, power/Wi-Fi and staff corrections. These observations do not expand today's implementation scope.

## Outside Voice

Design-spec cold review passed earlier; it does not establish engineering outside coverage. Claude CLI preflight was not installed; required Plan/TaskOutput/TaskStop fallback tools are unavailable. Record unavailable coverage, no replacement general-purpose agent, no cross-model agreement. Native architecture/code/test/performance review completed.

## Completion summary

FULL_REVIEW: scope accepted as-is. Saved reality evidence: 12/12 rows, five unverified premises retained. Architecture 15 findings; code quality two; tests six gap families; performance two: 25 total. All remedies mapped; zero unresolved design decisions. Zero critical gaps lacking both handling and planned tests; implemented readiness is not established. No TODOS.md additions. Zero parallel lanes. Lake score N/A. Baseline unchanged: 83 passed/one warning, no new tests run. API setup, catalog fit and live acceptance are execution prerequisites. The detailed report retains historical question snapshots; the final ledger supersedes their former pending states.

## Implementation execution record (October 25, 2026)

T1, T2, T3 and T5 implemented. T4 offline verification completed: 145 pytest cases pass with the existing dependency warning; isolated browser fixtures exercise actual controls/routes, timeout/late-result protection and responsive layout. See [pre-demo runbook](../pre-demo-runbook.md) for evidence and execution commands. The user selected offline verification because API setup is not yet complete. Live model calls: zero; spend: $0. T4 live API/catalog/Google and target-laptop microphone/scanner acceptance remain deferred, not passed. Historical review sections above retain their original baseline evidence.
