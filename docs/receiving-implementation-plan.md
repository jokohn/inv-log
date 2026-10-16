# Inventory receiving implementation handoff

Status: Implemented October 15, 2026 with automated and isolated browser verification. Live receiving and physical-scanner acceptance remain outstanding; see [verification evidence](verification.md). The requirements and historical planning limitations below are retained.

Add supplier-delivery receiving to the existing scanner-to-basket application. Reuse its save, verification, and recovery machinery while preserving withdrawal behavior and existing saved work. This document records the user's decisions and the implementation requirements for the next development agent.

This extends [the original architecture plan](architecture-plan.md), which excluded receiving from the first build. The receiving exclusion is superseded by this handoff; other architecture constraints remain. Read [verification evidence](verification.md) for the existing implementation's verification history.

## Agreed scope

| Decision | Agreed behavior |
| --- | --- |
| Inflows | Supplier deliveries into the existing single stock pool |
| Products | Existing catalog products only; unknown barcodes do not create products |
| Quantities | Positive whole catalog units; no case-to-bottle conversion |
| Delivery information | No supplier, invoice, delivery-reference, or note input |
| Mode selection | Choose Withdraw stock or Receive stock before scanning; switch only with an empty basket |
| Implementation structure | Extend existing modules and share save/recovery behavior; no separate receiving service |
| Existing saved work | Read old drafts, journal records, and receipts as withdrawals; do not rewrite history |
| Repeated scanning | Each intentional scan adds one catalog unit; repeated scans of the same barcode increment one basket line |

The repeated-scanning requirement is explicit user feedback, not an optional enhancement. Receiving must retain all three quantity-entry options: repeated barcode scans, plus/minus buttons, and direct quantity entry. Users may combine them within one basket.

For a product counted by bottle, two cases of 24 bottles must be entered as 48 bottles. A scan represents one bottle, never an inferred case size. Display the catalog counting unit beside the quantity.

Out of scope: returns, location transfers, new-product creation, packaging conversion, a correction UI, purchase-order matching, supplier management, staff authentication, multiple independent writers, and offline saving. Existing controlled manual adjustments remain supported.

## User workflow

1. With an empty basket and no save/recovery lock, choose Receive stock.
2. Scan an exact catalog barcode. Add a line with quantity 1.
3. Scan that barcode again to increment the same line. Preserve leading zeros and exact matching.
4. Adjust quantities with further scans, plus/minus controls, or direct entry. Removing a line continues to work.
5. Review products, counting units, and quantities. The save action explicitly says Receive stock or Record receipt.
6. Submit the entire basket. Show a verified confirmation only after reading back the exact transaction rows and expected balances.
7. Show receiving as positive stock movement in both the confirmation and recent activity. Old withdrawals retain negative presentation.

Block mode changes when the basket contains items, while sending, and while any save is unresolved. An empty-looking basket must not bypass the recovery lock. Preserve mode with the draft through reload and recover the original mode after an interrupted submission.

Preserve existing scanner focus/readiness behavior. The scanner beep confirms capture only; the verified confirmation establishes that inventory changed.

## Existing components to reuse

| Component | Current behavior | Receiving work |
| --- | --- | --- |
| `app/static/app.js` | Exact barcode lookup, repeated-scan consolidation, quantity controls, browser drafts, submission and recovery | Store movement type, share scanning/quantity behavior, enforce mode lock, render correct signs and labels |
| `app/static/index.html`, `app/static/styles.css` | Withdrawal-oriented page and basket | Add accessible mode selection and direction-aware presentation |
| `app/main.py` | Local API, Host/Origin/session-token protection, withdrawal and recovery routes | Expose receiving through the same security boundary and inventory service |
| `app/inventory.py` | Validation, canonical request identity, serialized writes, journal intent, verification and recovery | Make direction explicit throughout; retain legacy withdrawal compatibility |
| `app/sheets.py` | Typed ledger validation, signed balance formulas, bounded reads and one batched write | Accept receiving rows with positive Unit Change; preserve existing withdrawal/adjustment validation |
| `app/recovery.py` | SQLite journal containing serialized payload, evidence, and receipt | Preserve existing records; update consumers of stored data as needed |
| `app/demo.py` | Simulated provider that sums signed changes | Exercise receiving through the same application path; change simulator only if required |
| `tests/test_inventory.py` | Withdrawal validation, retry, corruption, security, concurrency and failure tests | Extend relevant cases to receiving and add legacy-compatibility assertions |

The existing formula is Opening Count plus signed transaction changes. The existing Transaction Type column can distinguish receiving. No new spreadsheet columns, opening-count reset, or replay of old transactions is needed for the agreed feature.

## Implementation requirements

### Direction and validation

