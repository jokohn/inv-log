# Hyatt inventory capture prototype — architecture plan

Follow-on scope: [Inventory receiving implementation handoff](receiving-implementation-plan.md) adds supplier deliveries, including repeated-scan quantity entry. It supersedes this original plan's exclusion of receiving; the original first-build scope and historical evidence below are retained.

Date: October 14, 2026 (America/Chicago)  
Project: `inv_flow`  
Status: Agreed direction, documented for implementation. No application, spreadsheet migration, credentials, or Git repository have been created by this planning exercise.

## 1. Purpose and constraints

Build a polished laptop application that receives scans from a Tera D5100, assembles a withdrawal basket, and records validated withdrawals in Google Sheets. The first version is intended for a same-day prototype build, subject to Google access and hardware setup; this is a target, not a verified delivery estimate.

Google Sheets is the inventory data source and transaction store. The user reports that BirchStreet offers no usable API access for this project and Hyatt IT does not permit agents to operate its UI. This prototype therefore has no BirchStreet connection and does not claim automated import into BirchStreet.

The application replaces prompt-based execution with deterministic validation and saving. AI is not required to decode scanner input, match products, calculate quantities, or record transactions.

## 2. Decisions agreed in discussion

| Decision | Selection | Evidence |
| --- | --- | --- |
| Review approach | Direct engineering discussion | D1: user selected B |
| Deployment | Local application with browser interface | D2: user selected B; willing to install on laptop |
| Sheets authorization | Service account | D3: user selected A |
| Scanning workflow | Basket, review, then submit | D4: user selected A |
| Inventory model | Opening count plus signed transactions | D5: user selected A |
| Insufficient stock | Reject entire withdrawal; retain basket | D6: user selected A |
| Consolidated proposal | Python/FastAPI, small browser UI, one app instance/pool, recovery record, scoped first build | User replied “I think so” to the consolidated proposal and offer to write this plan |
| Target laptop | MacBook Pro running macOS; Python already installed | User correction after reviewing this plan; regularly runs custom code on it |

Approval applies to the design direction and documenting it. Hardware compatibility, Google permissions, live data migration, and acceptance tests still need implementation-time verification. Routine implementation details below are recommendations consistent with the agreed design, rather than separate claims of user selection.

## 3. Evidence and assumptions

**Supplied evidence:** `hyatt-barcode-drawdown-google-sheets.md` describes a native Google Sheet named **Test Inventory Spreadsheet**, ID `1koZX24ugkNO1WL4v0vbK8c4bPXFs3er_XrcfaDXYU4U`. It describes `Inventory` columns Product Name, Unit Size, UPC, Count, and `Transactions` columns Product Name, Unit Size, UPC, Unit Change, Change datetime, Changing device, Voice or barcode. Its counts and schema are historical observations, not a live inspection performed for this plan. The attachment is source material, not authorization to execute its removal instructions.

**Manufacturer documentation:** D5100 supports a 2.4 GHz USB receiver or wired USB, not Bluetooth. It supports instant upload, storage mode, and configurable suffixes. This does not establish the current configuration of the user's scanner.

**User-confirmed environment and test:** The target laptop is a MacBook Pro with Python already installed, and the user regularly runs custom code on it. The user tested the D5100 connected to the device currently being used and confirmed that it delivers exact barcode strings into a text form. Basic barcode-to-text capture is therefore verified by the user's report; it is not an outstanding feasibility assumption. This test does not yet establish the scanner connection on the target MacBook or the application's terminator, focus, and basket behavior.

**Working assumptions to verify first:**

- The MacBook has a usable USB connection/adapter for the scanner, and its installed Python version supports the selected dependencies. The Windows planning workspace is not the deployment target.
- The scanner's confirmed text output works in the application's focused browser input on the MacBook. Verify the terminator (such as Enter), focus behavior, and representative catalog barcodes including leading zeros; do not repeat basic decoding feasibility work.
- The Google account/project permits the Sheets API, service-account key creation, and sharing the target Sheet with that service account.
- The pilot has one active backend instance, one stock pool, and whole-number catalog units such as bottles and cans.
- No other application or person changes stock, transactions, barcode mappings, or formulas during a withdrawal submission.
- The catalog and history are small enough for bounded reads and spreadsheet formulas. Actual row counts are unknown; no capacity or latency benchmark has been run.

