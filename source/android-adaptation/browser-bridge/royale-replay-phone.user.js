// ==UserScript==
// @name         RoyaleAPI → 安卓控制台播放
// @namespace    local.royale.replay.android
// @version      1.0.1
// @description  点击时将本页完整回放 HTML 交给本机控制台；不上传、不读 Cookie。
// @match        https://royaleapi.com/replay?*
// @match        https://www.royaleapi.com/replay?*
// @run-at       document-idle
// @grant        none
// @noframes
// ==/UserScript==

(() => {
  'use strict';
  if (window.top !== window.self || document.getElementById('royale-replay-phone-bridge')) return;
  const MAX_HTML = 25 * 1024 * 1024, MAX_GZIP = 160 * 1024, MAX_URI = 240 * 1024;
  function sourceURL() {
    const url = new URL(location.href);
    if (url.protocol !== 'https:' || !['royaleapi.com', 'www.royaleapi.com'].includes(url.hostname) ||
        url.port || url.username || url.password || url.pathname !== '/replay' ||
        url.searchParams.getAll('tag').length !== 1 || !/^[A-Z0-9]{6,32}$/.test(url.searchParams.get('tag') || '')) {
      throw new Error('请打开已登录的 RoyaleAPI Replay 详情页。');
    }
    url.hash = '';
    if (url.href.length > 8192) throw new Error('来源网址过长。');
    return url;
  }
  try { sourceURL(); } catch (_) { return; }
  const box = document.createElement('section');
  box.id = 'royale-replay-phone-bridge';
  box.style.cssText = 'position:fixed;bottom:18px;right:12px;z-index:2147483647;background:#142238;color:white;padding:12px;border-radius:12px;max-width:290px;font:14px/1.5 sans-serif;box-shadow:0 4px 20px #0006;';
  const button = document.createElement('button');
  button.textContent = '▶ 在安卓控制台播放';
  button.style.cssText = 'background:#087cf0;color:white;border:0;padding:12px;border-radius:8px;font:700 16px sans-serif;cursor:pointer;';
  const note = document.createElement('div');
  note.textContent = '仅点击时读取本页；本机传递，不上传。';
  const open = document.createElement('a');
  open.textContent = '点这里打开控制台（浏览器未自动跳转时）';
  open.style.cssText = 'display:none;color:#9dd9ff;padding-top:8px;overflow-wrap:anywhere;';
  open.rel = 'noreferrer';
  box.append(button, note, open); document.body.append(box);
  let pending = false, preparedURL = '';
  open.addEventListener('click', event => {
    try {
      if (sourceURL().href !== preparedURL) throw new Error('页面已切换，请重新点播放按钮。');
    } catch (error) { event.preventDefault(); open.removeAttribute('href'); open.style.display = 'none'; note.textContent = error.message; }
  });
  button.addEventListener('click', async () => {
    if (pending) return;
    pending = true; button.disabled = true; open.style.display = 'none'; open.removeAttribute('href');
    try {
      const url = sourceURL(), tag = url.searchParams.get('tag');
      const markers = [...document.querySelectorAll('.battle_replay[data-tag]')];
      if (!markers.length || markers.some(root => root.getAttribute('data-tag').replace(/^#/, '') !== tag) ||
          !document.querySelector('[data-t][data-s][data-c][data-x][data-y]')) {
        throw new Error('本页没有完整回放数据，请完成登录/验证并等待详情加载。');
      }
      if (typeof window.CompressionStream !== 'function' || !window.crypto || !window.crypto.subtle) {
        throw new Error('浏览器不支持安全压缩，请更新 Edge，或保存 HTML 后在控制台选择文件。');
      }
      note.textContent = '正在打包本页回放，仅在本机处理…';
      const clone = document.documentElement.cloneNode(true);
      clone.querySelector('#royale-replay-phone-bridge')?.remove();
      const bytes = new TextEncoder().encode('<!doctype html>\n' + clone.outerHTML);
      if (bytes.length > MAX_HTML) throw new Error('HTML 超过25MB，请保存文件后导入。');
      const hashBytes = new Uint8Array(await window.crypto.subtle.digest('SHA-256', bytes));
      const hash = Array.from(hashBytes, value => value.toString(16).padStart(2, '0')).join('');
      const compressed = new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(new window.CompressionStream('gzip'))).arrayBuffer());
      if (compressed.length > MAX_GZIP) throw new Error('页面超过浏览器传输上限；请保存完整 HTML 后在控制台选择文件，不会删减源指令。');
      let binary = '';
      for (let index = 0; index < compressed.length; index += 8192) binary += String.fromCharCode(...compressed.subarray(index, index + 8192));
      const data = btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
      if (sourceURL().href !== url.href) throw new Error('打包期间页面已切换，请重新选择。');
      const query = new URLSearchParams({v: '1', source: url.href, sha256: hash, html_gzip: data});
      // Pin the receiver package; no web fallback URL or network listener.
      const intent = 'intent://import/v1?' + query + '#Intent;scheme=royalereplay;package=local.royale.replay.android;end';
      if (intent.length > MAX_URI) throw new Error('传输链接过长，请保存 HTML 后导入。');
      preparedURL = url.href; open.href = intent; open.style.display = 'block';
      note.textContent = '已准备本页 HTML。请在控制台核对并确认播放；没有自动开始调试。';
      open.click(); // Some browsers require a second, trusted tap; leave this link visible.
    } catch (error) { note.textContent = '未发送：' + error.message; }
    finally { pending = false; button.disabled = false; }
  });
})();
