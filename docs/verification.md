# Prototype verification

Implementation date: October 14, 2026. Target deployment remains the user's MacBook Pro; implementation and automated checks ran on Windows with Python 3.12.14.

## Verified in this build

- **30 backend/integration test cases passed.** Real parser, request orchestration, typed batch construction, and durable journal exercised through an injected Google-client simulator.
- Repeated request identity returns the original receipt without a second write; changed content conflicts. Distinct intentional requests each save once. Two simultaneous calls serialize correctly.
- Empty/unknown/invalid quantities, insufficient stock, duplicate catalog identities/barcodes, numeric barcodes, and damaged formulas prevent writes. An exact-stock withdrawal reaches zero.
- Leading zeros survive transaction write/readback. Formula-looking product text is written as a literal string.
- A rejected write is safely retryable. An ambiguous absent write blocks further submissions. Timeout-after-commit and simulated process termination recover without double deduction. Partial history remains unresolved. Known-saved readback failure blocks writes until verified.
- Formula capacity expands with the transaction in one batch. Migration fixture preserves the live baseline once and excludes old history from the new ledger.
- Host/origin/session-token boundary, second-instance lock, and state/workbook identity checks passed.
- JavaScript syntax check passed.

The automated suite reports one upstream Starlette deprecation warning for its httpx test-client adapter; it does not affect these test results.

## Browser checks performed

Actual local browser interaction through the Codex browser tool:

1. Two Enter-terminated `000780000011` scans consolidated to quantity 2.
2. Altered barcode `0780000011` was rejected without changing the basket.
3. Reload restored an unsent basket.
4. Browser testing exposed a quantity-commit bug. Input now updates the draft immediately, and submit independently reads/validates displayed quantities.
5. After fixing it, quantity 49 against 46 available was rejected, with the basket retained and no additional ledger write.
6. Editing to 3 produced a receipt for exactly 3 units, with 43 remaining after earlier demo testing.
7. Adding then removing Tepache restored the empty basket and disabled submit.

Screenshots in the local ignored `artifacts/` folder show the workspace and verified receipt. Demo state retains the test withdrawals for inspection; it is excluded from source distribution.

## Not yet verified

- Google service-account policy, permissions, live API reads/writes, actual formula recalculation and capacity expansion, or migration against the real spreadsheet. No real workbook was modified.
- Fresh installation on macOS, the D5100's connection/Enter suffix on that MacBook, or physical-scanner behavior in this app.
- Cross-machine concurrency, external collaborator edits, or operational performance at the stated row limit. These remain outside the single-writer prototype's guarantees.

## Live staging follow-up — October 14, 2026

The original live migration encountered a formula error after its write. Inspection confirmed that all three staging tabs existed, but two Current Count formulas reported `N_A: Argument must be a range`. The initial batch interleaved tab creation and formula writes, referencing the transaction tab before its creation. Migration now creates all tabs first. Validation also accepts Google's canonical omission of unnecessary sheet-name quotes.

With the user confirming the app was stopped, the repair checked the approved backup fingerprint, original tab contents, both staged products and opening counts, provenance metadata, empty staged ledger, and empty local withdrawal journal. Only the two Current Count formulas were rewritten. Subsequent Google reads verified both calculated balances against the approved opening counts, an empty ledger, and unchanged original tabs. Repair evidence is stored in the ignored `.state/migrations/` folder.

All **47 tests passed** on the installed Python 3.14 after the credential, connection-message, and migration fixes. Tests include formula-write ordering, Google formula canonicalization, and rejection of repairs with altered baseline data or existing transactions.

This follow-up supersedes the original build's unverified migration status above. Live withdrawal/adjustment writes, capacity expansion, physical-scanner testing, and MacBook installation remain unverified.

## Live acceptance checklist

After following README setup and approving a reconciled baseline:

1. Verify the exact target spreadsheet ID and exclusive writer arrangement.
2. Inspect, back up, approve, stage, and compare every opening count. Preserve legacy tabs and record cutover provenance.
3. Launch on the MacBook and scan representative physical barcodes, including a leading-zero example. Verify Enter suffix, one-unit additions, repeated scans, focus behavior, edits, and removal.
4. Record one deliberate approved withdrawal. Check the matching request/line set and expected formula balances **in the original configured Google Sheet**.
5. Restore test stock through a documented adjustment, not by deleting history. Verify the adjusted formula balances.