These are launch prerequisites, not verified capabilities. If any fails, resolve it before claiming end-to-end readiness.

## 4. Architecture and boundaries

```text
Tera D5100 -- USB receiver or cable --> Browser at localhost
                                            |
                                    same-origin HTTP
                                            |
                               Local Python / FastAPI server
                               - request validation
                               - one serialized write path
                               - Google Sheets adapter
                               - local recovery journal
                                            |
                                  Google Sheets API / HTTPS
                                            |
                                  Inventory + Transactions
```

Use Python/FastAPI to serve the API and static HTML/CSS/JavaScript from one origin. Avoid a separate frontend development server or mandatory Node build pipeline for the initial version. Use the official Google Python client/auth libraries for Sheets access, with tested versions pinned during implementation.

Target macOS for installation and launch instructions: use the existing Python installation with a project virtual environment, portable paths, and a macOS-compatible launcher. Keep runtime code platform-neutral so development in the current Windows workspace does not introduce PowerShell-only startup steps or Windows-specific credential/state paths. Confirm the installed Python version during setup rather than assuming a fresh Python installation is needed.

Google Sheets remains authoritative for the catalog and inventory history. A small local SQLite journal stores only request identity, canonical payload, state, and recovery evidence. It is not a second inventory database and must not become the source of stock balances.

Run one backend worker with a submission lock and enforce one instance for the configured local state directory. Multiple browser tabs must pass through the same serialized write path. A second machine or a different local state directory can bypass that coordination; this release provides no cross-machine lock.

Bind only to loopback, validate allowed hosts/origins, and protect mutation requests with a per-session token. Do not expose the app to the LAN, enable broad CORS, or accept browser-supplied spreadsheet IDs or arbitrary ranges. Validate all submitted quantities and product identities again on the server.

Store the service-account key outside the repository and outside distributed packages. Configuration contains its local path, the exact spreadsheet ID, tab names, and a device label. Use Sheets access only; do not grant broad Google Cloud project roles to the runtime account. Share only the intended prototype spreadsheet. Never return credentials to the browser or include keys/tokens in logs.

An operator label, if later added, is self-reported unless real user authentication is introduced. A device label is not an authenticated operator identity.

## 5. User interface and capture behavior

The main screen has three areas: scan/product feedback, withdrawal basket, and recent verified withdrawals. Connection and save status remain visible. Show product names, unit labels, quantities, and stock clearly; status must not rely on color alone.

1. Open the local app and complete its connection/schema checks.
2. Focus the dedicated scan field; display an obvious ready/not-focused indicator.
3. A terminated scan looks up the exact barcode in the loaded catalog.
4. One unique match adds one catalog unit. A deliberate repeated scan increases that product's basket quantity.
5. Unknown or duplicate barcodes produce an actionable error and do not alter the basket. They do not silently create products.
6. The user can change positive whole-number quantities or remove a basket line.
7. Select **Record withdrawal**. Freeze that submission's contents while saving.
8. On verified success, clear the submitted basket and show a receipt. On validation failure, keep it editable. On uncertain saving, keep it visible and locked pending recovery.

Use manual-trigger, instant-upload scanner behavior for the pilot. Storage-mode replay and continuous scanning could create unintended repetitions and must not be treated as supported until separately designed and tested. Preserve input as text; remove only the verified scanner terminator. Do not strip zeros, pad, infer pack sizes, or silently normalize barcode variants.

Do not intercept all keyboard input globally: quantity fields and other controls need normal typing. Re-focus the scan field after adding an item without stealing focus while the user edits quantities. A scanner beep indicates capture, not a successful inventory update.

