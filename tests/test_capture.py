import asyncio
import json
import re
import gzip

import httpx
import pytest

from app.capture import CaptureAssistance, validate_result, MAX_CONTEXT_BYTES
from app.config import Config
from app.demo import DemoService
from app.sheets import Problem, Sheets
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def catalog():
    cfg = Config()
    return Sheets(DemoService(cfg), cfg).read().products


def run(awaitable):
    return asyncio.run(awaitable)


def result(actions=None, **kw):
    return dict(status="ready", movement_type="withdrawal", actions=actions or [], question="", candidate_ids=[], **kw)


def action(op="add", pid="sapporo", qty=2):
    return dict(action=op, product_id=pid, quantity=qty)


def test_lookup_known_and_unknown_withdrawal_never_call(catalog):
    def forbidden(req):
        pytest.fail("Lookup should not dispatch")
    capture = CaptureAssistance(Config(), httpx.MockTransport(forbidden))
    assert run(capture.lookup(dict(upc="000780000011", movement_type="withdrawal"), catalog))["status"] == "known"
    with pytest.raises(Problem, match="Unknown withdrawal"):
        run(capture.lookup(dict(upc="001234567890", movement_type="withdrawal"), catalog))


@pytest.mark.parametrize("variant,expected", [("complete", "complete"), ("partial", "manual"), ("none", "manual"), ("multiple", "manual"), ("mismatch", "manual"), ("quota", "manual"), ("timeout", "manual"), ("malformed", "manual"), ("oversized", "manual"), ("hostile", "complete")])
def test_lookup_fallbacks_preserve_barcode_and_partial_fields(catalog, variant, expected):
    calls = []
    def provider(req):
        calls.append(req)
        assert str(req.url).startswith("https://api.upcitemdb.com/prod/trial/lookup")
        if variant == "timeout": raise httpx.ReadTimeout("test")
        if variant == "quota": return httpx.Response(429)
        if variant == "malformed": return httpx.Response(200, content=b"invalid")
        if variant == "oversized": return httpx.Response(200, content=b"x" * 128001)
        item = dict(upc="001234567890", title='=IMPORTDATA("bad")' if variant == "hostile" else "Test drink", size="12 oz bottle")
        if variant == "partial": item.pop("size")
        if variant == "mismatch": item["upc"] = "999999999999"
        items = [] if variant == "none" else [item, item] if variant == "multiple" else [item]
        return httpx.Response(200, json=dict(code="OK", items=items))
    capture = CaptureAssistance(Config(), httpx.MockTransport(provider))
    value = run(capture.lookup(dict(upc="001234567890", movement_type="receiving"), catalog))
    assert value["status"] == expected and value["upc"] == "001234567890"
    assert len(calls) == 1
    if variant == "partial": assert value["name"] == "Test drink" and value["unit"] == ""


@pytest.mark.parametrize("actions", [[action(), action(pid="tepache")], [action("set", qty=3)], [action("remove", qty=0)], [action("cancel", "", 0)]])
def test_valid_semantics(catalog, actions):
    assert validate_result(result(actions), "withdrawal", catalog, {"sapporo":1})["actions"] == actions


@pytest.mark.parametrize("actions", [[action(qty=0)], [action(qty=True)], [action(qty=1.5)], [action(qty=-3)], [action(pid="invented")], [action("write")], [action("remove", "tepache", 0)], [action("cancel", "", 0), action()], [action(qty=1000000)]])
def test_invalid_semantics_reject_entire_command(catalog, actions):
    with pytest.raises(Problem): validate_result(result(actions), "withdrawal", catalog, {"sapporo":1})


def test_ambiguity_holds_all_edits_and_direction_rejected(catalog):
    value = result([action()]); value.update(status="clarify", question="Which drink?", candidate_ids=["sapporo", "tepache"])
    assert validate_result(value, "withdrawal", catalog, {})["status"] == "clarify"
    with pytest.raises(Problem): validate_result(value, "receiving", catalog, {})
    value["candidate_ids"] = ["invented"]
    with pytest.raises(Problem): validate_result(value, "withdrawal", catalog, {})


