# McCormick prototype runbook

October 25, 2026 · Feedback prototype for October 26 · Single capture station

## Start and setup

1. Use the existing local app/launcher on the MacBook. Start with `INV_MODE=demo`; demo and Google journals remain separate. Do not migrate, repair or reset the live workbook as part of this rehearsal.
2. For live voice later, the user creates/selects an OpenAI API project, enables API billing if necessary and creates a project key. Store it as `INV_OPENAI_API_KEY` only in ignored local `.env`; leave `INV_VOICE_MODEL=gpt-6.1-sol`. Restart. No secret belongs in chat, browser code, screenshots or commits.
3. Use a browser that supports SpeechRecognition/webkitSpeechRecognition. Permit the microphone and test real completed speech. Browser speech service/network availability and noisy-room behavior must be checked on the target laptop.
4. Only switch to the already migrated, approved test Google workbook with exclusive writer access after demo rehearsal. Preserve its original local recovery state. This build does not synchronize the separate legacy voice workbook.

## Rehearse with the person who will demonstrate

| Step | Expected behavior |
|---|---|
| Known barcode, repeated scan, plus/minus, direct quantity | One consolidated line; whole positive quantities; leading zeros preserved |
| Unknown barcode during withdrawal | Rejection; no staged product |
| Unknown barcode during receiving | Editable new product, quantity one; unique complete lookup prefills name/unit |
| No match, partial lookup, quota or network failure | Manual completion retains valid fields; no repeat call for staged scans |
| Several new items and known items together | Review name, unit and quantities; one Submit; zero opening counts plus signed receiving rows |
| Speak “withdraw two Sapporo and three Tepache” | Proposed edits appear in basket; no stock write |
| “Add three more Sapporo”, then “change Sapporo to three” | Increment then replace; quantities visible for review |
| Remove a line / cancel the draft | Only requested draft changes; no stock write |
| Ambiguous brand, missing quantity, unknown vodka | Clarification or unsupported feedback; entire ambiguous edit set held |
| Answer clarification / discard / edit another line | Full resolved command applies once / held command removed / old command invalidated |
| Scan or edit while voice processes | Edit continues; older answer cannot apply |
| Submit during recording/processing/clarification | Disabled; finish or discard voice, review, click freshly |
| Denied mic, recognition failure, 30s interpretation timeout | Basket retained, controls restored, late replies ignored |
| Reload during voice work | Basket/staged metadata retained; unfinished voice discarded with notice |
| Receive/withdraw and review receipt | Transaction rows, new catalog metadata, formulas and balances verified |
| Interrupted save | Both modes locked until Check recovery proves the exact outcome; never blind retry under a new ID |

Existing catalog units only; no case conversion, fractional quantities, operator/destination fields or products without scanned UPCs. Observe those cases for later decisions.

## Offline checks

```sh
python -m pytest -q --basetemp=artifacts/pytest-pre-demo
node --check app/static/app.js
node tests/browser/capture.cjs
python -m scripts.rehearse_voice
```

Browser checks need an installed Playwright package and Chromium; `INV_PLAYWRIGHT` can point to the bundled package and `INV_PYTHON` to the project Python. They start their own server on port 8882 (override `INV_BROWSER_TEST_PORT`), use temporary demo data, simulate recognition and mock both providers. They exercise real controls/routes and never connect to Google or OpenAI. A local environment that blocks Python's loopback event-loop sockets needs loopback access to run API/async/browser checks. The suite retains the existing dependency deprecation warning.

The rehearsal command without `--live` is a zero-request dry run. For later user-run API acceptance:

```sh
python -m scripts.rehearse_voice --live
```

The live command uses a fixed in-memory demo catalog even when `.env` selects Google. It sends no stock writes. Eleven semantic cases cover two-product capture, add/set/remove/cancel, product matching, ambiguity, clarification, direction and fractions. Wrong product/quantity/action or omission stops the rehearsal. A durable reservation before each call bounds cumulative task spend below $5, including failed/uncertain calls and reruns. Do not delete `.state/pre-demo-voice-rehearsal.json` to reset the cap. Review its reported token usage, reported cost estimate and conservative reservations. Rates ($2/M input, $10/M output) were verified for GPT-6.1 Sol on October 25; verify before using the harness with future pricing. This harness does not cap ordinary user-triggered app voice use; use API project billing controls separately.

Measure the actual target catalog separately before voice use. The server sends the complete compact validated catalog and returns `context_bytes` plus a conservative byte-based `token_upper_bound` (tokens cannot exceed UTF-8 bytes, with prompt/schema overhead). Context over 120,000 bytes is rejected, never truncated; this guard sits well below the documented model context. These are conservative size bounds, not a tokenizer's exact count. Record actual returned usage and latency during live rehearsal. API context size does not increase the existing 65,536-byte local request limit; oversized save requests reject definitively and retain editability.

## Verification record for this implementation

- Offline pytest: 145 passed, one existing dependency warning. Includes old withdrawals/receiving, historical payloads/receipts, literal text, provider failures, boundary controls, metadata/label identity conflicts, catalog collisions, 60/200-product baskets, capacities/formulas and recovery after rejection, timeout, restart and partial evidence.
- Browser fixture acceptance: onboarding/manual fallback, repeated scans, literal hostile-looking text, actual shared basket controls, voice semantics, duplicate delivery, stale results, clarification, refresh, numeric gating, verified receiving/withdrawal receipts, recognition errors, no-op attribution, a full 30-second timeout with late success ignored, and narrow-screen layout. Recognition and services are fixtures, not live evidence.
- User selected “Not yet; finish offline verification” for API setup. Live model requests: **0**. Actual spend: **$0**.
- Live model semantics, actual catalog fit/latency, UPCitemdb hotel coverage, Google atomic acceptance/readback, MacBook microphone/browser and physical D5100 scanner acceptance remain unverified. Do not claim demo readiness until the applicable target checks pass.

## During the visit

### Voice provider error follow-up (October 25)

After the original offline verification, the user approved one live diagnostic capped at $0.10. It used only fixed demo products and made no stock writes. OpenAI returned HTTP 429; no successful interpretation or token usage was returned. The original transport raised before reading the streamed error body, so the diagnostic could not establish whether this was quota/billing or rate limiting. The $0.10 conservative reservation remains in the task ledger; it is not a measured charge.

The transport now retains a bounded decoded error body, and the app separately explains credit exhaustion, project/organization spending or usage limits, request rate limits, invalid keys, model access, timeouts, refusal and malformed responses. Raw provider messages, keys and transcripts are not exposed in these errors. Restart the local app to load the change. Review the API project's billing/credits and limits if it reports 429; do not repeatedly retry billing/quota failures. No further live calls were made. Updated offline verification: 161 tests pass, one existing dependency warning; the browser fixture confirms specific quota feedback with the basket retained. Live voice success remains unverified.

Observe barcodes missing from products, cases versus loose units, portions/partial containers, typical basket lengths, noise/light, microphone permissions, Wi-Fi/power, hesitation and corrections. Record examples and request sizes. These observations inform future scope; they do not authorize new conversion or deployment behavior.

## Sources

- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [GPT-6.1 Sol model, context and rates](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [UPCitemdb Explorer/trial integration](https://www.upcitemdb.com/wp/docs/main/development/getting-started/)
