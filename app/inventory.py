import json
import re
import threading
from datetime import datetime, timezone
from uuid import UUID

from .sheets import DefinitiveRejection, Problem, text


def new_products(value):
    if not isinstance(value, list) or len(value) > 200:
        raise Problem("Invalid staged products.")
    result, upcs = {}, set()
    for p in value:
        if not isinstance(p, dict) or set(p) != {"id", "name", "unit", "upc"}:
            raise Problem("New products require ID, name, unit and scanned UPC.")
        for key in p:
            text(p[key], key)
        if not p["name"].strip() or not p["unit"].strip():
            raise Problem("New products need a nonblank name and catalog unit.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", p["id"]) or not re.fullmatch(r"[0-9]{8,14}", p["upc"]):
            raise Problem("New products require a valid ID and an 8–14 digit scanned barcode.")
        if p["id"] in result or p["upc"] in upcs:
            raise Problem("Duplicate staged ID or barcode.")
        result[p["id"]] = dict(p)
        upcs.add(p["upc"])
    return result


def payload_details(payload):
    kind, lines = stored_payload(payload)
    value = json.loads(payload)
    if isinstance(value.get("lines"), dict) and value.get("version") == 3:
        return kind, lines, value["new_products"], value["capture"]
    return kind, lines, {}, {p: "barcode" for p in lines}


def movement_type(value):
    if value not in ("withdrawal", "receiving"):
        raise Problem("Unsupported stock movement type.")
    return value


def stored_payload(payload):
    """Interpret historical maps without changing their durable representation."""
    value = json.loads(payload)
    if isinstance(value, dict) and value and all(type(q) is int and q > 0 for q in value.values()):
        return "withdrawal", value
    if not isinstance(value, dict) or not ((set(value) == {"version", "movement_type", "lines"} and value["version"] == 2) or (set(value) == {"version", "movement_type", "lines", "new_products", "capture"} and value["version"] == 3)):
        raise Problem("Invalid saved request payload. Reconciliation is required.", 409)
    kind = movement_type(value["movement_type"])
    if not isinstance(value["lines"], dict) or not value["lines"] or not all(type(q) is int and q > 0 for q in value["lines"].values()):
        raise Problem("Invalid saved request lines. Reconciliation is required.", 409)
    if value["version"] == 3:
        try:
            staged, capture = value["new_products"], value["capture"]
            if not isinstance(staged, dict) or new_products(list(staged.values())) != staged:
                raise Problem("Invalid staged evidence.")
            if not set(staged) <= set(value["lines"]) or (staged and kind != "receiving"):
                raise Problem("Invalid staged references.")
            if not isinstance(capture, dict) or set(capture) != set(value["lines"]) or any(not isinstance(v, str) or v not in {"barcode", "voice", "mixed"} for v in capture.values()):
                raise Problem("Invalid capture evidence.")
        except Problem:
            raise Problem("Invalid saved request metadata. Reconciliation is required.", 409) from None
    return kind, value["lines"]


def canonical(request, kind="withdrawal"):
    movement_type(kind)
    if not isinstance(request, dict) or not {"request_id", "lines"} <= set(request) or set(request) - {"request_id", "lines", "movement_type", "new_products", "capture"}:
        raise Problem("Submit a request identity and basket lines.")
    if "movement_type" in request and movement_type(request["movement_type"]) != kind:
        raise Problem("Stock movement type contradicts the submission route.")
    try:
        rid = str(UUID(request["request_id"]))
    except (ValueError, TypeError, AttributeError):
        raise Problem("Request identity must be a UUID.")
    lines = request["lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 200:
        raise Problem("Basket must contain between 1 and 200 products.")
    combined = {}
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"product_id", "quantity"}:
            raise Problem("Each basket line requires a product and quantity.")
        pid, qty = line["product_id"], line["quantity"]
        if not isinstance(pid, str) or not 1 <= len(pid) <= 100 or type(qty) is not int or not 1 <= qty <= 1000000:
            raise Problem("Quantities must be positive whole numbers up to 1,000,000.")
        combined[pid] = combined.get(pid, 0) + qty
        if combined[pid] > 1000000:
            raise Problem("Consolidated quantity is too large.")
    payload = dict(version=2, movement_type=kind, lines=combined)
    if "new_products" in request or "capture" in request:
        staged = new_products(request.get("new_products", []))
        capture = request.get("capture", {p: "barcode" for p in combined})
        if not isinstance(capture, dict) or set(capture) != set(combined) or any(not isinstance(v, str) or v not in {"barcode", "voice", "mixed"} for v in capture.values()):
            raise Problem("Capture labels must match basket products.")
        if not set(staged) <= set(combined) or (staged and kind != "receiving"):
            raise Problem("Only referenced receiving products may be created.")
        payload.update(version=3, new_products=staged, capture=capture)
    return rid, json.dumps(payload, sort_keys=True, separators=(",", ":")), combined