Use explicit withdrawal and receiving transaction types. Keep input quantities positive for both; derive the signed Unit Change on the server. A receiving row adds quantity and a withdrawal row subtracts it.

Validate products and quantities against fresh data before writing. Receiving must work when current stock is zero and when delivered quantity exceeds current stock. Insufficient-stock rejection remains specific to withdrawals. Preserve whole-basket validation, existing quantity/basket limits, literal text handling, and rejection of unknown products or malformed history.

Receiving rows use the existing product snapshots, UTC timestamp, device, capture method, and request/line identity fields. Note and Related Request ID remain blank for receiving. Do not reuse `adjustment` as the delivery type: corrections have different existing rules.

Retain the existing API route's withdrawal meaning for old clients. A separate receiving route calling the same inventory service is a suitable implementation approach; exact route and internal field names are engineering details, not additional user requirements. Reject unsupported or contradictory types rather than silently interpreting them as withdrawals.

### Request identity and compatibility

The current canonical payload contains only a product-to-quantity map. New receiving identity must also distinguish direction. The same request ID with changed quantities, products, or direction must conflict, even if the product quantities otherwise match.

Compatibility requirements:

- Recognize the actual legacy product-to-quantity payload shape as a withdrawal. New version/type fields must not become fake product lines in pending-state rendering.
- Treat old browser drafts and old stored receipts without a movement type as withdrawals.
- Preserve IDs, payloads, evidence, timestamps, and ledger rows. Normalize for interpretation/comparison without rewriting historical records.
- A verified old withdrawal retry returns its original result without another write, including after later legitimate transactions change stock.
- An old pending withdrawal still recovers as a withdrawal, using its exact saved evidence.
- Missing legacy fields are different from invalid new fields: do not default an explicitly unknown type to withdrawal.
- Freeze direction and contents once sending starts. Recovery must not use whichever mode is currently selected on screen.

Update receipt generation, recent activity, status, and pending-state consumers together. The current receipt calculation assumes every ledger change is negative; merely changing the write sign would produce incorrect receiving quantities.

### Save and recovery guarantees

```text
Mode + barcode scans / quantity edits
                 |
        Persist draft and request ID
                 |
      Shared serialized inventory service
                 |
 Validate identity, products, quantity, direction
                 |
 Fresh stock check (availability gate for withdrawal only)
                 |
        Journal intent before dispatch
                 |
    Typed transaction batch + any range expansion
                 |
        Read exact rows and balances
          /                       \
 Verified confirmation       Uncertain or mismatched
                             Lock both modes; recover
```

Maintain one shared lock and recovery gate for both directions. Do not add a second save implementation or a receiving-specific journal. A failed journal write must prevent provider dispatch. Definitive rejection may permit the existing safe retry; ambiguous absence after dispatch must not authorize a resend or a new request ID.

Use the same atomic batch builder and balance verification. If rows exist but balances cannot be verified, retain the unresolved state. Mixed receiving/withdrawal history must not invalidate a previously verified receipt solely because the balance changed later.

### Deployment and performance

Keep loopback-only hosting, existing credential handling, local access checks, and the single-writer restriction. Receiving does not require additional per-product network calls; scans remain local basket edits until submission. Preserve current ledger capacity checks and formula expansion.

The application still reads full bounded history. Receiving increases that history; performance near the row limit is unverified. This feature does not introduce a cache or a concurrency redesign.

Old application versions reject receiving transaction types. Stop the old app before upgrading and do not assume it can run against a ledger after the first receiving transaction. Document this compatibility limitation without deleting receiving history or resetting the inventory baseline. Resolve any uncertain submission before operational cutover.

## Development sequence

1. **Restore a runnable test baseline.** Investigate the recorded dependency import failure below and rerun the existing suite. Do not change dependency versions blindly.
2. **Extend direction-aware domain behavior and compatibility.** Implement receiving in the shared service, ledger validation, request identity, receipts, pending/status interpretation, and API. Add meaningful backend regression tests alongside it.
3. **Extend the existing interface.** Add mode selection, persisted direction, direction-aware copy/signs, and mode locking. Reuse the existing scan and quantity controls.
4. **Verify browser behavior and recovery.** Exercise the scenarios below against isolated demo state, including legacy drafts and interrupted submissions.
5. **Update operating documentation.** Explain receiving, catalog units, repeated scans, verification, and the older-version limitation in README and record actual test evidence in `docs/verification.md`.
6. **Perform live acceptance on approved prototype data.** Inspect the original configured Sheet's transaction rows and balances; keep hardware and provider verification distinct from simulated tests.

Sequential implementation is appropriate: domain/API contracts feed the interface, and integration checks depend on both. No new framework, dependency, migration utility, or service is required by the agreed scope.

