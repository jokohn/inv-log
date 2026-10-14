# Inventory Flow

A local scanner-to-basket inventory prototype built from [the architecture plan](docs/architecture-plan.md). Python/FastAPI serves a buildless browser interface. Google Sheets holds live inventory; a local SQLite journal records request identities and recovery evidence.

**Current delivery: runnable demo plus Google integration code and migration tooling.** Demo mode is the default. No Google credentials, real inventory, or live spreadsheet were used or changed during development. See [verification evidence and remaining acceptance checks](docs/verification.md).

## Run on the MacBook

Use Python **3.12 or newer**. Python 3.12 was tested on the Windows development machine; installation and scanner behavior on the target MacBook still need verification. Open Terminal in this folder:

```sh
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m app
```

The app opens at **http://127.0.0.1:8765**. Keep its Terminal window running; press Control-C to stop. Subsequent launches:

```sh
sh start.command
```

Alternatively, `chmod +x start.command` once enables Finder double-click launch. The launcher uses the project's environment and works from any current directory. No Node installation or frontend build is needed. For Windows development use `.venv\Scripts\python.exe -m app` after creating the environment and installing dependencies.

## Try the demo

1. Click **Show demo barcodes**, then click a sample product, or type `000780000011` in Barcode and press Enter.
2. Scan the same barcode again to increase the quantity. Edit quantities directly or use the plus/minus buttons; remove a line with ×.
3. Select **Record withdrawal**. A receipt appears only after transaction rows and new balances have been read back and checked.
4. Refresh the page to test draft restoration. Request more units than available to test whole-basket rejection.

Sample barcodes and counts are synthetic demonstration data, not claims about real product UPCs or Hyatt stock. Demo data persists locally in `.state/demo/demo-workbook.json`. It uses the same catalog parser, atomic write builder, validation, and recovery workflow as Google mode through a simulated Google client. It does not prove actual Sheets API behavior.

## Scanner use

Connect the Tera D5100 by USB cable or its USB receiver and use manual-trigger, instant-upload mode with an **Enter suffix**. Click Barcode and verify **Ready to scan**. Do not enable continuous scanning or storage replay. The app preserves the complete text, including leading zeros and spaces; it does not infer pack sizes. The Enter event submits the field; no other terminators are stripped.

One scan means one catalog unit. The scanner beep confirms capture only. The receipt confirms an inventory update. Quantity controls keep normal keyboard behavior. Product counts shown while scanning are advisory and are reread on every submission.

## Connect Google Sheets

1. In your Google Cloud project, enable the Google Sheets API and create a service account. No broad project roles are needed. Your organization must permit service-account key creation.
2. Create/download its JSON key and store it **outside this project**, e.g. `~/.config/inv-flow/service-account.json`. On macOS restrict file permissions with `chmod 600`.
3. Share only the intended prototype Google Sheet with the service account's email as Editor. Keep this a single-writer pilot: no other laptop, script, or person may edit stock, history, mappings, or formulas during saving.
4. Edit `.env` with `INV_MODE=google`, the exact `INV_SPREADSHEET_ID`, absolute `INV_CREDENTIALS` file path, and `INV_DEVICE`. The supplied sheet ID comes from the architecture plan and has **not** been inspected in this build; confirm it is your intended prototype sheet.
5. Perform the explicit migration below. Normal startup never creates or alters schema. Legacy tabs are incompatible with the new schema until staging is completed.
6. Launch the app. A successful connection must show Google Sheets connected. Complete a deliberate test withdrawal on approved data and inspect the original Sheet's request rows and balances before using the prototype operationally.

Keys are read only by the local Python backend and never sent to the browser. `.env`, local state, and credential filename patterns are ignored by Git. Do not put secrets elsewhere in the source folder or distribute `.state` or `.venv` with the code.

## Migration: inspection first, explicit staging second

Stop the app and all old writers. Establish an exclusive maintenance window. The utility supports the exact legacy `Inventory`/`Transactions` headers documented in the architecture plan. It rejects malformed counts, numeric or duplicate UPCs, unexpected occupied columns, and malformed history. If existing numeric UPCs have lost zeros, repair from a reliable source; do not guess them.

Inspect and create a new backup file (the parent directory must exist):

```sh
mkdir -p .state/migrations
python -m scripts.migrate --backup .state/migrations/baseline.json
```