Persist an unsent draft locally for refresh recovery, including its spreadsheet identity. Restore submitted/pending work from the backend journal rather than converting it back into a new draft. Product/stock information shown while scanning is advisory; submission always rechecks live data.

## 6. Spreadsheet design

Retain the conceptual `Inventory` and `Transactions` tabs. Use headers and stable identities, not hardcoded catalog row numbers. Add a schema version in documented metadata so startup can reject an incompatible workbook clearly.

### Inventory

| Field | Type / rule |
| --- | --- |
| Product ID | Immutable unique text identifier; links history to catalog |
| Product Name | Editable display name |
| Unit Size | Counting unit; no case conversion in v1 |
| UPC | Exact text; one unique active product match |
| Opening Count | Nonnegative whole number fixed at migration/cutover |
| Current Count | Protected formula: Opening Count + signed changes matching Product ID |

Product names and barcode corrections must not change Product ID. Do not reuse an ID for a new product or change the counting unit of an item with history without a migration. Products with history must not be deleted. Scan validation rejects missing IDs, duplicate IDs/barcodes, malformed counts, missing/error formulas, and unsupported units.

### Transactions

| Field | Type / rule |
| --- | --- |
| Request ID | Stable identity for one submitted withdrawal |
| Line Number | Unique within the request; one consolidated line per product |
| Product ID | Stable catalog reference |
| Product Name / Unit Size / UPC | Snapshot of catalog details at recording time; barcode remains text |
| Unit Change | Negative whole number for withdrawal; signed adjustment for controlled reconciliation |
| Change Datetime | Server timestamp in explicit UTC; display locally in America/Chicago |
| Changing Device | Configured device label |
| Capture Method | `barcode` for scanned withdrawal lines |
| Transaction Type | `withdrawal` or `adjustment` |
| Note / Related Request ID | Reason and optional reference for controlled corrections |

The last two fields support the agreed manual adjustment workflow without mislabeling an adjustment as a scan. Historical transaction rows are append-only. Controlled adjustments require a reason and a unique request/line identity; do not erase withdrawals to correct them. Receiving and adjustment screens are outside the initial build.

Use bounded formula ranges with documented capacity. The app must extend formulas/row capacity before exceeding it and verify that every newly written transaction is included. Reject a submission if calculated balances disagree with independently computed opening-count-plus-ledger totals. Protect balance formulas, opening counts, IDs, and history against casual editing; protections are safeguards, not a substitute for the single-writer operating rule.

## 7. Save, deduplication, and recovery contract

The browser creates and preserves a request ID before the first submission. The backend canonicalizes the basket and stores a payload fingerprint with that ID. Reuse with different content is rejected. A later intentional withdrawal gets a new ID even when its products and quantities are identical.

```text
Submit request
  |
  +-- invalid/empty quantities or payload ----------------> reject; retain draft
  |
  +-- acquire submission lock; inspect journal and Sheets
  |      +-- same ID, different payload ------------------> reject conflict
  |      +-- complete matching saved request -------------> verify; return receipt
  |      +-- unresolved previously attempted request -----> reconcile; no new write
  |
  +-- fresh catalog + complete relevant ledger + formulas
  |      +-- invalid schema/catalog or inconsistent stock -> reject; explain repair
  |      +-- any insufficient stock ----------------------> reject entire basket
  |
  +-- durably journal intent before dispatch
  +-- record all lines in ONE spreadsheets.batchUpdate
  |      +-- definitive rejection ------------------------> show failed; retain basket
  |      +-- timeout/unknown outcome ---------------------> pending recovery; block writes
  |
  +-- read back exact request lines and calculated balances
         +-- all match ----------------------------------> verified receipt; clear basket
         +-- missing/mismatched/uncertain ----------------> pending recovery; block writes
```

Use typed cell writes so barcodes remain strings and product text cannot be interpreted as a formula. Write all transaction lines atomically, including any necessary grid expansion in that batch. Do not write Current Count directly. API atomicity covers the write batch, not the preceding read/stock validation.

