// Offline browser-script harness, not a live browser or website automation tool.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const { gunzipSync } = require('node:zlib');
const root = path.resolve(__dirname, '..');
const script = fs.readFileSync(path.join(root, 'browser-bridge/royale-replay-phone.user.js'), 'utf8');
const fixture = fs.readFileSync(path.join(root, 'app/assets/synthetic.html'), 'utf8');
function harness(options = {}) {
  const elements = [], state = { clones: 0, stripped: false, opened: 0 };
  function element(tag) {
    const value = { tag, style: {}, handlers: {}, textContent: '', disabled: false,
      addEventListener(type, fn) { this.handlers[type] = fn; }, append() {}, removeAttribute(name) { delete this[name]; },
      click() { let prevented = false; if (this.handlers.click) this.handlers.click({ preventDefault() { prevented = true; } });
        if (this.href && !prevented) state.opened++; }
    }; elements.push(value); return value;
  }
  const location = { href: options.url || 'https://royaleapi.com/replay?tag=SYNTHETIC01&team_tags=ABCDEF' };
  const context = { URL, URLSearchParams, TextEncoder, Blob, Response,
    Uint8Array, btoa: value => Buffer.from(value, 'binary').toString('base64'), location,
    document: { getElementById() { return null; }, createElement: element, body: { append() {} },
      querySelectorAll() { return options.login ? [] : [{ getAttribute() { return 'SYNTHETIC01'; } }]; },
      querySelector() { return options.login ? null : {}; }, documentElement: { cloneNode() {
        state.clones++; return { outerHTML: options.html || fixture, querySelector() { return { remove() { state.stripped = true; } }; } };
      } } }
  }; context.window = { top: 1, self: 1,
    CompressionStream: options.noCompression ? undefined : CompressionStream,
    crypto: options.noCrypto ? undefined : webcrypto };
  vm.runInNewContext(script, context);
  return { state, location, elements, button: elements.find(e => e.tag === 'button'),
    note: elements.find(e => e.tag === 'div'), open: elements.find(e => e.tag === 'a') };
}
(async () => {
  let count = 0;
  const valid = harness(); assert.equal(valid.state.clones, 0); count++;
  await valid.button.handlers.click();
  assert.equal(valid.state.clones, 1); assert.equal(valid.state.stripped, true);
  assert.equal(valid.state.opened, 1); assert.equal(valid.button.disabled, false); count++;
  const intent = valid.open.href;
  assert.ok(intent.endsWith('#Intent;scheme=royalereplay;package=local.royale.replay.android;end'));
  const link = intent.replace(/^intent:/, 'royalereplay:').split('#Intent;')[0], url = new URL(link);
  const bytes = gunzipSync(Buffer.from(url.searchParams.get('html_gzip'), 'base64url'));
  assert.equal(bytes.toString('utf8'), '<!doctype html>\n' + fixture);
  const hash = Buffer.from(await webcrypto.subtle.digest('SHA-256', bytes)).toString('hex');
  assert.equal(url.searchParams.get('sha256'), hash); count++;
  if (process.argv[2]) fs.writeFileSync(process.argv[2], link, { mode: 0o600 });
  await valid.button.handlers.click(); assert.equal(valid.state.clones, 2); count++;
  valid.location.href = 'https://royaleapi.com/replay?tag=OTHER01';
  valid.open.click(); assert.equal(valid.state.opened, 2); assert.equal(valid.open.href, undefined); count++;
  const login = harness({ login: true }); await login.button.handlers.click();
  assert.equal(login.state.clones, 0); assert.equal(login.state.opened, 0); count++;
  for (const options of [{ noCompression: true }, { noCrypto: true }]) {
    const unsupported = harness(options); await unsupported.button.handlers.click();
    assert.equal(unsupported.state.clones, 0); assert.equal(unsupported.state.opened, 0);
    assert.equal(unsupported.button.disabled, false); assert.match(unsupported.note.textContent, /不支持安全压缩/); count++;
  }
  for (const bad of ['https://evil.test/replay?tag=SYNTHETIC01', 'http://royaleapi.com/replay?tag=SYNTHETIC01',
    'https://royaleapi.com/replay?tag=SYNTHETIC01&tag=SYNTHETIC01', 'https://user@royaleapi.com/replay?tag=SYNTHETIC01']) {
    assert.equal(harness({ url: bad }).button, undefined); count++;
  }
  const giant = harness({ html: 'A'.repeat(25 * 1024 * 1024 + 1) }); await giant.button.handlers.click();
  assert.equal(giant.state.opened, 0); assert.match(giant.note.textContent, /25MB/); count++;
  const noise = harness({ html: require('node:crypto').randomBytes(240000).toString('base64') });
  await noise.button.handlers.click(); assert.equal(noise.state.opened, 0); assert.match(noise.note.textContent, /传输上限/); count++;
  console.log('PASS ' + count + ' offline browser-script checks');
})().catch(error => { console.error(error.message); process.exitCode = 1; });
