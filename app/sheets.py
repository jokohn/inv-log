"""Typed, bounded Google Sheets reads and a single atomic, non-retried write."""
from dataclasses import dataclass
from datetime import datetime
import re
import math

INVENTORY = ["Product ID", "Product Name", "Unit Size", "UPC", "Opening Count", "Current Count"]
TRANSACTIONS = ["Request ID", "Line Number", "Product ID", "Product Name", "Unit Size", "UPC",
                "Unit Change", "Change Datetime", "Changing Device", "Capture Method",
                "Transaction Type", "Note", "Related Request ID"]
MAX_ROWS = 100001


class Problem(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


class DefinitiveRejection(Exception):
    pass


def connection_error(exc):
    """Actionable status text without exposing raw provider responses or tokens."""
    if isinstance(exc, Problem):
        return str(exc)
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 403:
        import json
        try:
            error = json.loads(exc.content).get("error", {})
            disabled = any(d.get("reason") == "SERVICE_DISABLED" for d in error.get("details", [])) or any(
                d.get("reason") == "accessNotConfigured" for d in error.get("errors", []))
        except (ValueError, TypeError, AttributeError):
            disabled = False
        if disabled:
            return "Google Sheets API is disabled for the credential's project. Enable it in Google Cloud, then Refresh."
        return "Google denied access to this spreadsheet (403). Confirm INV_SPREADSHEET_ID and share that exact Google Sheet with the service account's client_email as Editor, then Refresh. Organization sharing restrictions may require your administrator."
    if status == 404:
        return "Google could not find or access the configured spreadsheet (404). Check INV_SPREADSHEET_ID and service-account sharing."
    if status == 401:
        return "Google rejected authentication (401). Check the service-account key and restart the app."
    if status == 429:
        return "Google's request limit was reached. Wait briefly, then Refresh."
    return "Could not read the workbook. Check the network and credentials, or run python -m scripts.check_connection for a read-only diagnosis."


def quote(tab):
    return "'" + tab.replace("'", "''") + "'"


def formula(row, capacity, transactions_tab):
    tab = quote(transactions_tab)
    return f"=E{row}+SUMIF({tab}!$C$2:$C${capacity},A{row},{tab}!$G$2:$G${capacity})"


def formula_matches(actual, row, capacity, transactions_tab):
    expected = formula(row, capacity, transactions_tab)
    allowed = {expected}
    # Sheets canonicalizes simple sheet names by removing optional quotes.
    # Accept only this exact equivalent, not arbitrary rewritten expressions.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", transactions_tab):
        allowed.add(expected.replace(quote(transactions_tab) + "!", transactions_tab + "!"))
    return actual in allowed


def cell(value):
    return {"userEnteredValue": {"numberValue" if type(value) in (int, float) else "stringValue": value}}


def typed_rows(rows):
    return [{"values": [cell(v) for v in row]} for row in rows]


def integer(value, label, minimum=None):
    if type(value) not in (int, float) or not math.isfinite(value) or int(value) != value or (minimum is not None and value < minimum):
        raise Problem(f"{label} must be a whole number" + (f" of at least {minimum}." if minimum is not None else "."))
    return int(value)


def text(value, label):
    if not isinstance(value, str) or not value or len(value) > 500 or any(ord(c) < 32 for c in value):
        raise Problem(f"{label} must be nonempty text without control characters.")
    return value


@dataclass
class Snapshot:
    products: dict
    ledger: list
    inventory_id: int
    transactions_id: int
    capacity: int
    next_row: int


class Sheets:
    def __init__(self, service, config):
        self.api = service.spreadsheets()
        self.config = config

    def read(self):
        cfg = self.config
        props = self.api.get(spreadsheetId=cfg.spreadsheet_id,
                             fields="sheets.properties").execute(num_retries=2)
        by_title = {s["properties"]["title"]: s["properties"] for s in props["sheets"]}
        names = [cfg.inventory_tab, cfg.transactions_tab, cfg.metadata_tab]
        if len(set(names)) != 3 or any(t not in by_title for t in names):
            raise Problem("Workbook is not configured for schema v1. Run the separate migration preflight.", 503)
        if any(by_title[t]["gridProperties"]["rowCount"] > MAX_ROWS for t in names):
            raise Problem("Workbook exceeds the prototype's 100,000-row capacity; archive through a controlled migration.", 503)
        ranges = [f"{quote(t)}!A1:{end}{by_title[t]['gridProperties']['rowCount']}"
                  for t, end in zip(names, ["F", "M", "B"])]
        data = self.api.get(spreadsheetId=cfg.spreadsheet_id, ranges=ranges,
                            includeGridData=True).execute(num_retries=2)
        grids = {s["properties"]["title"]: s.get("data", [{}])[0].get("rowData", []) for s in data["sheets"]}
        def values(row, width):
            result = []
            for c in row.get("values", [])[:width]:
                v = c.get("effectiveValue", c.get("userEnteredValue", {}))
                if "errorValue" in v:
                    raise Problem("Spreadsheet formula error. Repair the workbook before saving.", 503)
                result.append(next(iter(v.values()), ""))
            return result + [""] * (width - len(result))
        inv, ledger, meta = (grids[t] for t in names)
        if not inv or values(inv[0], 6) != INVENTORY or not ledger or values(ledger[0], 13) != TRANSACTIONS:
            raise Problem("Workbook headers differ from schema v1. No data was changed.", 503)
        metadata = dict(values(r, 2) for r in meta if any(values(r, 2)))
        if metadata.get("schema_version") != "1":
            raise Problem("Missing or incompatible schema_version metadata.", 503)
        capacity = by_title[cfg.transactions_tab]["gridProperties"]["rowCount"]
        products, upcs = {}, set()
        for row_number, row in enumerate(inv[1:], 2):
            vals = values(row, 6)
            if not any(v != "" for v in vals):
                continue
            pid, name, unit, upc, opening, current = vals
            entered = row.get("values", [])
            if any("stringValue" not in c.get("userEnteredValue", {}) for c in entered[:4]) or "numberValue" not in entered[4].get("userEnteredValue", {}):
                raise Problem("Catalog identity fields must be literal text and opening counts must be literal numbers.", 503)
            for value, label in [(pid, "Product ID"), (name, "Product name"), (unit, "Unit size"), (upc, "UPC")]:
                text(value, label)
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", pid):
                raise Problem("Product IDs must use letters, numbers, underscores, or hyphens.")
            if pid in products or upc in upcs:
                raise Problem("Duplicate product ID or barcode. Repair the catalog before scanning.", 503)
            if metadata.get("counting_model") != "whole_catalog_units":
                raise Problem("Unsupported counting model; schema v1 requires whole catalog units.", 503)
            opening, current = integer(opening, "Opening count", 0), integer(current, "Current count", 0)
            actual_formula = row.get("values", [{}] * 6)[5].get("userEnteredValue", {}).get("formulaValue")
            if not formula_matches(actual_formula, row_number, capacity, cfg.transactions_tab):
                raise Problem(f"Balance formula for {name} is missing or has incorrect coverage.", 503)
            products[pid] = dict(id=pid, name=name, unit=unit, upc=upc, opening=opening, count=current, row=row_number)
            upcs.add(upc)
        if not products:
            raise Problem("Catalog has no products.", 503)
        records, identities, totals = [], set(), {pid: p["opening"] for pid, p in products.items()}
        request_products, request_numbers = {}, {}
        last_row = 1
        for row_number, row in enumerate(ledger[1:], 2):
            v = values(row, 13)
            if not any(x != "" for x in v):
                continue
            last_row = row_number
            if any("formulaValue" in c.get("userEnteredValue", {}) for c in row.get("values", [])):
                raise Problem("Transaction history must contain literal values, not formulas.", 503)
            rid, line, pid, name, unit, upc, change, stamp, device, method, kind, note, related = v
            text(rid, "Request ID")
            line = integer(line, "Line number", 1)
            if (rid, line) in identities or pid not in products:
                raise Problem("Duplicate transaction identity or missing catalog product.", 503)
            if pid in request_products.setdefault(rid, set()):
                raise Problem("A request contains duplicate product lines.", 503)
            request_products[rid].add(pid)
            request_numbers.setdefault(rid, []).append(line)
            for value, label in [(name, "Snapshot name"), (upc, "Snapshot UPC"), (device, "Device")]:
                text(value, label)
            if unit != products[pid]["unit"]:
                raise Problem("Historical counting unit differs from the catalog.", 503)
            change = integer(change, "Unit change")
            if kind not in {"withdrawal", "adjustment"} or change == 0:
                raise Problem("Invalid transaction type or zero unit change.", 503)
            if kind == "withdrawal" and (change >= 0 or method != "barcode"):
                raise Problem("Withdrawal ledger line is invalid.", 503)
            if kind == "adjustment" and (not note or method != "manual"):
                raise Problem("Adjustments require a reason and manual capture method.", 503)
            try:
                dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
                    raise ValueError()
            except (ValueError, AttributeError):
                raise Problem("Transaction timestamps must be explicit UTC.", 503)
            identities.add((rid, line))
            totals[pid] += change
            records.append(v)
        if any(sorted(numbers) != list(range(1, len(numbers) + 1)) for numbers in request_numbers.values()):
            raise Problem("A request has missing or invalid line numbers.", 503)
        for pid, product in products.items():
            if product["count"] != totals[pid]:
                raise Problem(f"Calculated balance disagrees with ledger for {product['name']}.", 503)
        return Snapshot(products, records, by_title[cfg.inventory_tab]["sheetId"],
                        by_title[cfg.transactions_tab]["sheetId"], capacity, last_row)

    def write(self, snapshot, rows):
        end = snapshot.next_row + len(rows)
        if end > MAX_ROWS:
            raise DefinitiveRejection("Transaction capacity reached. Reconcile and migrate before continuing.")
        requests = []
        if end > snapshot.capacity:
            capacity = min(MAX_ROWS, max(end, snapshot.capacity + 1000))
            requests.append({"appendDimension": {"sheetId": snapshot.transactions_id, "dimension": "ROWS",
                                                    "length": capacity - snapshot.capacity}})
            for p in snapshot.products.values():
                requests.append({"updateCells": {"start": {"sheetId": snapshot.inventory_id,
                    "rowIndex": p["row"] - 1, "columnIndex": 5}, "rows": [{"values": [{"userEnteredValue": {
                    "formulaValue": formula(p["row"], capacity, self.config.transactions_tab)}}]}], "fields": "userEnteredValue"}})
        requests.append({"updateCells": {"start": {"sheetId": snapshot.transactions_id,
            "rowIndex": snapshot.next_row, "columnIndex": 0}, "rows": typed_rows(rows), "fields": "userEnteredValue"}})
        try:
            self.api.batchUpdate(spreadsheetId=self.config.spreadsheet_id,
                                 body={"requests": requests}).execute(num_retries=0)
        except Exception as exc:
            # Only explicit provider rejection proves that dispatch did not commit.
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in {400, 401, 403, 404, 413, 422}:
                raise DefinitiveRejection("Google rejected the write. Check access/schema, then retry the retained basket.") from None
            raise


def load_service_account_credentials(filename):
    """Validate credential kind locally without printing credential values."""
    import json
    from pathlib import Path
    from google.oauth2.service_account import Credentials
    try:
        info = json.loads(Path(filename).expanduser().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise Problem("INV_CREDENTIALS must point to a readable service-account JSON key file. See README: Connect Google Sheets.", 503) from None
    if isinstance(info, dict) and ("installed" in info or "web" in info):
        raise Problem("INV_CREDENTIALS points to an OAuth client configuration. This app requires a service-account JSON key: Google Cloud > IAM & Admin > Service Accounts > select account > Keys > Add key > Create new key > JSON. Update INV_CREDENTIALS to that downloaded file; do not edit the OAuth file to add missing fields.", 503)
    if not isinstance(info, dict) or info.get("type") != "service_account" or not all(
        isinstance(info.get(key), str) and info[key] for key in ("client_email", "token_uri", "private_key")
    ):
        raise Problem("INV_CREDENTIALS is not a complete service-account JSON key. Download the JSON key from the service account's Keys tab. An API key or OAuth client file cannot be used here.", 503)
    try:
        return Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    except (ValueError, TypeError):
        raise Problem("The service-account key could not be loaded. Use the original downloaded JSON file, without modifying its contents.", 503) from None


def google_service(config):
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    credentials = load_service_account_credentials(config.credentials)
    # Authentication retries must not silently replay a mutation.
    transport = AuthorizedHttp(credentials, http=httplib2.Http(timeout=20), max_refresh_attempts=0)
    return build("sheets", "v4", http=transport, cache_discovery=False, static_discovery=True)