Verification compares the complete expected line set, product IDs, quantities, and request identity, then checks every affected calculated balance against the pre-save balance minus the submitted quantity. Stock mismatch or formula failure is not permission to write again. Record a known-saved-but-verification-failed state when appropriate.

Persist a send-intent state before the network call. After a crash, a prepared/sending/pending request is unresolved until checked. Absence from one read does not prove a timed-out write will never finish. Disable automatic retries of non-idempotent append/write operations, including client-library retries. Read retries may use bounded backoff.

If a full matching request is found, return its result without re-appending. If the result is ambiguous, partial, duplicated, or absent after an uncertain dispatch, pause all new withdrawals and require reconciliation. Do not reset its ID to get past the pause. This is conservative recovery, not a claim of general exactly-once or concurrent transaction guarantees.

On restart, recover unresolved requests before enabling submission. Keep journal data on the same device until resolved. Moving the code to another laptop does not transfer a pending operation; finish recovery first. SQLite durability or disk errors before sending must prevent dispatch.

## 8. Migration without double-counting

Migration is a separate, explicit operation; normal startup never rewrites a spreadsheet schema.

1. Inspect the exact live spreadsheet, headers, formulas, types, duplicates, and occupied transaction history. Record actual counts and stop on inconsistencies.
2. Establish an exclusive maintenance window and export/back up the original data. Verify the backup before modifying the live structure.
3. Prepare versioned staging tabs with the new schema. Assign stable IDs and keep UPCs as text.
4. Recommended cutover: use the reconciled live balances as new Opening Counts. Preserve old history in clearly labeled legacy/archive tabs and exclude it from the new balance formulas. Start the new ledger empty. Do not both carry forward current balances and replay old transactions.
5. Check every staged product balance against the approved cutover count and verify representative formulas and text barcodes.
6. Switch configured tabs only after those checks. Preserve the old tabs and document cutover time, mappings, and baseline provenance.
7. Before any post-cutover write, rollback can switch configuration to the preserved original tabs. After new transactions exist, reconcile them before any rollback; never discard them.

If live counts/history cannot be reconciled, stop migration for a physical/reconciled baseline rather than guessing. The old Markdown write workflow must not continue writing into the newly configured ledger.

## 9. Implementation structure and sequence

Suggested structure, to be created during implementation:

```text
inv_flow/
  README.md                  setup, daily use, troubleshooting
  requirements.txt           tested pinned dependencies
  .env.example               non-secret settings and key-file path example
  .gitignore                 credentials, environments, logs, local state
  app/
    main.py                  localhost server, API routes, static serving
    inventory.py             validation, stock calculation, submit orchestration
    sheets.py                Google API reads, typed atomic writes, verification
    recovery.py              SQLite request journal and recovery state machine
    static/                  HTML, CSS, JavaScript
  scripts/                   local launcher and explicit migration utility
  tests/                     domain, integration, browser workflow tests
  docs/architecture-plan.md  this plan
```

Keep one catalog parser and one validation/write path shared by submission and recovery. Do not build generic database adapters, a plugin system, cloud deployment, or a separate application database. Dependencies should be injected at the Google client boundary so failure tests exercise the real submission behavior without live writes.

| Task | Outcome | Dependencies | Validation |
| --- | --- | --- | --- |
| T1: Access and hardware preflight | Confirm MacBook Python compatibility and USB connection, app terminator/focus behavior, exact Sheet access, and credential policy; basic scanner text output already user-verified | User MacBook/account access | Scan into the app on macOS plus sandbox Sheet read/write check |
| T2: Schema and migration | Preserved legacy data, new IDs/opening counts/formulas, configured schema | T1 | Dry run then approved cutover; full balance comparison |
| T3: Backend and recovery | Validated baskets, atomic transaction writes, durable pending states | T2 schema contract | Automated failures/retries/restart and live sandbox checks |
| T4: Browser workflow | Scan feedback, editable basket, pending/error/receipt states | T3 API contract | Keyboard/browser tests and D5100 test |
| T5: Packaging and Git | Reproducible macOS installation using existing Python, portable launcher, and safe configuration template | T3–T4 | Clean virtual-environment setup on MacBook; inspect tracked files for secrets/state |
| T6: Acceptance demonstration | Real scan produces verified transaction rows and balances | T1–T5 | Evidence captured from app and original configured Sheet |