class Inventory:
    def __init__(self, sheets, journal, config):
        self.sheets, self.journal, self.config = sheets, journal, config
        self.lock = threading.RLock()

    def verify(self, record, snapshot):
        evidence = json.loads(record["evidence"])
        found = [r for r in snapshot.ledger if r[0] == record["id"]]
        expected = evidence["rows"]
        kind, _ = stored_payload(record["payload"])
        self.verify_catalog(evidence, snapshot)
        if sorted(found, key=lambda r: r[1]) != expected:
            self.journal.state(record["id"], "pending")
            raise Problem("Save outcome is unresolved. All stock movements are paused; check recovery. Do not submit under a new ID.", 409)
        if any(snapshot.products.get(pid, {}).get("count") != count for pid, count in evidence["after"].items()):
            self.journal.state(record["id"], "saved_unverified")
            raise Problem("Transaction rows are saved but balances could not be verified. Reconciliation is required.", 409)
        receipt = dict(request_id=record["id"], timestamp=expected[0][7], movement_type=kind,
                       total_units=sum(abs(r[6]) for r in expected),
                       lines=[dict(product_id=r[2], name=r[3], unit=r[4], quantity=abs(r[6]), remaining=evidence["after"][r[2]]) for r in expected])
        self.journal.state(record["id"], "verified", receipt)
        return receipt

    @staticmethod
    def verify_catalog(evidence, snapshot):
        for pid, expected in evidence.get("catalog", {}).items():
            actual = snapshot.products.get(pid, {})
            if any(actual.get(k) != v for k, v in expected.items()):
                raise Problem("Saved catalog evidence differs. Reconciliation is required.", 409)

    def recover(self):
        with self.lock:
            pending = self.journal.unresolved()
            for record in pending:
                try:
                    self.verify(record, self.sheets.read())
                except Exception:
                    # An unavailable provider, malformed ledger, or absent rows cannot prove failure.
                    if self.journal.get(record["id"])["state"] == "sending":
                        self.journal.state(record["id"], "pending")
            return self.pending()

    def pending(self):
        result = []
        for r in self.journal.unresolved():
            kind, lines, staged, capture = payload_details(r["payload"])
            pending = dict(request_id=r["id"], state=r["state"], movement_type=kind,
                           lines=[dict(product_id=p, quantity=q) for p, q in lines.items()])
            if isinstance(json.loads(r["payload"]).get("lines"), dict) and json.loads(r["payload"]).get("version") == 3:
                pending.update(new_products=list(staged.values()), capture=capture)
            result.append(pending)
        return result

    def status(self):
        with self.lock:
            snapshot = self.sheets.read()
            return dict(products=list(snapshot.products.values()), pending=self.pending(), recent=self.journal.recent())

    def submit(self, request, kind="withdrawal"):
        rid, payload, lines = canonical(request, kind)
        with self.lock:
            old = self.journal.get(rid)
            if old and payload_details(old["payload"]) != payload_details(payload):
                raise Problem("This request ID already belongs to a different basket.", 409)
            if old and old["state"] == "verified":
                # Recheck exact saved rows; later legitimate withdrawals may have changed stock.
                snapshot = self.sheets.read()
                try:
                    self.verify_catalog(json.loads(old["evidence"]), snapshot)
                except Problem:
                    self.journal.state(rid, "saved_unverified")
                    raise
                found = sorted([r for r in snapshot.ledger if r[0] == rid], key=lambda r: r[1])
                if found != json.loads(old["evidence"])["rows"]:
                    self.journal.state(rid, "saved_unverified")
                    raise Problem("Previously verified history changed. Reconciliation is required.", 409)
                return json.loads(old["receipt"])
            self.recover()
            if self.pending():
                raise Problem("A previous save is unresolved. All stock movements are paused until recovery is verified.", 409)
            old = self.journal.get(rid)
            if old and old["state"] == "verified":
                return json.loads(old["receipt"])
            snapshot = self.sheets.read()
            _, _, staged, capture = payload_details(payload)
            if any(pid in snapshot.products or any(p["upc"] == candidate["upc"] for p in snapshot.products.values()) for pid, candidate in staged.items()):
                raise Problem("A staged product ID or UPC now exists in the catalog. Refresh and review the basket.")
            products = {**snapshot.products, **{pid: dict(p, opening=0, count=0) for pid, p in staged.items()}}
            if any(r[0] == rid for r in snapshot.ledger):
                raise Problem("Request exists in Sheets without matching local evidence. Reconcile on the original device.", 409)
            for pid, qty in lines.items():
                if pid not in products:
                    raise Problem("A basket product no longer exists in the catalog. Refresh and review your basket.")
                p = products[pid]
                if kind == "withdrawal" and qty > p["count"]:
                    raise Problem(f"Not enough {p['name']}: requested {qty}, available {p['count']}. Nothing was recorded.")
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            rows, after = [], {}
            for n, (pid, qty) in enumerate(sorted(lines.items()), 1):
                p = products[pid]
                change = qty if kind == "receiving" else -qty
                rows.append([rid, n, pid, p["name"], p["unit"], p["upc"], change, timestamp,
                             self.config.device, capture[pid], kind, "", ""])
                after[pid] = p["count"] + change
            evidence = dict(rows=rows, after=after)
            if staged:
                evidence["catalog"] = {pid: dict(p, opening=0) for pid, p in staged.items()}
            # Prove capacity before recording a dispatch intent.
            self.sheets.check_capacity(snapshot, rows, staged)
            self.journal.intent(rid, payload, evidence)
            try:
                if staged:
                    self.sheets.write(snapshot, rows, staged)
                else:
                    self.sheets.write(snapshot, rows)
            except DefinitiveRejection as exc:
                self.journal.state(rid, "rejected")
                raise Problem(str(exc), 422) from None
            except Exception:
                self.journal.state(rid, "pending")
                raise Problem("Connection interrupted during saving. Basket is locked until recovery verifies the result.", 409) from None
            self.journal.state(rid, "saved_unverified")
            try:
                return self.verify(self.journal.get(rid), self.sheets.read())
            except Problem:
                raise
            except Exception:
                raise Problem("Write was accepted, but readback is unavailable. Use Check recovery; do not resubmit.", 409) from None
