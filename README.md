# Inventory Flow

A local scanner-to-basket inventory prototype built from [the architecture plan](docs/architecture-plan.md). Python/FastAPI serves a buildless browser interface. Google Sheets holds live inventory; a local SQLite journal records request identities and recovery evidence.

**Current delivery: runnable demo plus Google integration code and migration tooling.** Demo mode is the default. No Google credentials, real inventory, or live spreadsheet were used or changed during development. See [verification evidence and remaining acceptance checks](docs/verification.md).

**Receiving implemented:** [Inventory receiving implementation plan](docs/receiving-implementation-plan.md) records the supplier-delivery scope and acceptance requirements. Receiving shares the withdrawal save and recovery path. Automated and isolated browser checks are recorded in [verification evidence](docs/verification.md); live receiving and physical-scanner acceptance remain outstanding.

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

1. Choose **Withdraw stock** or **Receive stock** with an empty basket. Click **Show demo barcodes**, then click a sample product, or type `000780000011` in Barcode and press Enter.
2. Scan the same barcode again to increase the quantity. Edit quantities directly or use the plus/minus buttons; remove a line with ×.
3. Select **Record withdrawal** or **Receive stock**. A receipt appears only after transaction rows and new balances have been read back and checked.
4. Refresh the page to test draft restoration. Request more units than available to test whole-basket rejection.

Sample barcodes and counts are synthetic demonstration data, not claims about real product UPCs or Hyatt stock. Demo data persists locally in `.state/demo/demo-workbook.json`. It uses the same catalog parser, atomic write builder, validation, and recovery workflow as Google mode through a simulated Google client. It does not prove actual Sheets API behavior.

## Receive a supplier delivery

Choose **Receive stock** before scanning. Existing catalog products only: each exact barcode scan adds one catalog unit to a single consolidated basket line. Scan repeatedly, use plus/minus, or enter a quantity directly; these methods can be combined. The counting unit appears beside each product. Two cases of 24 bottles require **48 bottles**; there is no case conversion or supplier/reference field.

Select **Receive stock** to submit. Receiving adds stock, including when current stock is zero or the delivery exceeds stock on hand. Withdrawals still reject insufficient stock for the entire basket. Confirmation and recent activity show **+** for receiving and **−** for withdrawals, with the resulting stock in the receipt.

Switch modes only with an empty basket and no save or recovery lock. Reload restores the draft's direction. An interrupted save locks both modes until **Check recovery** verifies its exact rows and balances. A scanner beep means capture, not a verified stock change. Never create another request to bypass an unresolved save.

### Upgrade an existing installation

Resolve uncertain submissions and stop the old app before upgrading. Keep its local journal and browser drafts; older records without a movement type are interpreted as withdrawals without rewriting their history. No spreadsheet migration, new column, opening-count reset, or replay is needed for receiving on an existing v1 workbook.

**Older application versions reject receiving rows.** After the first receipt is recorded, do not run an older build against that ledger. Preserve all history and use documented manual adjustments for corrections. Keep one writer active.

If an environment was reused across Python versions and imports fail, recreate the virtual environment for the chosen interpreter and install the pinned requirements. Compiled dependency files from Python 3.12 cannot be reused by Python 3.14.

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

### Wrong credential file: missing client_email / token_uri

This app requires a **service-account JSON key**, not an API key or an OAuth client configuration (those often have an `installed` or `web` object). Do not add the missing fields manually.