This is read-only to Google. It exports the full workbook with cell types/formulas, verifies the local backup, and prints a SHA-256 fingerprint. **Review every current count against an approved reconciled or physical baseline.** Historical records alone cannot establish opening inventory, so the utility cannot certify that reconciliation for you.

Only after reviewing the backup and confirming the baseline, stage using the printed fingerprint:

```sh
python -m scripts.migrate --backup .state/migrations/baseline.json \
  --stage --exclusive-maintenance --approved-baseline-sha256 PASTE_REVIEWED_HASH
```

Staging adds `Inventory_v1`, `Transactions_v1`, and `InvFlow_v1` atomically and verifies every new balance. It leaves original tabs intact. Current reconciled balances become Opening Counts; the old history stays exclusively in the original tabs and is **not replayed**. Stable IDs are generated once, UPCs remain strings, and balances use bounded formulas. New tabs have warning protections against casual edits; these are not access restrictions. For stricter protection, restrict editors manually while retaining service-account access.

The staging utility records dispatch intent beside the backup and refuses to overwrite that marker or existing target tabs. If staging times out, inspect Google for all three staging tabs and compare every balance before any further action. Do not remove the marker and blindly retry. No automatic migration recovery is claimed.

Document the cutover time, backup fingerprint, and product-ID mapping from the staged catalog. Configure the new tabs only after verification and discontinue the legacy Markdown write workflow. Before new transactions exist, retain the original tabs for rollback. After new activity, reconcile it before changing configuration; never discard new history.

## Recovery and corrections

Every submission has a stable UUID saved in the browser before sending and in SQLite before network dispatch. A retry with the same ID and payload cannot append a second copy. A different payload with the same ID is rejected. Every fresh intentional withdrawal receives a new ID.

An interrupted write locks the basket and pauses all new withdrawals. Select **Check recovery**. If exact rows and expected balances exist, the app returns a verified receipt. If the original HTTP request never reached the journal, the browser may resend exactly the same identity and payload. Once a dispatch is journaled, absent rows do **not** authorize a resend. The app never automatically clears uncertain journal records.

For unresolved/partial/mismatched results, stop capture and reconcile the original Sheet and local journal on the original device. Keep the journal and evidence. Do not switch state directories, reset IDs, delete rows, or move to another laptop to get around the pause. This release deliberately has no "force retry" or "mark failed" button; ambiguous absence requires a reviewed reconciliation procedure.

Corrections are append-only controlled `adjustment` rows: unique Request ID, contiguous Line Number beginning at 1, valid Product ID and snapshot unit, signed nonzero integer Unit Change, explicit UTC timestamp, device label, `manual` Capture Method, `adjustment` Transaction Type, and a required Note. Optional Related Request ID links the original withdrawal. No receiving or adjustment UI is included. Perform manual adjustments only while the app is stopped and no submission is unresolved; verify balances before reopening.

## Schema and limits

- `Inventory_v1`: Product ID, Product Name, Unit Size, UPC, Opening Count, Current Count.
- `Transactions_v1`: Request ID, Line Number, Product ID, Product Name, Unit Size, UPC, Unit Change, Change Datetime, Changing Device, Capture Method, Transaction Type, Note, Related Request ID.
- `InvFlow_v1`: key/value metadata including `schema_version` = text `1` and `counting_model` = `whole_catalog_units`.
- Formula coverage starts at 1,000 ledger rows and expands by 1,000 rows in the same atomic batch as the withdrawal. Hard limit: 100,000 transaction rows and 200 products per basket. Every populated ledger row is read; blank gaps do not terminate history.
- Unit Size is a literal catalog counting unit, not a conversion rule. Fractional quantities, cases-to-bottles conversion, and unit changes to products with history are unsupported.
- The launcher binds only to loopback, runs one worker, locks its state directory, validates Host/Origin, and requires a session token on mutations. No LAN or cloud hosting.
- Different computers/state directories bypass the lock. Google batch atomicity does not make the preceding read/check/write transactional against outside editors.
- No BirchStreet connection, staff authentication, offline saving, automatic receipts export, or stock receiving screen.

## Development and verification

```sh
python -m pytest -q
```

Tests inject failures at the Google client boundary and exercise real application parsing, writing, and recovery. Pinned dependencies include test tooling. No CI or installer packaging is included. Backend tests were run on Windows/Python 3.12; see the evidence file for browser checks and unverified live acceptance requirements.

Google references: [atomic batch updates](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate), [typed cell update requests](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request#UpdateCellsRequest).
