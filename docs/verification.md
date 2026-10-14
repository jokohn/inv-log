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

## Live acceptance checklist

After following README setup and approving a reconciled baseline:

1. Verify the exact target spreadsheet ID and exclusive writer arrangement.
2. Inspect, back up, approve, stage, and compare every opening count. Preserve legacy tabs and record cutover provenance.
3. Launch on the MacBook and scan representative physical barcodes, including a leading-zero example. Verify Enter suffix, one-unit additions, repeated scans, focus behavior, edits, and removal.
4. Record one deliberate approved withdrawal. Check the matching request/line set and expected formula balances **in the original configured Google Sheet**.
5. Restore test stock through a documented adjustment, not by deleting history. Verify the adjusted formula balances.

Passing simulated tests or showing a receipt in demo mode does not complete these live acceptance checks.