In Google Cloud Console, open **IAM & Admin → Service Accounts → your service account → Keys → Add key → Create new key → JSON**. Store the downloaded file outside the project. Share the target spreadsheet with that service account's email as Editor. See [Google's key creation instructions](https://docs.cloud.google.com/iam/docs/keys-create-delete).

On this Windows device, set the path in `.env` using forward slashes, for example:

```dotenv
INV_CREDENTIALS=C:/Users/jkohn/.config/inv-flow/service-account.json
```

Use the actual location where you saved the downloaded key, then restart `python -m app`. Credential loading happens before any Google request; this particular error does not indicate a Sheets sharing or API-enablement problem. Connection and schema checks still follow successful credential loading.

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

### Recover the initial staging formula error

The initial migration implementation wrote formulas before creating the transaction tab they referenced. Google could save those formulas with `#N/A: Argument must be a range`. The fixed migration creates all target tabs before writing any formulas, and balance validation accepts Google's removal of optional quotes around simple tab names.

If staging already created the tabs, **do not rerun `--stage` or delete the intent marker**. Stop the app and all other editors. The narrowly scoped repair below checks the verified backup, migration provenance, unchanged original tabs, exact staged product data/opening counts, empty new ledger, and absence of withdrawal activity in the journal:

```sh
python -m scripts.repair_migration --backup .state/migrations/baseline.json
python -m scripts.repair_migration --backup .state/migrations/baseline.json --apply
```

The first command is read-only to Google. The second rewrites only the original staged balance formulas, saves local repair evidence, and reads back every balance against the approved baseline. It refuses changed data or any existing withdrawal activity. It is not a general-purpose repair for transaction recovery.

Document the cutover time, backup fingerprint, and product-ID mapping from the staged catalog. Configure the new tabs only after verification and discontinue the legacy Markdown write workflow. Before new transactions exist, retain the original tabs for rollback. After new activity, reconcile it before changing configuration; never discard new history.

## Recovery and corrections

Every submission has a stable UUID saved in the browser before sending and in SQLite before network dispatch. A retry with the same ID and payload cannot append a second copy. A different payload with the same ID is rejected. Every fresh intentional withdrawal or delivery receives a new ID. Direction is part of that identity.

An interrupted write locks the basket and pauses both receiving and withdrawals. Select **Check recovery**. If exact rows and expected balances exist, the app returns a verified receipt. If the original HTTP request never reached the journal, the browser may resend exactly the same identity and payload. Once a dispatch is journaled, absent rows do **not** authorize a resend. The app never automatically clears uncertain journal records.

For unresolved/partial/mismatched results, stop capture and reconcile the original Sheet and local journal on the original device. Keep the journal and evidence. Do not switch state directories, reset IDs, delete rows, or move to another laptop to get around the pause. This release deliberately has no "force retry" or "mark failed" button; ambiguous absence requires a reviewed reconciliation procedure.

Corrections are append-only controlled `adjustment` rows: unique Request ID, contiguous Line Number beginning at 1, valid Product ID and snapshot unit, signed nonzero integer Unit Change, explicit UTC timestamp, device label, `manual` Capture Method, `adjustment` Transaction Type, and a required Note. Optional Related Request ID links the original stock movement. No adjustment UI is included. Perform manual adjustments only while the app is stopped and no submission is unresolved; verify balances before reopening.

## Schema and limits

- `Inventory_v1`: Product ID, Product Name, Unit Size, UPC, Opening Count, Current Count.
- `Transactions_v1`: Request ID, Line Number, Product ID, Product Name, Unit Size, UPC, Unit Change, Change Datetime, Changing Device, Capture Method, Transaction Type, Note, Related Request ID.
- `InvFlow_v1`: key/value metadata including `schema_version` = text `1` and `counting_model` = `whole_catalog_units`.
- Formula coverage starts at 1,000 ledger rows and expands by 1,000 rows in the same atomic batch as the stock movement. Hard limit: 100,000 transaction rows and 200 products per basket. Every populated ledger row is read; blank gaps do not terminate history.
- Unit Size is a literal catalog counting unit, not a conversion rule. Fractional quantities, cases-to-bottles conversion, and unit changes to products with history are unsupported.
- The launcher binds only to loopback, runs one worker, locks its state directory, validates Host/Origin, and requires a session token on mutations. No LAN or cloud hosting.
- Different computers/state directories bypass the lock. Google batch atomicity does not make the preceding read/check/write transactional against outside editors.
- No BirchStreet connection, staff authentication, offline saving, automatic receipts export.

## Development and verification

```sh
python -m pytest -q
```

Tests inject failures at the Google client boundary and exercise real application parsing, writing, and recovery. Pinned dependencies include test tooling. No CI or installer packaging is included. Backend tests were most recently run on Windows/Python 3.14; see the evidence file for browser checks and unverified live acceptance requirements.

Google references: [atomic batch updates](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate), [typed cell update requests](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request#UpdateCellsRequest).
## Pre-demo capture additions (October 25, 2026)

Receiving now supports unfamiliar scanned barcodes. Scan in **Receive stock**: UPCitemdb Explorer can fill editable product name/unit fields. No match, missing data, quota or a five-second lookup timeout leaves a manual draft. Complete both fields, review the catalog counting unit and quantity, then submit. Repeat scans increment the same staged line. Unknown withdrawals still reject. New inventory rows start with zero opening count; the receiving transaction supplies their quantity once. New catalog rows, balance formulas and transaction rows share one atomic batch and the existing verification/recovery journal.

The **Voice command** card uses the browser's speech recognition and server-side OpenAI interpretation. Start recording, speak, and finish recording. Supported commands add/increment, set quantities, remove a line or cancel the draft. Clarification holds the entire command until answered or discarded. Basket edits remain available while interpretation runs; an intervening edit discards its response. Submit waits for recording, interpretation and clarification to end and requires a fresh click. Refresh retains the basket and staged products and discards unfinished voice work with a notice. Voice never saves stock.

To enable voice, create/select an OpenAI API project, enable its API billing if needed, and create a project API key yourself. Add it **only to the local server's ignored `.env`**:

```dotenv
INV_OPENAI_API_KEY=your-project-key
INV_VOICE_MODEL=gpt-6.1-sol
```

Restart the app. Do not paste the key into chat or commit it. ChatGPT subscription access does not establish API project access. Without a key or supported browser, the microphone explains its unavailability and barcode/manual capture stays usable. Browser recognition may use its browser vendor's online speech service; verify permissions and recognition on the demo laptop. Unknown barcode lookup sends only that barcode to UPCitemdb. Interpretation sends the completed text, selected direction, draft context and complete compact catalog to OpenAI; credentials stay on the server. No provider image/link URLs are fetched. Calls are bounded, are never automatically retried, and do not hold the inventory writer lock. Interpretation times out after 30 seconds. Oversized full context disables voice rather than truncating the catalog.

For setup and rehearsal, see [the pre-demo runbook](docs/pre-demo-runbook.md). The offline suite and browser fixtures establish implementation behavior, not live provider quality or target-device acceptance. User requested offline verification for this run; no live model calls or billing occurred.

**Compatibility:** historical map/v2 payloads and immutable saved receipts remain supported. New payloads include staged metadata and per-product barcode/voice/mixed capture labels in request identity. Updated readers accept those ledger labels. An old binary rejects voice/mixed history; do not use it as a transparent rollback. Keep the original state directory with its workbook, and never clear unresolved journal entries to retry a save.