Passing simulated tests or showing a receipt in demo mode does not complete these live acceptance checks.

## Receiving implementation — October 15, 2026

Implemented supplier receiving in the existing service, ledger parser, API, and browser interface. `/api/withdrawals` retains its meaning; `/api/receiving` uses the same serialized save/recovery path. Quantities remain positive in requests; only the server derives signed ledger changes. Canonical v2 payloads include direction; historical product-to-quantity maps remain withdrawals without rewriting their stored payload or evidence.

### Current automated evidence

**83 tests passed** on Windows / Python 3.14.3 using `.venv/Scripts/python.exe -m pytest -q --basetemp=artifacts/pytest-receiving-final`. JavaScript syntax and `git diff --check` passed. The existing upstream Starlette test-client deprecation warning remains.

The original 47-test baseline passed before feature edits. The planning import failure was caused by Python 3.12 compiled binaries in a Python 3.14 virtual environment: `pydantic_core` and `_cffi_backend` carried `cp312` filenames. Reinstalling the already-pinned `pydantic_core==2.50.1` and `cffi==2.1.1` with Python 3.14 wheels restored the baseline; requirements were not changed. Tests required execution outside the sandbox because its temporary-directory permissions failed.

Receiving regression coverage includes 10 + 48 = 58, zero stock, deliveries exceeding current stock, consolidation, stale products and whole-basket rejection, invalid quantities, duplicate concurrent requests, opposite-direction and changed-content conflicts, distinct intentional deliveries, shared receiving/withdrawal serialization, capacity expansion, mixed adjustments, literal product text, invalid ledger signs/types, API session/origin checks, journal failure, rejection/retry, timeout before/after commit, crash/restart, unavailable readback, partial history, and changed post-save balances. Seeded actual legacy payload maps and receipts verify pending recovery, original verified receipts after later receiving, and unchanged IDs/payload/evidence/creation timestamps.

### Browser evidence

Real browser interactions used isolated demo state under `artifacts/receiving-browser-verified` (port 8877), plus test-only seeded fixtures under `artifacts/receiving-fixtures` (port 8880). No live credentials or Sheet writes were used for these checks.

- Two scans, plus once, direct entry 7, then another scan produced one line of 8. Reload retained Receive stock, quantity 8, and its draft. Double-clicking Receive stock produced one +8 receipt and 56 on hand from 48. Request: `9541e8d5-0da6-4833-afdb-acb51e4f9123`.
- Five intentional identical scans produced one line of 5; saving showed +5 and 61 on hand. Request: `a638bb90-7af6-4e11-993e-13e4b6a25bae`.
- Altered barcode `0780000011` was rejected; exact `000780000011` worked. Capture focus returned after scans. Catalog units remained visible.
- Mode selection was disabled with basket items. Removal restored an empty basket and enabled switching. Quantity 0 disabled receiving submission with a validation message.
- Withdrawing 62 from 61 was rejected without a write. Correcting to 1 showed a negative receipt and 60 on hand. Recent activity displayed both signed directions.
- A seeded old draft without direction restored as Withdraw stock and saved -2. A seeded interrupted receiving request restored the original receiving mode and locked scanning, editing, and mode switching; Check recovery returned +2 and the expected 48 balance without another addition.
- An explicitly unknown draft direction blocked capture instead of being treated as a withdrawal.
- Starting with an empty browser draft while the journal held an ambiguously absent receiving save restored that pending basket and receiving mode. Recovery checks and reload kept both modes locked; no success was claimed.
- No browser JavaScript errors were reported in the inspected console logs. Final browser files were reloaded after the draft-validation edit.

Visual receipt evidence: `artifacts/receiving-receipt.png` (ignored local artifact). Test fixture server source is retained locally at `artifacts/browser_fixture_server.py`; it is not part of the production app.

### Remaining acceptance

Live receiving rows and balances in the original configured Google Sheet, actual Google formula recalculation/capacity expansion, physical D5100 repeated scans, MacBook installation, and performance near the ledger limit remain unverified. Approve a specific prototype delivery and establish exclusive writer access before live acceptance. Preserve receiving history; correct test stock through documented adjustments. Older app builds reject receiving ledger rows and must not be used after the first live receipt.