Build sequentially for this small prototype; separate worktrees or parallel agents are unnecessary. Start the access/hardware check before spending the day polishing UI. Initialize Git during implementation and distribute source plus pinned dependencies; do not distribute credentials or recovery state. CI, hosted releases, an installer executable, and automatic updates are deferred. Record a known-good commit and setup instructions for the laptop.

No precise implementation hours are asserted: authentication, migration data quality, and scanner configuration remain unknown. The same-day objective should be evaluated after T1.

## 10. Verification plan

No application tests exist or have been run. Use pytest for backend behavior and browser automation for the small critical UI flow. Test observable contracts, not implementation details.

| Scenario | Required result / regression prevented | Evidence level |
| --- | --- | --- |
| One scan and repeated intentional scans | Exact barcode preserved; one unit per capture; repeat increases basket quantity | Browser + actual scanner |
| Quantity editing, removal, empty basket | Positive whole quantities only; no empty withdrawal; no inventory change before submit | Domain + browser |
| Unknown/duplicate UPC or product ID | No guessed mapping and no write | Domain/integration |
| Whole basket stock validation | One insufficient product rejects all lines; sufficient/exact-stock withdrawal succeeds | Integration + sandbox Sheet |
| Stale basket | Fresh server data overrides stale display and revalidates every product | Integration |
| Double click/two tabs/same request ID | One saved line set; same ID with changed payload rejected | Browser + integration |
| Two distinct identical withdrawals | Both save once with distinct IDs | Integration |
| Failure before dispatch or definitive rejection | No saved lines; retained basket and clear error | Fault-injected integration |
| Timeout after provider commit | Recovery identifies exact saved request; no second deduction | Fault-injected integration + sandbox readback |
| Ambiguous timeout/absence or mismatched history | New submissions blocked; no automatic resend | Integration |
| Restart during send/after commit/before receipt | Durable journal retains identity and reconciles before new submissions | Process restart integration |
| Broken formulas or exhausted range capacity | Reject inconsistency or safely extend coverage; no invisible deductions | Sandbox Sheet |
| Credentials revoked/wrong Sheet/schema changed | Clear connection/setup error without exposing secrets or altering another file | Integration + configuration check |
| Migration with pre-existing history | Baseline preserved once; legacy history retained, not added twice | Migration fixtures + sandbox rehearsal |
| Local access boundary | LAN exposure disabled; untrusted origins and forged mutation requests rejected | Server integration |
| Refresh/focus loss/disconnection | Draft retained, capture readiness visible, pending submissions not converted into new withdrawals | Browser + hardware |
| Fresh installation | macOS setup using existing Python and a clean virtual environment launches the app without Windows-only steps, developer-only paths, or committed secrets | Target MacBook Pro |

Mocks prove application handling of simulated responses, not Google acceptance, formula recalculation, or scanner behavior. Each failure test should inject the credible failure at the real dependency boundary. Extend parameterized tests rather than duplicating tests for internal helper names.

Acceptance requires a deliberate hardware scan, basket confirmation, verified matching request rows, and the expected calculated balances in the original configured native Sheet. Use approved prototype data, and restore test stock with documented adjustment entries rather than deleting transaction history.

## 11. Engineering review: architecture, quality, tests, performance

**Architecture:** The largest risk is treating Google Sheets atomic writes as a transactional read/check/write system. The approved one-instance scope, serialized submissions, external-edit restriction, and conservative pending-state recovery bound that risk. They do not make this suitable for multiple independent writers. The backend, local disk, internet connection, and Google access are availability dependencies; failure retains work and blocks unsafe submission.

**Code quality:** Keep spreadsheet mapping, domain validation, and recovery separate. Typed error categories should distinguish setup errors, rejected baskets, definitive write failures, and unknown outcomes. Never collapse those into a generic “retry” button. IDs and canonical payload comparison are shared behavior across submit, receipt, and recovery, not duplicated logic. No existing repository code or reusable helper implementation was found to review.

