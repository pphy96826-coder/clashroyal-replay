"use strict";
importScripts("page.js");

// The export runs here, not in the popup, so closing the popup does not stop it.
// Progress lives in chrome.storage.session under "job"; the popup only reads it.
const FOLDER = "RoyaleAPI回放";
const GAP_MS = 1500;          // pause between replay requests: RoyaleAPI refuses requests that come too often
let cancelled = false, active = false;

const sleep = ms => new Promise(r => setTimeout(r, ms));
// Long waits touch an extension API every few seconds so the service worker is not stopped as idle.
async function wait(ms) { for (let t = 0; t < ms; t += 5000) { await sleep(Math.min(5000, ms - t)); await chrome.storage.session.get("job"); } }

/** A file name from the opponent's name: keep the name, drop only what file systems refuse. */
function safeName(name, fallback) {
  let s = (name || "").normalize("NFC")
    .replace(/[\u0000-\u001f\u007f​-‏‪-‮⁦-⁩﻿]/g, "")
    .replace(/[\\/:*?"<>|~]/g, "_")
    .replace(/\s+/g, " ").trim()
    .replace(/^[.\s]+|[.\s]+$/g, "");
  if ([...s].length > 80) s = [...s].slice(0, 80).join("").trim();
  if (!s || /^(con|prn|aux|nul|com\d|lpt\d)$/i.test(s)) s = fallback;
  return s;
}

async function setJob(job) { await chrome.storage.session.set({job}); }

async function waitForDownload(id) {
  for (let i = 0; i < 40; i++) {
    const [d] = await chrome.downloads.search({id});
    if (d && (d.state === "complete" || d.state === "interrupted")) return d;
    await sleep(250);
  }
  const [d] = await chrome.downloads.search({id});
  return d;
}

async function runExport(tabId, pageUrl, items) {
  cancelled = false; active = true;
  const job = {tabId, pageUrl, running: true, started: Date.now(), total: items.length,
               results: items.map(it => ({tag: it.tag, opponent: it.opponentNames.join(" & "), state: "waiting"}))};
  await setJob(job);
  // No download bubble/shelf popping up for every file while the export runs.
  try { await chrome.downloads.setUiOptions({enabled: false}); } catch (_) {}
  try {
    for (let i = 0; i < items.length; i++) {
      if (cancelled) { job.results.slice(i).forEach(r => { r.state = "skipped"; r.error = "已取消"; }); break; }
      const item = items[i], res = job.results[i];
      res.state = "working"; await setJob(job);
      let got;
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const [frame] = await chrome.scripting.executeScript({target: {tabId}, world: "MAIN", func: exportPageReplay, args: [item]});
          got = frame && frame.result || {ok: false, error: "页面没有返回结果"};
        } catch (e) { got = {ok: false, error: "无法在页面中运行：" + e.message}; }
        // Too many requests: back off once, then give up on this one.
        if (!got.ok && got.status === 429 && attempt === 0) { res.error = "请求过快，等待 30 秒后重试"; await setJob(job); await wait(30000); continue; }
        break;
      }
      if (got.ok) {
        const base = safeName(item.opponentNames.join(" & "), item.tag);
        const url = "data:text/html;charset=utf-8," + encodeURIComponent(got.html);
        try {
          const id = await chrome.downloads.download({url, filename: FOLDER + "/" + base + ".html",
                                                      conflictAction: "uniquify", saveAs: false});
          const d = await waitForDownload(id);
          if (d && d.state === "interrupted") { res.state = "failed"; res.error = "保存失败：" + d.error; }
          else { res.state = "saved"; res.file = d && d.filename || base + ".html"; res.actions = got.actions; }
        } catch (e) { res.state = "failed"; res.error = "保存失败：" + e.message; }
      } else {
        res.state = got.notFound ? "missing" : "failed"; res.error = got.error;
        // Cloudflare wants a new check: stop, never try to pass it. The user reloads the page and exports the rest.
        if (got.needsLogin) {  // every other replay would fail the same way
          res.error = "RoyaleAPI 要求登录才能看回放，已停止。请在这个浏览器里登录 RoyaleAPI（页面右上角 Login）后再导出。";
          job.results.slice(i + 1).forEach(r => { r.state = "skipped"; r.error = "未登录，已停止"; });
          await setJob(job);
          break;
        }
        if (got.status === 403 || got.cloudflare) {
          res.error = (got.error || "") + "；Cloudflare 拒绝了请求，已停止。请刷新页面，通过验证后再导出剩下的。";
          job.results.slice(i + 1).forEach(r => { r.state = "skipped"; r.error = "因 Cloudflare 停止"; });
          await setJob(job);
          break;
        }
      }
      await setJob(job);
      if (i + 1 < items.length) await sleep(GAP_MS);
    }
  } finally {
    try { await chrome.downloads.setUiOptions({enabled: true}); } catch (_) {}
    job.running = false; job.finished = Date.now();
    await setJob(job);
    active = false;
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg && msg.type === "export") {
    chrome.storage.session.get("job").then(({job}) => {
      if (job && job.running) { reply({ok: false, error: "已有导出在进行"}); return; }
      runExport(msg.tabId, msg.pageUrl, msg.items);
      reply({ok: true});
    });
    return true;
  }
  if (msg && msg.type === "cancel") { cancelled = true; reply({ok: true}); }
});

// A service worker restarted mid-export cannot resume it; do not leave a "running" job behind.
chrome.runtime.onStartup.addListener(() => chrome.storage.session.remove("job"));
chrome.storage.session.get("job").then(({job}) => {
  if (job && job.running && !active) {
    job.running = false;
    job.results.forEach(r => { if (r.state === "waiting" || r.state === "working") { r.state = "skipped"; r.error = "扩展后台被浏览器中断，请重新导出"; } });
    chrome.storage.session.set({job});
  }
});