@pytest.mark.parametrize("failure", [None, "refusal", "incomplete", "bad_json", "wrong_id", "direction", "timeout", "quota"])
def test_voice_provider_context_validation_and_single_call(catalog, failure):
    calls = []
    def provider(req):
        calls.append(req)
        assert str(req.url) == "https://api.openai.com/v1/responses"
        body = json.loads(req.content)
        context = json.loads(body["input"])
        assert len(context["catalog"]) == len(catalog)
        assert context["basket"] == {"sapporo":1}
        assert body["model"] == "gpt-6.1-sol" and body["store"] is False
        assert body["text"]["format"]["strict"] is True
        if failure == "timeout": raise httpx.ReadTimeout("test")
        if failure == "quota": return httpx.Response(429)
        proposed = result([action(pid="missing" if failure == "wrong_id" else "sapporo")])
        if failure == "direction": proposed["movement_type"] = "receiving"
        content = {"type":"refusal", "refusal":"no"} if failure == "refusal" else {"type":"output_text", "text":"invalid" if failure == "bad_json" else json.dumps(proposed)}
        return httpx.Response(200, json=dict(status="incomplete" if failure == "incomplete" else "completed", output=[dict(type="message", content=[content])], usage={"input_tokens":100, "output_tokens":50}))
    capture = CaptureAssistance(Config(openai_api_key="test-only"), httpx.MockTransport(provider))
    call = capture.interpret(dict(transcript="add two Sapporo", movement_type="withdrawal", lines=[dict(product_id="sapporo", quantity=1)]), catalog)
    if failure:
        with pytest.raises(Problem): run(call)
    else:
        value = run(call)
        assert value["actions"] == [action()] and value["context_bytes"] > 0
    assert len(calls) == 1 and not capture.voice_lock.locked()


def test_missing_key_and_oversized_full_context_do_not_dispatch(catalog):
    capture = CaptureAssistance(Config(), httpx.MockTransport(lambda r: pytest.fail("must not dispatch")))
    body = dict(transcript="add two", movement_type="withdrawal", lines=[])
    with pytest.raises(Problem, match="INV_OPENAI_API_KEY"): run(capture.interpret(body, catalog))
    products = {str(n):dict(id=str(n), name="x"*500, unit="bottle", upc=str(n)) for n in range(300)}
    assert len(json.dumps(products)) > MAX_CONTEXT_BYTES
    with pytest.raises(Problem, match="too large"): run(capture.interpret(body, products))


def test_voice_concurrency_guard(catalog):
    capture = CaptureAssistance(Config(openai_api_key="test-only"))
    capture.voice_lock.acquire()
    with pytest.raises(Problem, match="already running"):
        run(capture.interpret(dict(transcript="add two", movement_type="withdrawal", lines=[]), catalog))
    capture.voice_lock.release()


def test_capture_routes_boundary_and_oversized_submit(tmp_path):
    cfg = Config(state_dir=tmp_path)
    service = DemoService(cfg)
    capture = CaptureAssistance(cfg, httpx.MockTransport(lambda r: pytest.fail("No external dispatch expected")))
    with TestClient(create_app(cfg, service, capture), base_url="http://127.0.0.1:8765") as client:
        status = client.get("/api/status").json()
        headers = {"origin":"http://127.0.0.1:8765", "x-session-token":status["token"]}
        for route in ("lookup", "voice"):
            assert client.post("/api/capture/" + route, json={}).status_code == 403
            assert client.post("/api/capture/" + route, json={}, headers={**headers,"origin":"https://evil.test"}).status_code == 403
        value = client.post("/api/capture/lookup", json=dict(upc="000780000011", movement_type="withdrawal"), headers=headers)
        assert value.status_code == 200 and value.json()["status"] == "known"
        value = client.post("/api/capture/voice", json=dict(transcript="add two", movement_type="withdrawal", lines=[]), headers=headers)
        assert value.status_code == 503 and "INV_OPENAI_API_KEY" in value.json()["error"]
        assert "openai_api_key" not in status and "voice_available" in status
        oversized = client.post("/api/receiving", content='{"padding":"' + 'x' * 65536 + '"}', headers={**headers, "content-type":"application/json"})
        assert oversized.status_code == 413 and service.write_count == 0