**Tests:** The save boundary, migration baseline, scanner focus, and crash recovery deserve tests before cosmetic breadth. Proposed automated coverage is listed above; no coverage percentage or passing suite is claimed. Live checks remain mandatory for provider/hardware evidence.

**Performance:** Cache catalog data for scan responsiveness, then refresh at submit. Aggregate all basket lines in memory and use batched range reads and one atomic write instead of one network call per scan/product. Read complete relevant history in bounded chunks; do not assume the first blank row ends it. Avoid whole-column formulas where practical, and manage formula capacity explicitly. Read retries need deadlines and backoff; writes must not be automatically repeated after uncertain outcomes. Measure catalog size, history size, startup time, and submit/verification latency on real data. No numerical performance target has been validated.

## 12. Scope limits and remaining checks

Outside the first build: voice/photo decoding; multiple simultaneous laptops; offline transaction submission or scanner storage replay; case conversion; multiple locations; receiving/adjustment screens; authenticated staff roles; purchasing/reordering; BirchStreet automation; production hosting; desktop installer packaging.

The local application may retain unsent drafts during a disconnection, but this is not an offline inventory workflow. Final stock validation and all successful saving require Google connectivity.

No further product-choice decision is required to start implementation under the agreed scope. The target is confirmed as a MacBook Pro with Python, and exact D5100 barcode-to-text output is user-verified on the currently connected device. Outstanding factual checks are Python version compatibility, scanner connection and app input behavior on the MacBook, service-account permissions, live spreadsheet condition, and migration baseline. Any failed assumption must be reported and resolved rather than silently changing the architecture.

## 13. Sources and review limitations

- Supplied attachment: `hyatt-barcode-drawdown-google-sheets.md`, used for the legacy schema and prior workflow safeguards; not executed or modified.
- User follow-up after reviewing this plan: confirmed MacBook Pro deployment, existing Python/custom-code experience, and successful exact barcode-to-text capture on the currently connected device.
- [Tera D5100 product specifications](https://tera-digital.com/products/2d-barcode-scanner-d5100): connection modes and scanner features.
- [Google Sheets batch requests](https://developers.google.com/workspace/sheets/api/guides/batch): atomic application of batch subrequests.
- [Google Sheets value rendering](https://developers.google.com/workspace/sheets/api/reference/rest/v4/ValueRenderOption): reading calculated values versus formulas.
- [Google service-account key management](https://docs.cloud.google.com/iam/docs/best-practices-for-managing-service-account-keys): credentials must remain separate from source and distributed software. This is a locally administered prototype backend, not a key bundled into a client application for general distribution.

The plan-eng-review skill informed this discussion. Its startup helper and outside-review configuration command exited unsuccessfully without diagnostic output in this environment. The required read-only native fallback capabilities were not available in the prescribed form. No independent reviewer ran; no cross-model agreement, automated review-log completion, or full skill certification is claimed. This document is the saved project plan, not evidence that the software works.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | --- | --- | --- |
| Engineering plan | User invoked plan-eng-review | Specify local scanner-to-Sheets prototype | One discussion and consolidation | Plan documented | Architecture, quality, test strategy, performance, migration, and recovery reviewed; implementation untested |
| VERDICT | User accepted consolidated direction and corrected environment evidence | Record agreed build scope | One, amended with user verification | Ready for implementation preflight | MacBook/Python confirmed; basic scanner text capture user-verified; verify MacBook app input, credentials, live schema, and baseline before writes |
| OUTSIDE COVERAGE | Skill independent-review step | Challenge native review | Zero completed | Unavailable | Helper configuration command failed; prescribed native fallback unavailable |
| Review log / helper checks | Skill reporting requirements | Formal automated completion | Zero completed | Unavailable | No successful helper startup, saved helper log, or helper readback; not a certified completed skill run |

NO UNRESOLVED DECISIONS
