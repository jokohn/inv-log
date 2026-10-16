/* Browser drafts are advisory. The server revalidates and owns submitted recovery. */
const $ = (id) => document.getElementById(id);
let state = null, draft = {lines: [], request_id: null, phase: 'draft', movement_type:'withdrawal'}, busy = false, storageKey, invalidDraft = false;
function movement(value) {
  if (!Object.hasOwn(value, 'movement_type')) return 'withdrawal';
  if (!['withdrawal', 'receiving'].includes(value.movement_type)) throw new Error('Unknown saved movement type. Resolve the saved draft before continuing.');
  return value.movement_type;
}
const receiving = () => movement(draft) === 'receiving';
const sign = (value) => movement(value) === 'receiving' ? '+' : '−';
const esc = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const product = (id) => state?.products.find(p => p.id === id);
const isLocked = () => invalidDraft || busy || draft.phase === 'sending' || Boolean(state?.pending.length);
const total = () => draft.lines.reduce((sum, l) => sum + l.quantity, 0);
function alertMessage(message) { $('alert').textContent = message || ''; $('alert').hidden = !message; }
function persist() {
  try { localStorage.setItem(storageKey, JSON.stringify(draft)); }
  catch { alertMessage('Browser draft storage is unavailable. Keep this tab open until the stock movement is verified.'); }
}
function changed() { draft.request_id = crypto.randomUUID(); draft.phase = 'draft'; persist(); render(); }
function feedback(title, detail, error = false) {
  $('scan-feedback').classList.toggle('error', error);
  $('scan-feedback').innerHTML = `<span class="feedback-symbol">${error ? '!' : '✓'}</span><div><strong>${esc(title)}</strong><p>${esc(detail)}</p></div>`;
}
function focusStatus() {
  const ready = document.activeElement === $('barcode') && !isLocked() && state?.connected;
  $('focus-status').textContent = ready ? 'Ready to scan' : isLocked() ? 'Capture paused' : 'Click to focus';
  $('focus-status').classList.toggle('ready', Boolean(ready));
}
function scan(upc) {
  if (isLocked() || !state?.connected) return;
  const matches = state.products.filter(p => p.upc === upc);
  if (matches.length !== 1) {
    feedback(matches.length ? 'Barcode has multiple matches' : 'Barcode not recognized', 'Check the exact barcode and catalog. Nothing was added.', true);
  } else {
    const p = matches[0], line = draft.lines.find(l => l.product_id === p.id);
    if (line?.quantity >= 1000000 || (!line && draft.lines.length >= 200)) {
      feedback('Basket limit reached', 'Use at most 200 products and 1,000,000 units per product.', true);
      $('barcode').value = ''; $('barcode').focus(); return;
    }
    if (line) line.quantity++; else draft.lines.push({product_id:p.id, quantity:1});
    changed();
    feedback(`${p.name} added`, `${p.unit} · ${p.count} available · ${line ? line.quantity : 1} in basket`);
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
    return `<div class="basket-line"><div class="product-details"><strong>${esc(p?.name || l.product_id)}</strong><p>${esc(p?.unit || 'Unavailable product')}</p><span class="stock ${p && !receiving() && p.count < l.quantity ? 'low' : ''}">${p ? `${p.count} available${!receiving() && p.count < l.quantity ? ' · exceeds stock' : ''}` : 'Refresh catalog before saving'}</span></div><div class="qty-controls"><div class="qty-box"><button data-action="minus" data-id="${esc(l.product_id)}" aria-label="Decrease ${esc(p?.name || l.product_id)}" ${locked?'disabled':''}>−</button><input aria-label="Quantity for ${esc(p?.name || l.product_id)}" type="number" min="1" max="1000000" step="1" value="${l.quantity}" data-id="${esc(l.product_id)}" ${locked?'disabled':''}><button data-action="plus" data-id="${esc(l.product_id)}" aria-label="Increase ${esc(p?.name || l.product_id)}" ${locked?'disabled':''}>+</button></div><button class="remove" data-action="remove" data-id="${esc(l.product_id)}" aria-label="Remove ${esc(p?.name || l.product_id)}" ${locked?'disabled':''}>×</button></div></div>`;
  }).join('') : '<div class="basket-empty"><div class="basket-symbol">▱</div><strong>Your basket is waiting</strong><p>Scan an item to start your next stock movement.</p></div>';
  $('recovery-panel').hidden = !(draft.phase === 'sending' || state?.pending.length);
  $('recovery-id').textContent = state?.pending[0]?.request_id || (draft.phase === 'sending' ? draft.request_id : '') || '';
  $('recover').disabled = busy;
  $('recent').innerHTML = state?.recent.length ? state.recent.map(r => `<div class="recent-row"><span class="recent-check">✓</span><div><strong>${esc(r.lines.map(l => l.name).join(', '))}</strong><small>${esc(new Date(r.timestamp).toLocaleString('en-US', {timeZone:'America/Chicago', month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}))} · Chicago · ${movement(r) === 'receiving' ? 'Received' : 'Withdrawn'} · Verified</small></div><span>${sign(r)}${r.total_units}</span></div>`).join('') : '<div class="empty-activity"><span>◷</span><p>No stock movements recorded yet.<br><small>Verified saves will appear here.</small></p></div>';
  focusStatus();
}
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Session-Token':state.token}, body:JSON.stringify(body)};
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
  if (busy || !state?.connected || !draft.lines.length || (isLocked() && draft.phase !== 'sending')) return;
  if (draft.phase !== 'sending') {
    for (const input of $('basket').querySelectorAll('input[data-id]')) {
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
    const receipt = await api(receiving() ? '/api/receiving' : '/api/withdrawals', {request_id:draft.request_id, lines:draft.lines, movement_type:draft.movement_type});
    complete(receipt);
  } catch (error) {
    // Only known validation/rejection returns the basket to editing. Unknown outcomes stay locked.
    if (error.status === 422) { draft.phase = 'draft'; persist(); }
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
  if (button.dataset.action === 'remove') draft.lines = draft.lines.filter(l => l !== line);
  else line.quantity = Math.max(1, Math.min(1000000, line.quantity + (button.dataset.action === 'plus' ? 1 : -1)));
  changed();
});
$('basket').addEventListener('input', e => {
  if (!e.target.matches('input') || isLocked()) return;
  const qty = Number(e.target.value);
  if (!Number.isInteger(qty) || qty < 1 || qty > 1000000) { alertMessage('Enter a positive whole-number quantity.'); $('record').disabled = true; return; }
  draft.lines.find(l => l.product_id === e.target.dataset.id).quantity = qty;
  draft.request_id = crypto.randomUUID(); draft.phase = 'draft'; persist();
  alertMessage(''); $('total').textContent = total(); $('record').disabled = !state?.connected;
});
$('record').addEventListener('click', submit);
$('movement-type').addEventListener('change', e => {
  if (isLocked() || draft.lines.length) { render(); return; }
  draft.movement_type = movement({movement_type:e.target.value});
  changed(); alertMessage(''); $('barcode').focus();
});
$('toggle-demo').addEventListener('click', () => {
  $('demo-catalog').hidden = !$('demo-catalog').hidden;
  $('toggle-demo').textContent = $('demo-catalog').hidden ? 'Show demo barcodes ↗' : 'Hide demo barcodes ↗';
});
$('catalog-items').addEventListener('click', e => {const button = e.target.closest('[data-upc]'); if (button) scan(button.dataset.upc);});
$('refresh').addEventListener('click', () => {alertMessage(''); refresh();});
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
refresh(true);