## Acceptance and regression checks

Extend existing parameterized tests where they already exercise the relevant behavior. Test observable results at the application/provider boundary rather than internal helper structure.

| Scenario | Required result | Verification |
| --- | --- | --- |
| Receive 48 bottles with 10 on hand | One positive change of 48; verified final balance 58 | Integration and approved live Sheet |
| Repeated receiving scans | Five identical scans yield one line with quantity 5; saving increases stock by exactly 5 | Browser, then physical scanner |
| Combine quantity-entry methods | Scan twice, press plus once, enter 7, scan once more: one line with quantity 8; save exactly 8 | Browser |
| Receiving and withdrawal parity | Same barcode matching, consolidation, editing, removal, focus, and Enter behavior in both modes | Browser and regression suite |
| Empty basket or invalid quantity | Reject zero, negative, fractional, boolean, string API quantities, and quantities above existing limits; no write | Integration and browser |
| Zero stock or receipt larger than stock | Receiving succeeds; withdrawal still enforces available stock | Integration |
| Unknown barcode or stale/missing product | Do not guess or create a product; do not partially save the basket | Browser and integration |
| Exact barcode text | Preserve leading zeros; an altered barcode does not match | Browser and integration |
| Mode switching | Allowed with an empty unlocked basket; blocked with items or any send/recovery lock | Browser |
| Reload unsent receiving basket | Restore direction, products, quantities, and identity correctly | Browser |
| Double click or duplicate request | Same ID, contents, and direction produce one saved transaction set | Browser and integration |
| Conflicting direction | Same ID and products/quantities but opposite type is rejected without a write | Integration |
| Two intentional identical deliveries | Distinct request IDs each save once; no invoice-based deduplication is claimed | Integration |
| Concurrent receiving and withdrawal | Shared serialization; correct final balance and fresh withdrawal availability check | Integration |
| Timeout after commit or crash before receipt | Recover exact rows and balances without recording a second addition | Fault-injected integration and restart |
| Timeout with ambiguous absence, partial rows, or changed history | Both directions remain paused; no blind resend | Fault-injected integration |
| Definitive provider rejection | Basket retained; same-identity safe retry follows existing rejection rules | Integration |
| Readback unavailable | No success claim; recover and verify before new transactions | Fault-injected integration |
| Legacy draft, pending record, or verified receipt | Interpret as withdrawal; preserve original IDs, quantities, signs, and recovery result | Seeded legacy fixtures and browser |
| Earlier receipt after later movements | Return original verified receipt without a duplicate write or false balance-conflict failure | Integration |
| Mixed ledger types and invalid signs | Accept valid withdrawals, receiving, and adjustments; reject wrong-sign/type combinations | Integration |
| Formula range expansion | Receiving beyond initial coverage expands formulas and writes rows together | Integration; live provider evidence if exercised |
| Local access boundary | Receiving rejects missing session token and untrusted origin just like withdrawals | API integration |
| Final presentation | Positive receiving quantities, negative withdrawals, correct resulting stock; no reference field | Browser |

Each receiving failure test protects against the corresponding false success, duplicate addition, wrong direction, or loss of pending work. Existing withdrawal-only fixtures do not establish receiving coverage. Retain withdrawal, migration, and credential tests; none is made obsolete by this feature.

## Evidence and handoff limitations

Source inspection confirmed the reusable signed balance model and withdrawal-specific assumptions in the request payload, ledger validator, receipt calculations, and browser UI. No receiving code was implemented during planning.

The planning-session command `.venv\Scripts\python.exe -m pytest -q` failed during collection with:

```text
ImportError: cannot import name 'ArgsKwargs' from 'pydantic_core._pydantic_core' (unknown location)
```

No tests ran in that attempt. The cause was not established. Historical passing results in `docs/verification.md` are not a current passing baseline and do not validate receiving. Independent outside review was unavailable; no completed automated engineering-review certification is claimed.

For live acceptance, use approved prototype data and visibly verify both the receiving transaction and updated balance in the original Google Sheet. Demo/provider simulation does not prove actual formula recalculation or physical-scanner behavior. Correct test data through documented adjustments rather than deleting history.

## Decision record

The user selected supplier deliveries (D2 A), existing catalog units (D3 A), no reference field (D4 C), empty-basket-only switching (D5 A), existing-module implementation (D6 A), and legacy records interpreted as withdrawals (D7 A). The user then explicitly required repeated scans as an alternative to quantity buttons or direct entry for receiving, and requested this repository handoff.

No product-scope decision remains open. Engineering details may be resolved within these contracts; escalate a concrete conflict rather than silently changing scope. This handoff does not authorize live inventory writes as part of document preparation.