def test_total_deadline_does_not_retry():
    calls = []
    async def slow(req):
        calls.append(req)
        await asyncio.sleep(.1)
        return httpx.Response(200, json={})
    capture = CaptureAssistance(Config(), httpx.MockTransport(slow))
    with pytest.raises(TimeoutError):
        run(capture.fetch_json("GET", "https://api.upcitemdb.com/prod/trial/lookup", seconds=.01, limit=100))
    assert len(calls) == 1


@pytest.mark.parametrize("status,code,expected", [
    (429,"insufficient_quota","quota is exhausted"),
    (429,"rate_limit_exceeded","rate limit was reached"),
    (429,"slow_down","rate limit was reached"),
    (429,"credit_balance_exhausted","credits are exhausted"),
    (429,"project_spend_limit_exceeded","project's spending limit"),
    (429,"organization_spend_limit_exceeded","organization's spending limit"),
    (429,"organization_usage_limit_exceeded","usage allowance"),
    (429,None,"quota or rate limit (429)"),
    (401,"invalid_api_key","rejected the API key"),
    (403,"permission_denied","does not have permission"),
    (404,"model_not_found","model is unavailable"),
    (400,"invalid_request_error","request configuration"),
    (503,"server_error","temporarily unavailable"),
])
def test_voice_provider_rejections_keep_bounded_error_body_and_safe_message(catalog, status, code, expected):
    calls = []
    def provider(req):
        calls.append(req)
        return httpx.Response(status, json={"error":{"code":code,"type":code,"message":"DO_NOT_EXPOSE_PROVIDER_MESSAGE_OR_SECRET"}})
    capture = CaptureAssistance(Config(openai_api_key="fixture-only"), httpx.MockTransport(provider))
    with pytest.raises(Problem, match=re.escape(expected)) as caught:
        run(capture.interpret(dict(transcript="add two Sapporo",movement_type="withdrawal",lines=[]),catalog))
    assert "DO_NOT_EXPOSE" not in str(caught.value)
    assert "fixture-only" not in str(caught.value)
    assert caught.value.status == 502 and "Basket unchanged" in str(caught.value)
    assert len(calls) == 1 and not capture.voice_lock.locked()


def test_voice_invalid_error_body_falls_back_to_status(catalog):
    capture = CaptureAssistance(Config(openai_api_key="fixture-only"), httpx.MockTransport(lambda req: httpx.Response(429,content=b"<html>not json</html>")))
    with pytest.raises(Problem, match="quota or rate limit"):
        run(capture.interpret(dict(transcript="add two",movement_type="withdrawal",lines=[]),catalog))


@pytest.mark.parametrize("status", [200,429])
def test_compressed_provider_body_is_decoded_once(status):
    payload = {"error":{"code":"insufficient_quota"}} if status == 429 else {"items":[]}
    def provider(req):
        return httpx.Response(status, content=gzip.compress(json.dumps(payload).encode()), headers={"content-encoding":"gzip"})
    capture = CaptureAssistance(Config(), httpx.MockTransport(provider))
    call = capture.fetch_json("GET", "https://api.upcitemdb.com/prod/trial/lookup", seconds=1, limit=1000)
    if status == 200:
        assert run(call) == payload
    else:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            run(call)
        assert caught.value.response.json() == payload
