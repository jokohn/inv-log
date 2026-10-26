/* Browser drafts are advisory. The server revalidates and owns submitted recovery. */
const $ = (id) => document.getElementById(id);
let state = null, draft = {lines: [], request_id: null, phase: 'draft', movement_type:'withdrawal'}, busy = false, storageKey, invalidDraft = false;
let revision = 0, voice = {phase:'idle', generation:0}, recognition = null;
const invalidQuantities = new Map(), lookups = new Map();
const stagedProducts = () => draft.new_products || [];
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
function movement(value) {
  if (!Object.hasOwn(value, 'movement_type')) return 'withdrawal';
  if (!['withdrawal', 'receiving'].includes(value.movement_type)) throw new Error('Unknown saved movement type. Resolve the saved draft before continuing.');
  return value.movement_type;
}
const receiving = () => movement(draft) === 'receiving';
const sign = (value) => movement(value) === 'receiving' ? '+' : '−';
const esc = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const product = (id) => stagedProducts().find(p => p.id === id) || state?.products.find(p => p.id === id);
const isLocked = () => invalidDraft || busy || draft.phase === 'sending' || Boolean(state?.pending.length);
const total = () => draft.lines.reduce((sum, l) => sum + l.quantity, 0);
function alertMessage(message) { $('alert').textContent = message || ''; $('alert').hidden = !message; }
function persist() {
  try { localStorage.setItem(storageKey, JSON.stringify(draft)); }
  catch { alertMessage('Browser draft storage is unavailable. Keep this tab open until the stock movement is verified.'); }
}
function changed(redraw = true) {
  revision++;
  draft.request_id = crypto.randomUUID(); draft.phase = 'draft';
  const ids = new Set(draft.lines.map(l => l.product_id));
  draft.new_products = stagedProducts().filter(p => ids.has(p.id));
  draft.capture = Object.fromEntries(draft.lines.map(l => [l.product_id, draft.capture?.[l.product_id] || 'barcode']));
  for (const id of invalidQuantities.keys()) if (!ids.has(id)) invalidQuantities.delete(id);
  if (voice.phase === 'clarify') { discardVoice(); feedback('Clarification discarded', 'Your edit changed the command context. Speak a fresh command.'); }
  persist(); if (redraw) render(); else controls();
}
function contribute(id, method) {
  draft.capture ||= {};
  const old = draft.capture[id];
  draft.capture[id] = old && old !== method ? 'mixed' : method;
}
function incompleteProducts() { return stagedProducts().some(p => !p.name.trim() || !p.unit.trim() || p.name.length > 500 || p.unit.length > 500 || /[\x00-\x1f]/.test(p.name + p.unit)); }
function controls() {
  const blocked = isLocked() || !state?.connected;
  $('record').disabled = blocked || !draft.lines.length || invalidQuantities.size > 0 || incompleteProducts() || voice.phase !== 'idle' || lookups.size > 0;
  $('total').textContent = total();
  $('mic').disabled = blocked || !SpeechRecognition || !state?.voice_available || (voice.phase !== 'recording' && (invalidQuantities.size > 0 || incompleteProducts())) || !['idle','recording'].includes(voice.phase);
  $('mic').textContent = voice.phase === 'recording' ? 'Finish recording' : 'Speak a command';
  $('voice-status').textContent = voice.phase === 'recording' ? 'Listening… Finish recording before Submit.' : voice.phase === 'processing' ? 'Interpreting… Basket edits remain available.' : voice.phase === 'clarify' ? 'Resolve or discard the command before Submit.' : !SpeechRecognition ? 'Speech recognition is unavailable in this browser. Use scanning.' : !state?.voice_available ? 'Voice needs server API setup. Scanning and manual entry are available.' : 'Speak once, finish, then review your basket. Voice never saves stock.';
  $('clarification').hidden = voice.phase !== 'clarify';
  $('voice-discard').hidden = voice.phase === 'idle';
  $('movement-type').disabled = blocked || Boolean(draft.lines.length) || voice.phase !== 'idle' || lookups.size > 0;
}
function feedback(title, detail, error = false) {
  $('scan-feedback').classList.toggle('error', error);
  $('scan-feedback').innerHTML = `<span class="feedback-symbol">${error ? '!' : '✓'}</span><div><strong>${esc(title)}</strong><p>${esc(detail)}</p></div>`;
}
function focusStatus() {
  const ready = document.activeElement === $('barcode') && !isLocked() && state?.connected;
  $('focus-status').textContent = ready ? 'Ready to scan' : isLocked() ? 'Capture paused' : 'Click to focus';
  $('focus-status').classList.toggle('ready', Boolean(ready));
}
async function scan(upc) {
  if (isLocked() || !state?.connected) return;
  const matches = [...state.products, ...stagedProducts()].filter(p => p.upc === upc);
  if (matches.length !== 1) {
    if (!matches.length && receiving() && /^[0-9]{8,14}$/.test(upc) && draft.lines.length < 200) {
      const p = {id:crypto.randomUUID(), upc, name:'', unit:''};
      draft.new_products ||= []; draft.new_products.push(p);
      draft.lines.push({product_id:p.id, quantity:1}); contribute(p.id, 'barcode');
      lookups.set(p.id, true); changed();
      $('barcode').value = ''; $('barcode').focus();
      feedback('New receiving product', 'Looking up barcode… You can complete its name and unit manually.');
      try {
        const result = await api('/api/capture/lookup', {upc, movement_type:'receiving'}, 6000);
        const current = stagedProducts().find(s => s.id === p.id);
        if (current && !current.name && !current.unit) {
          if (result.status === 'known') {
            feedback('Catalog changed', 'Refresh and remove this staged item before scanning the existing product.', true);
          } else {
            current.name = result.name || ''; current.unit = result.unit || ''; changed();
            feedback(result.status === 'complete' ? 'Product details filled' : 'Complete new product details', result.message);
          }
        }
      } catch (error) { feedback('Complete new product details', error.message, true); }
      finally { lookups.delete(p.id); render(); }
      return;
    }
    feedback(matches.length ? 'Barcode has multiple matches' : 'Barcode not recognized', receiving() ? 'Scan an 8–14 digit UPC, then complete the product details.' : 'Unknown products can only be added while receiving.', true);
  } else {
    const p = matches[0], line = draft.lines.find(l => l.product_id === p.id);
    if (line?.quantity >= 1000000 || (!line && draft.lines.length >= 200)) {
      feedback('Basket limit reached', 'Use at most 200 products and 1,000,000 units per product.', true);
      $('barcode').value = ''; $('barcode').focus(); return;
    }
    if (line) line.quantity++; else draft.lines.push({product_id:p.id, quantity:1});
    invalidQuantities.delete(p.id);
    contribute(p.id, 'barcode');
    changed();
    feedback(`${p.name || 'New receiving product'} added`, `${p.unit || 'Complete catalog unit'} · ${p.count ?? 0} available · ${line ? line.quantity : 1} in basket`);
  }
  $('barcode').value = '';
  $('barcode').focus();
}
function render() {
  const locked = isLocked();
  $('movement-type').value = draft.movement_type;
  $('movement-type').disabled = locked || Boolean(draft.lines.length);
  $('total-label').textContent = receiving() ? 'Total receiving' : 'Total withdrawal';
  document.body.classList.toggle('busy', busy);
  $('barcode').disabled = locked || !state?.connected;
  $('scan-form').querySelector('button').disabled = $('barcode').disabled;
  $('item-count').textContent = `${draft.lines.length} product${draft.lines.length === 1 ? '' : 's'}`;
  $('total').textContent = total();
  $('record').disabled = locked || !state?.connected || !draft.lines.length;
  $('record').textContent = busy ? 'Verifying stock movement…' : locked ? 'Waiting for verification' : receiving() ? 'Receive stock +' : 'Record withdrawal ↗';
  $('basket').innerHTML = draft.lines.length ? draft.lines.map(l => {
    const p = product(l.product_id);
    const staged = stagedProducts().some(s => s.id === l.product_id);
    return `<div class="basket-line"><div class="product-details">${staged ? `<span class="small-tag">NEW · ${esc(p.upc)}</span><label>Product name<input data-field="name" data-id="${esc(p.id)}" aria-label="New product name ${esc(p.upc)}" maxlength="500" value="${esc(p.name)}" ${locked?'disabled':''}></label><label>Catalog unit<input data-field="unit" data-id="${esc(p.id)}" aria-label="New product unit ${esc(p.upc)}" maxlength="500" placeholder="e.g. 12 oz bottle" value="${esc(p.unit)}" ${locked?'disabled':''}></label>` : `<strong>${esc(p?.name || l.product_id)}</strong><p>${esc(p?.unit || 'Unavailable product')}</p>`}<span class="stock ${p && !receiving() && p.count < l.quantity ? 'low' : ''}">${staged ? 'Created only on verified receiving' : p ? `${p.count} available${!receiving() && p.count < l.quantity ? ' · exceeds stock' : ''}` : 'Refresh catalog before saving'} · ${esc(draft.capture?.[l.product_id] || 'barcode')}</span></div><div class="qty-controls"><div class="qty-box"><button data-action="minus" data-id="${esc(l.product_id)}" aria-label="Decrease ${esc(p?.name || l.product_id)}" ${locked?'disabled':''}>−</button><input aria-label="Quantity for ${esc(p?.name || l.product_id)}" type="number" min="1" max="1000000" step="1" value="${esc(invalidQuantities.get(l.product_id) ?? l.quantity)}" data-id="${esc(l.product_id)}" ${locked?'disabled':''}><button data-action="plus" data-id="${esc(l.product_id)}" aria-label="Increase ${esc(p?.name || l.product_id)}" ${locked?'disabled':''}>+</button></div><button class="remove" data-action="remove" data-id="${esc(l.product_id)}" aria-label="Remove ${esc(p?.name || l.product_id)}" ${locked?'disabled':''}>×</button></div></div>`;
  }).join('') : '<div class="basket-empty"><div class="basket-symbol">▱</div><strong>Your basket is waiting</strong><p>Scan an item to start your next stock movement.</p></div>';
  $('recovery-panel').hidden = !(draft.phase === 'sending' || state?.pending.length);
  $('recovery-id').textContent = state?.pending[0]?.request_id || (draft.phase === 'sending' ? draft.request_id : '') || '';
  $('recover').disabled = busy;
  $('recent').innerHTML = state?.recent.length ? state.recent.map(r => `<div class="recent-row"><span class="recent-check">✓</span><div><strong>${esc(r.lines.map(l => l.name).join(', '))}</strong><small>${esc(new Date(r.timestamp).toLocaleString('en-US', {timeZone:'America/Chicago', month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}))} · Chicago · ${movement(r) === 'receiving' ? 'Received' : 'Withdrawn'} · Verified</small></div><span>${sign(r)}${r.total_units}</span></div>`).join('') : '<div class="empty-activity"><span>◷</span><p>No stock movements recorded yet.<br><small>Verified saves will appear here.</small></p></div>';
  controls(); focusStatus();
}
async function api(path, body, timeout = 0) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Session-Token':state.token}, body:JSON.stringify(body)};
  if (timeout) options.signal = AbortSignal.timeout(timeout);
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) { const error = new Error(data.error || data.detail || 'Request failed.'); error.status = response.status; throw error; }
  return data;
}
async function refresh(initial = false) {
  try {
    const result = await api('/api/status' + (draft.request_id ? '?request_id=' + encodeURIComponent(draft.request_id) : ''));
    state = result;
    if (initial) {
      storageKey = 'inv_flow:draft:' + state.identity;
      try {
        const saved = JSON.parse(localStorage.getItem(storageKey));
        if (saved !== null) {
          if (!saved || !Array.isArray(saved.lines) || !saved.lines.every(l => l && typeof l.product_id === 'string' && Number.isInteger(l.quantity) && l.quantity > 0)) {
            throw new Error('Saved browser draft could not be read. Resolve it before continuing.');
          }
          draft = saved;
        }
        draft.movement_type = movement(draft);
        if (draft.new_products !== undefined && (!Array.isArray(draft.new_products) || !draft.new_products.every(p => p && ['id','upc','name','unit'].every(k => typeof p[k] === 'string') && draft.lines.some(l => l.product_id === p.id)))) throw new Error('Saved staged products are invalid. Resolve the draft before continuing.');
        if (draft.voice_unfinished) { draft.voice_unfinished = false; persist(); alertMessage('Unfinished voice work was discarded after refresh. Basket and staged products are retained.'); }
      } catch (error) {
        invalidDraft = true;
        // Preserve unreadable saved work and pause both modes instead of guessing its direction.
        draft = {lines:[], request_id:null, phase:'draft', movement_type:'withdrawal'};
        alertMessage(error.message || 'Saved browser draft could not be read. Resolve it before continuing.');
      }
      if (draft.request_id) { await refresh(); if (!isLocked()) $('barcode').focus(); return; }
    }
    if (draft.phase === 'sending' && state.request?.state === 'verified') {
      complete(state.request.receipt);
    } else if (draft.phase === 'sending' && state.request?.state === 'rejected') {
      draft.phase = 'draft'; persist();
      alertMessage('The previous write was rejected. Review the retained basket and try again after resolving the cause.');
    }
    if (!invalidDraft && state.pending.length && (!draft.lines.length || state.pending[0].request_id === draft.request_id)) {
      draft = {...state.pending[0], movement_type:movement(state.pending[0]), phase:'sending'}; persist();
    }
    $('mode').textContent = state.mode === 'demo' ? 'DEMO MODE' : 'GOOGLE SHEETS';
    $('device').textContent = state.device;
    $('connection').textContent = state.connected ? (state.mode === 'demo' ? 'Local demo connected' : 'Google Sheets connected') : 'Connection needs attention';
    $('demo-banner').hidden = state.mode !== 'demo';
    $('catalog-items').innerHTML = state.products.map(p => `<button class="catalog-row" data-upc="${esc(p.upc)}"><span>${esc(p.name)}<small>${esc(p.upc)} · ${esc(p.unit)}</small></span><span>+</span></button>`).join('');
    if (!state.connected) alertMessage(state.error);
    render();
    if (initial && !isLocked()) $('barcode').focus();
  } catch (error) {
    if (state) state.connected = false;
    $('connection').textContent = 'Disconnected';
    alertMessage('The local app is unavailable. Your basket is retained. Restart the app, then Refresh.');
    render();
  }
}
function complete(receipt) {
  const kind = movement(receipt);
  draft = {lines:[], request_id:null, phase:'draft', movement_type:kind}; persist();
  alertMessage('');
  $('receipt-summary').textContent = `${receipt.total_units} unit${receipt.total_units === 1 ? '' : 's'} ${kind === 'receiving' ? 'received' : 'withdrawn'}${state.mode === 'demo' ? ' in the local demo' : ' in Google Sheets'}. Transaction rows and balances verified.`;
  $('receipt-lines').innerHTML = receipt.lines.map(l => `<div class="receipt-item"><div>${esc(l.name)}<small>${esc(l.unit)} · ${l.remaining} in stock</small></div><strong>${sign(receipt)}${l.quantity}</strong></div>`).join('');
  $('receipt-reference').textContent = 'Request ' + receipt.request_id;
  if (!$('receipt').open) $('receipt').showModal();
}
async function submit() {
  if (busy || !state?.connected || !draft.lines.length || voice.phase !== 'idle' || invalidQuantities.size || incompleteProducts() || lookups.size || (isLocked() && draft.phase !== 'sending')) return;
  if (draft.phase !== 'sending') {
    for (const input of $('basket').querySelectorAll('input[type="number"][data-id]')) {
      const qty = Number(input.value);
      if (!Number.isInteger(qty) || qty < 1 || qty > 1000000) { alertMessage('Enter a positive whole-number quantity.'); return; }
      draft.lines.find(l => l.product_id === input.dataset.id).quantity = qty;
    }
  }
  busy = true;
  draft.request_id ||= crypto.randomUUID();
  draft.phase = 'sending';
  persist(); render(); alertMessage('');
  try {
    const receipt = await api(receiving() ? '/api/receiving' : '/api/withdrawals', {request_id:draft.request_id, lines:draft.lines, movement_type:draft.movement_type, new_products:stagedProducts(), capture:draft.capture || Object.fromEntries(draft.lines.map(l => [l.product_id, 'barcode']))});
    complete(receipt);
  } catch (error) {
    // Only known validation/rejection returns the basket to editing. Unknown outcomes stay locked.
    if ([413,422].includes(error.status)) { draft.phase = 'draft'; persist(); }
    alertMessage(error.message || 'Save outcome is unknown. Check recovery.');
  } finally {
    busy = false; await refresh(); render();
  }
}
$('scan-form').addEventListener('submit', e => {e.preventDefault(); scan($('barcode').value);});
$('barcode').addEventListener('focus', focusStatus);
$('barcode').addEventListener('blur', focusStatus);
$('basket').addEventListener('click', e => {
  const button = e.target.closest('button[data-action]');
  if (!button || isLocked()) return;
  const line = draft.lines.find(l => l.product_id === button.dataset.id);
  invalidQuantities.delete(button.dataset.id);
  if (button.dataset.action === 'remove') draft.lines = draft.lines.filter(l => l !== line);
  else line.quantity = Math.max(1, Math.min(1000000, line.quantity + (button.dataset.action === 'plus' ? 1 : -1)));
  changed();
});
$('basket').addEventListener('input', e => {
  if (!e.target.matches('input') || isLocked()) return;
  if (e.target.dataset.field) {
    stagedProducts().find(p => p.id === e.target.dataset.id)[e.target.dataset.field] = e.target.value;
    changed(false); return;
  }
  const qty = Number(e.target.value);
  if (!Number.isInteger(qty) || qty < 1 || qty > 1000000) { invalidQuantities.set(e.target.dataset.id, e.target.value); changed(false); alertMessage('Enter a positive whole-number quantity.'); return; }
  invalidQuantities.delete(e.target.dataset.id);
  draft.lines.find(l => l.product_id === e.target.dataset.id).quantity = qty;
  changed(false); alertMessage('');
});
$('record').addEventListener('click', submit);
$('movement-type').addEventListener('change', e => {
  if (isLocked() || draft.lines.length || voice.phase !== 'idle' || lookups.size) { render(); return; }
  draft.movement_type = movement({movement_type:e.target.value});
  changed(); alertMessage(''); $('barcode').focus();
});
$('toggle-demo').addEventListener('click', () => {
  $('demo-catalog').hidden = !$('demo-catalog').hidden;
  $('toggle-demo').textContent = $('demo-catalog').hidden ? 'Show demo barcodes ↗' : 'Hide demo barcodes ↗';
});
$('catalog-items').addEventListener('click', e => {const button = e.target.closest('[data-upc]'); if (button) scan(button.dataset.upc);});
$('refresh').addEventListener('click', () => {
  revision++;
  if (voice.phase !== 'idle') { discardVoice(); feedback('Voice command discarded', 'Catalog refresh changed the command context. Basket retained.'); }
  alertMessage(''); refresh();
});
$('recover').addEventListener('click', async () => {
  if (busy || !state) return;
  busy = true; render();
  try {await api('/api/recovery', {}); await refresh();}
  catch (error) {alertMessage(error.message);}
  finally {busy = false; render();}
  // An HTTP request lost before reaching the journal is safe to retry with exactly the same ID and contents.
  if (draft.phase === 'sending' && state.request?.state === 'unknown' && !state.pending.length) await submit();
});
function closeReceipt() {$('receipt').close(); $('barcode').focus();}
$('close-receipt').addEventListener('click', closeReceipt);
$('next-basket').addEventListener('click', closeReceipt);
$('receipt').addEventListener('close', () => {if (!isLocked()) $('barcode').focus();});
function discardVoice() {
  const old = recognition;
  recognition = null;
  voice = {phase:'idle', generation:voice.generation + 1};
  draft.voice_unfinished = false; persist(); controls();
  if (old) { try { old.abort(); } catch {} }
}
function applyVoice(actions) {
  const next = structuredClone(draft.lines), labels = {...draft.capture};
  for (const a of actions) {
    const line = next.find(l => l.product_id === a.product_id);
    if (a.action === 'cancel') { next.length = 0; continue; }
    if (!product(a.product_id)) throw new Error('Voice referenced an unavailable product. Basket unchanged.');
    if (a.action === 'remove') {
      if (!line) throw new Error('Voice removal is stale. Basket unchanged.');
      next.splice(next.indexOf(line), 1); delete labels[a.product_id]; continue;
    }
    const qty = a.action === 'add' ? (line?.quantity || 0) + a.quantity : a.quantity;
    if (!Number.isInteger(qty) || qty < 1 || qty > 1000000) throw new Error('Voice quantity is invalid. Basket unchanged.');
    if (line?.quantity === qty) continue;
    if (line) line.quantity = qty; else next.push({product_id:a.product_id, quantity:qty});
    const old = labels[a.product_id]; labels[a.product_id] = old && old !== 'voice' ? 'mixed' : 'voice';
  }
  if (next.length > 200) throw new Error('Voice exceeds the basket limit. Basket unchanged.');
  if (JSON.stringify(next) === JSON.stringify(draft.lines)) return false;
  draft.lines = next; draft.capture = labels; changed(); return true;
}
async function interpretVoice(transcript, atRevision, clarification) {
  const generation = voice.generation;
  voice = {phase:'processing', generation, transcript, atRevision};
  draft.voice_unfinished = true; persist(); controls();
  try {
    const body = {transcript, movement_type:draft.movement_type, lines:structuredClone(draft.lines), new_products:structuredClone(stagedProducts())};
    if (clarification) body.clarification = clarification;
    const result = await api('/api/capture/voice', body, 30000);
    if (voice.generation !== generation) return;
    if (revision !== atRevision || isLocked()) { discardVoice(); feedback('Voice response discarded', 'Basket changed while the command was running. Speak a fresh command.', true); return; }
    if (result.status === 'clarify') {
      voice = {phase:'clarify', generation, transcript, atRevision, question:result.question};
      $('voice-question').textContent = result.question;
      $('voice-candidates').textContent = result.candidate_ids.map(id => product(id)?.name || id).join(' · ');
      $('clarify-answer').value = ''; controls(); $('clarify-answer').focus(); return;
    }
    discardVoice();
    if (result.status === 'unsupported') { feedback('Command needs a fresh attempt', result.question || 'Use a supported draft command. Basket unchanged.', true); return; }
    const applied = applyVoice(result.actions);
    feedback(applied ? 'Voice edits applied to draft' : 'No basket changes', 'Review quantities and products, then click Submit when ready.');
  } catch (error) {
    if (voice.generation !== generation) return;
    discardVoice(); feedback('Voice command not applied', error.name === 'TimeoutError' ? 'Interpretation timed out after 30 seconds. Basket unchanged.' : error.message, true);
  } finally { controls(); }
}
$('mic').addEventListener('click', () => {
  if (voice.phase === 'recording') { recognition?.stop(); return; }
  if (isLocked() || !state?.connected || voice.phase !== 'idle' || !SpeechRecognition || !state.voice_available || invalidQuantities.size || incompleteProducts()) return;
  const generation = voice.generation + 1, atRevision = revision;
  const rec = new SpeechRecognition(); recognition = rec;
  voice = {phase:'recording', generation};
  draft.voice_unfinished = true; persist(); controls(); $('transcript').textContent = '';
  rec.lang = 'en-US'; rec.continuous = false; rec.interimResults = true;
  let ended = false, failed = false;
  const finals = new Map();
  const recordingTimer = setTimeout(() => { if (voice.generation === generation) { failed = true; discardVoice(); feedback('Recording ended', 'Recording exceeded 60 seconds. Basket unchanged.', true); } }, 60000);
  rec.onresult = event => {
    if (ended || voice.generation !== generation) return;
    let interim = '';
    for (let i = 0; i < event.results.length; i++) {
      if (event.results[i].isFinal) finals.set(i, event.results[i][0].transcript);
      else interim += event.results[i][0].transcript;
    }
    $('transcript').textContent = [...finals.values()].join(' ') + interim;
  };
  rec.onerror = event => {
    if (voice.generation !== generation) return;
    failed = true; clearTimeout(recordingTimer); discardVoice();
    feedback('Speech recognition unavailable', `Recognition ended (${event.error}). Basket unchanged. Use scanning or manual entry.`, true);
  };
  rec.onend = () => {
    clearTimeout(recordingTimer);
    if (ended || failed || voice.generation !== generation) return;
    ended = true; recognition = null;
    const transcript = [...finals.values()].join(' ').trim();
    if (!transcript || revision !== atRevision) { discardVoice(); feedback('Voice command discarded', transcript ? 'Basket changed during recording. Speak a fresh command.' : 'No completed speech was recognized.', true); return; }
    interpretVoice(transcript, atRevision);
  };
  try { rec.start(); } catch { clearTimeout(recordingTimer); discardVoice(); feedback('Microphone could not start', 'Check browser microphone permission. Basket unchanged.', true); }
});
$('voice-discard').addEventListener('click', () => {discardVoice(); feedback('Voice command discarded', 'Your basket is retained.');});
$('clarify-form').addEventListener('submit', e => {
  e.preventDefault();
  if (voice.phase !== 'clarify' || isLocked() || revision !== voice.atRevision) return;
  const answer = $('clarify-answer').value.trim();
  if (!answer) return;
  interpretVoice(voice.transcript, voice.atRevision, {question:voice.question, answer});
});
refresh(true);
