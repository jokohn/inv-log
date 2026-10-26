/* Real controls and HTTP routes; recognition/provider fixtures do not prove device acceptance. */
const {chromium} = require(process.env.INV_PLAYWRIGHT || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
function expect(locator) {
  async function poll(read, matches, description) {
    const end = Date.now() + 6000;
    let actual;
    while (Date.now() < end) {
      try { actual = await read(); if (matches(actual)) return; } catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error(`${description}: ${locator} returned ${JSON.stringify(actual)}`);
  }
  return {
    toHaveValue: v => poll(() => locator.inputValue(), x => x === v, `Expected value ${v}`),
    toHaveText: v => poll(() => locator.textContent(), x => x === v, `Expected text ${v}`),
    toContainText: v => poll(() => locator.textContent(), x => x?.includes(v), `Expected text containing ${v}`),
    toHaveCount: v => poll(() => locator.count(), x => x === v, `Expected count ${v}`),
    toBeVisible: () => poll(() => locator.isVisible(), x => x, 'Expected visible'),
    toBeHidden: () => poll(() => locator.isVisible(), x => !x, 'Expected hidden'),
    toBeDisabled: () => poll(() => locator.isDisabled(), x => x, 'Expected disabled'),
    toBeEnabled: () => poll(() => locator.isEnabled(), x => x, 'Expected enabled'),
  };
}
(async () => {
  const root = path.resolve(__dirname, '../..');
  const python = process.env.INV_PYTHON || path.join(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
  const port = process.env.INV_BROWSER_TEST_PORT || '8882';
  const server = spawn(python, ['tests/browser/server.py'], {cwd:root, windowsHide:true, env:{...process.env,PYTHONPATH:root,INV_BROWSER_TEST_PORT:port}});
  await new Promise((resolve,reject) => {
    const timer = setTimeout(() => {server.kill(); reject(new Error('Fixture server did not start'));}, 10000);
    server.on('error', error => {clearTimeout(timer); reject(error);});
    server.stderr.on('data', chunk => {if (chunk.toString().includes('Uvicorn running')) {clearTimeout(timer); resolve();}});
    server.on('exit', code => {clearTimeout(timer); reject(new Error(`Fixture server exited ${code}`));});
  });
  const browser = await chromium.launch({headless:true});
  const context = await browser.newContext({viewport:{width:1440,height:1100}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await context.addInitScript(() => {
    window.SpeechRecognition = class {
      start() { window.testRecognition = this; }
      stop() { this.onend?.(); }
      abort() { this.onend?.(); }
    };
  });
  const qty = name => page.getByRole('spinbutton', {name:'Quantity for ' + name, exact:true});
  const scan = async upc => {await page.locator('#barcode').fill(upc); await page.locator('#barcode').press('Enter');};
  const speak = async (command, duplicate=false) => {
    await page.locator('#mic').click();
    await expect(page.locator('#record')).toBeDisabled();
    await page.evaluate(({command, duplicate}) => {
      const rec = window.testRecognition;
      const part = [{transcript:command}]; part.isFinal = true;
      rec.onresult({results:[part]});
      if (duplicate) rec.onresult({results:[part]});
      rec.onend();
      if (duplicate) rec.onend();
    }, {command, duplicate});
  };
  try {
    await page.goto(`http://127.0.0.1:${port}`);
    await expect(page.locator('#connection')).toHaveText('Local demo connected');
    await scan('001234567890');
    await expect(page.locator('#basket .basket-line')).toHaveCount(0); // withdrawal cannot create
    await page.locator('#movement-type').selectOption('receiving');
    let lookups = 0; page.on('request', r => {if(r.url().endsWith('/api/capture/lookup')) lookups++;});
    await scan('001234567890');
    await expect(page.getByLabel('New product name 001234567890')).toHaveValue('New demo drink');
    await scan('001234567890'); await expect(qty('New demo drink')).toHaveValue('2');
    assert.equal(lookups, 1);
    await scan('001234567891');
    await expect(page.getByLabel('New product name 001234567891')).toBeVisible();
    await page.getByLabel('New product name 001234567891').fill('<img src=x onerror=alert(1)>');
    await page.getByLabel('New product unit 001234567891').fill('bottle');
    await page.reload();
    await expect(page.getByLabel('New product name 001234567890')).toHaveValue('New demo drink');
    await expect(page.getByLabel('New product name 001234567891')).toHaveValue('<img src=x onerror=alert(1)>');
    assert.equal(await page.locator('#basket img').count(), 0);
    await scan('000780000011');
    await speak('two drinks', true);
    await expect(qty('Sapporo Premium')).toHaveValue('3');
    await expect(qty('Tepache · Spiced Pineapple')).toHaveValue('3');
    await expect(page.locator('#basket')).toContainText('mixed');
    await speak('set three'); await expect(qty('Sapporo Premium')).toHaveValue('3');
    await speak('remove'); await expect(qty('Tepache · Spiced Pineapple')).toHaveCount(0);
    await speak('ambiguous');
    await expect(page.locator('#clarification')).toBeVisible();
    await expect(qty('Sapporo Premium')).toHaveValue('3'); // all edits held
    await expect(page.locator('#record')).toBeDisabled();
    await page.locator('#voice-discard').click();
    await expect(qty('Sapporo Premium')).toHaveValue('3');
    await speak('ambiguous'); await expect(page.locator('#clarification')).toBeVisible();
    await page.locator('#clarify-answer').fill('Tepache'); await page.locator('#clarify-answer').press('Enter');
    await expect(qty('Sapporo Premium')).toHaveValue('5');
    await expect(qty('Tepache · Spiced Pineapple')).toHaveValue('1');
    await speak('slow');
    await qty('Sapporo Premium').fill('7');
    await expect(page.locator('#scan-feedback')).toContainText('Voice response discarded');
    await expect(qty('Sapporo Premium')).toHaveValue('7');
    await qty('Sapporo Premium').fill(''); await expect(page.locator('#record')).toBeDisabled();
    await scan('008500395210'); await expect(page.locator('#record')).toBeDisabled();
    await expect(qty('Sapporo Premium')).toHaveValue('');
    await qty('Sapporo Premium').fill('7');
    await page.locator('#mic').click(); await page.reload();
    await expect(page.locator('#alert')).toContainText('Unfinished voice work was discarded');
    await expect(qty('Sapporo Premium')).toHaveValue('7');
    await speak('ambiguous'); await expect(page.locator('#clarification')).toBeVisible();
    await qty('Sapporo Premium').fill('8');
    await expect(page.locator('#clarification')).toBeHidden();
    await expect(page.locator('#record')).toBeEnabled();
    fs.mkdirSync('artifacts/pre-demo-browser', {recursive:true});
    await page.screenshot({path:'artifacts/pre-demo-browser/basket.png',fullPage:true});
    await page.locator('#record').click();
    await expect(page.locator('#receipt')).toBeVisible();
    await expect(page.locator('#receipt-summary')).toContainText('Transaction rows and balances verified');
    await page.screenshot({path:'artifacts/pre-demo-browser/receipt.png',fullPage:true});
    await page.locator('#next-basket').click();
    await page.locator('#movement-type').selectOption('withdrawal');
    await speak('two drinks'); await expect(qty('Sapporo Premium')).toHaveValue('2');
    await page.locator('#record').click(); await expect(page.locator('#receipt')).toBeVisible();
    await page.locator('#next-basket').click();
    await speak('two drinks'); await expect(qty('Sapporo Premium')).toHaveValue('2');
    await speak('cancel'); await expect(page.locator('#basket .basket-line')).toHaveCount(0);
    await scan('000780000011');
    await page.locator('#mic').click();
    await page.evaluate(() => window.testRecognition.onerror({error:'not-allowed'}));
    await expect(qty('Sapporo Premium')).toHaveValue('1');
    await expect(page.locator('#record')).toBeEnabled();
    // A no-op set must leave barcode attribution intact.
    await speak('set three'); await expect(qty('Sapporo Premium')).toHaveValue('3');
    await page.getByRole('button',{name:'Remove Sapporo Premium',exact:true}).click();
    await scan('000780000011'); await scan('000780000011'); await scan('000780000011');
    await speak('set three');
    await expect(page.locator('#mic')).toBeEnabled();
    await expect(page.locator('#basket')).toContainText('barcode');
    assert.equal((await page.locator('#basket').textContent()).includes('mixed'), false);
    await speak('quota');
    await expect(page.locator('#scan-feedback')).toContainText('OpenAI API quota is exhausted');
    await expect(qty('Sapporo Premium')).toHaveValue('3');
    await expect(page.locator('#record')).toBeEnabled();
    // A late successful response after the browser deadline cannot change the basket.
    await page.route('**/api/capture/voice', async route => {
      await new Promise(resolve => setTimeout(resolve, 31000));
      try { await route.fulfill({json:{status:'ready', actions:[{action:'add', product_id:'sapporo',quantity:100}], question:'', candidate_ids:[]}}); } catch {}
    });
    await speak('timeout');
    await page.waitForTimeout(31500);
    await expect(page.locator('#scan-feedback')).toContainText('timed out after 30 seconds');
    await expect(qty('Sapporo Premium')).toHaveValue('3');
    await expect(page.locator('#record')).toBeEnabled();
    await page.unroute('**/api/capture/voice');
    // Mobile-width layout stays within the viewport.
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({path:'artifacts/pre-demo-browser/mobile.png',fullPage:true});
    assert.deepEqual(errors, []);
    console.log('Browser acceptance passed: onboarding, repeat scan, literal text, voice add/set/remove/cancel, duplicate/stale responses, clarification, numeric gate, refresh, mixed receiving and withdrawal receipts.');
  } finally { await browser.close(); server.kill(); }
})().catch(e => {console.error(e); process.exitCode=1;});
