"""Explicit live semantic rehearsal. Fixed demo catalog, no inventory writes, $5 task cap."""
import argparse
import asyncio
import json
from pathlib import Path

from filelock import FileLock

from app.capture import CaptureAssistance, INSTRUCTIONS, SCHEMA, MAX_OUTPUT_TOKENS
from app.config import Config
from app.demo import DemoService
from app.sheets import Problem, Sheets

# Rates verified against official model documentation on 2026-10-25.
INPUT_PER_MILLION, OUTPUT_PER_MILLION = 2, 10
CAP = 5.0
SPEND_PATH = Path(".state/pre-demo-voice-rehearsal.json")


def edit(op, pid, qty):
    return dict(action=op, product_id=pid, quantity=qty)


CASES = [
    ("Withdraw two Sapporo and three Tepache.", {}, [edit("add", "sapporo", 2), edit("add", "tepache", 3)], None),
    ("Add three more Sapporo.", {"sapporo":2}, [edit("add", "sapporo", 3)], None),
    ("Change Sapporo to three.", {"sapporo":2}, [edit("set", "sapporo", 3)], None),
    ("Remove the Tepache.", {"sapporo":2,"tepache":3}, [edit("remove", "tepache", 0)], None),
    ("Cancel this draft.", {"sapporo":2}, [edit("cancel", "", 0)], None),
    ("Withdraw two Sapporo and one sparkling water.", {}, [edit("add", "sapporo", 2), edit("add", "perrier", 1)], None),
    ("Withdraw two vodka.", {}, None, None),
    ("Withdraw two Sapporo and one drink.", {}, None, None),
    ("Withdraw two Sapporo and one drink.", {}, [edit("add", "sapporo", 2), edit("add", "tepache", 1)], {"question":"Which drink?", "answer":"Tepache"}),
    ("Receive two Sapporo.", {}, "unsupported", None),
    ("Withdraw half a Sapporo.", {}, "unsupported", None),
]


async def rehearse(cfg):
    if not cfg.openai_api_key:
        raise Problem("Set INV_OPENAI_API_KEY locally before live rehearsal. Do not paste it into chat.")
    if cfg.voice_model != "gpt-6.1-sol":
        raise Problem("Rehearsal cost bounds apply only to the approved gpt-6.1-sol model.")
    # Always use fixed in-memory demo data, regardless of the app's configured workbook.
    demo_cfg = Config()
    catalog = Sheets(DemoService(demo_cfg), demo_cfg).read().products
    capture = CaptureAssistance(cfg)
    SPEND_PATH.parent.mkdir(exist_ok=True)
    with FileLock(str(SPEND_PATH) + ".lock", timeout=0):
        ledger = json.loads(SPEND_PATH.read_text()) if SPEND_PATH.exists() else dict(reserved_usd=0, actual_reported_usd=0, attempts=[])
        for index, (transcript, basket, expected, clarification) in enumerate(CASES, 1):
            body = dict(transcript=transcript, movement_type="withdrawal", lines=[dict(product_id=p,quantity=q) for p,q in basket.items()])
            if clarification: body["clarification"] = clarification
            context_bytes = len(json.dumps(dict(body, catalog=list(catalog.values())), ensure_ascii=False).encode())
            # Byte count bounds input tokens; overhead deliberately exceeds schema/envelope size.
            reserve = ((context_bytes + len(INSTRUCTIONS.encode()) + len(json.dumps(SCHEMA)) + 10000) * INPUT_PER_MILLION + MAX_OUTPUT_TOKENS * OUTPUT_PER_MILLION) / 1000000
            if ledger["reserved_usd"] + reserve > CAP:
                print("STOP: cumulative task reservation would exceed $5. No call sent.")
                return False
            ledger["reserved_usd"] += reserve
            attempt = dict(case=index, reserved_usd=reserve, status="dispatching")
            ledger["attempts"].append(attempt)
            SPEND_PATH.write_text(json.dumps(ledger, indent=2))  # reserve durably before dispatch, even on crash
            passed = False
            try:
                value = await capture.interpret(body, catalog)
                usage = value.get("usage", {})
                actual = (usage.get("input_tokens", 0) * INPUT_PER_MILLION + usage.get("output_tokens", 0) * OUTPUT_PER_MILLION) / 1000000
                ledger["actual_reported_usd"] += actual
                attempt.update(usage=usage, actual_usd=actual)
                if expected is None:
                    passed = value["status"] in {"clarify", "unsupported"}
                elif expected == "unsupported":
                    passed = value["status"] in {"unsupported", "clarify"} and not value["actions"]
                else:
                    key = lambda a: (a["product_id"], a["action"], a["quantity"])
                    passed = value["status"] == "ready" and sorted(value["actions"], key=key) == sorted(expected, key=key)
                attempt.update(status="pass" if passed else "fail", result=value)
            except Problem as exc:
                attempt.update(status="error", error=str(exc))
            SPEND_PATH.write_text(json.dumps(ledger, indent=2))
            print(f"Case {index}: {attempt['status']}; reported ${ledger['actual_reported_usd']:.4f}, reserved ${ledger['reserved_usd']:.4f} / $5")
            if not passed:
                print("STOP: resolve the failed case before rerunning. Reservations persist across runs.")
                return False
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send paid requests within the cumulative $5 cap")
    args = parser.parse_args()
    if not args.live:
        print(f"Dry run: {len(CASES)} fixed demo cases; zero requests, $0 spent. Use --live only after local API setup.")
    else:
        try:
            raise SystemExit(0 if asyncio.run(rehearse(Config.load())) else 1)
        except Problem as exc:
            parser.exit(1, str(exc) + "\n")
