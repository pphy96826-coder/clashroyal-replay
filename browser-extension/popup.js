"use strict";
const $ = id => document.getElementById(id);
const list = $("list"), status = $("status"), exportBtn = $("export"), cancelBtn = $("cancel");
let tabId = null, pageUrl = "", replays = [], job = null;
// Show an export's results only on the page it was started from.
const mine = () => !!(job && job.tabId === tabId && job.pageUrl === pageUrl);

const STATE_TEXT = {waiting: "排队", working: "导出中…", saved: "✓ 已保存", failed: "✗ 失败", missing: "无回放", skipped: "未导出"};

function validPage(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && ["royaleapi.com", "www.royaleapi.com"].includes(u.hostname);
  } catch (_) { return false; }
}

function when(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), p = n => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

function render() {
  list.replaceChildren();
  const byTag = new Map((mine() ? job.results : []).map(r => [r.tag, r]));
  for (const r of replays) {
    const row = el("label", "row");
    const box = el("input"); box.type = "checkbox"; box.checked = r.checked; box.disabled = !!(job && job.running);
    box.addEventListener("change", () => { r.checked = box.checked; updateCount(); });
    const mid = el("div");
    mid.append(el("div", "opp", r.opponentNames.join(" & ") || r.tag));
    const team = r.teamNames.join(" & ") || "?";
    const bits = [r.teamCrowns !== "" ? `${team} ${r.teamCrowns}–${r.opponentCrowns} 对手` : "对战 " + team, r.mode, when(r.timestamp)];
    if (r.deckGrids > 2) bits.push(`${r.deckGrids / 2} 局连续（决斗）`);
    mid.append(el("div", "sub", bits.filter(Boolean).join(" · ")));
    const res = byTag.get(r.tag);
    const st = el("div", "state " + (res ? res.state : ""), res ? STATE_TEXT[res.state] || res.state : "");
    row.append(box, mid, st);
    if (res && res.error && res.state !== "saved") row.append(el("div", "err", res.error));
    if (res && res.state === "saved" && res.file) row.append(el("div", "sub file", res.file.split(/[\\/]/).slice(-2).join("/") + `（${res.actions} 个操作）`));
    list.append(row);
  }
  updateCount();
}

function updateCount() {
  const n = replays.filter(r => r.checked).length;
  $("count").textContent = replays.length ? `已选 ${n} / ${replays.length} 场` : "";
  const running = !!(job && job.running);
  exportBtn.disabled = running || !n;
  exportBtn.textContent = running ? "导出中…" : `导出所选（${n}）`;
  cancelBtn.hidden = !running;
  $("all").disabled = $("none").disabled = $("reload").disabled = running;
  if (mine()) {
    const c = s => job.results.filter(r => r.state === s).length;
    const done = job.results.filter(r => !["waiting", "working"].includes(r.state)).length;
    status.textContent = (running ? `正在导出 ${done} / ${job.total}` : `导出结束：`) +
      `　已保存 ${c("saved")}` + (c("missing") ? `，无回放 ${c("missing")}` : "") +
      (c("failed") ? `，失败 ${c("failed")}` : "") + (c("skipped") ? `，未导出 ${c("skipped")}` : "");
  }
}

async function load() {
  status.textContent = "";
  const want = Number(new URLSearchParams(location.search).get("tab"));  // only for testing: popup opened as a page
  const tab = want ? await chrome.tabs.get(want) : (await chrome.tabs.query({active: true, currentWindow: true}))[0];
  tabId = tab && tab.id;
  if (!tab || !validPage(tab.url || "")) {
    $("page").textContent = "当前标签页不是 RoyaleAPI 页面。";
    status.textContent = "请打开 royaleapi.com 上有对战列表的页面（玩家的 Battles、卡组胜利榜等），再点扩展图标。";
    replays = []; render(); return;
  }
  $("page").textContent = tab.title || tab.url;
  let page;
  try {
    const [frame] = await chrome.scripting.executeScript({target: {tabId}, func: listPageReplays});
    page = frame && frame.result;
  } catch (e) { status.textContent = "无法读取页面：" + e.message; return; }
  if (!page) { status.textContent = "页面没有返回结果。"; return; }
  pageUrl = page.url;
  const old = new Map(replays.map(r => [r.tag, r.checked]));
  replays = page.replays.map(r => ({...r, checked: old.has(r.tag) ? old.get(r.tag) : true}));
  if (!replays.length)
    status.textContent = /Just a moment|Attention Required/i.test(page.title)
      ? "页面还在 Cloudflare 验证中，请先在页面上完成验证。"
      : "本页没有带 Replay 按钮的对战。向下滚动加载更多对战后可点“刷新列表”。";
  render();
}

$("all").addEventListener("click", () => { replays.forEach(r => r.checked = true); render(); });
$("none").addEventListener("click", () => { replays.forEach(r => r.checked = false); render(); });
$("reload").addEventListener("click", load);
cancelBtn.addEventListener("click", () => chrome.runtime.sendMessage({type: "cancel"}));
exportBtn.addEventListener("click", async () => {
  const items = replays.filter(r => r.checked).map(({checked, ...r}) => r);
  if (!items.length) return;
  const reply = await chrome.runtime.sendMessage({type: "export", tabId, pageUrl, items});
  if (!reply || !reply.ok) status.textContent = (reply && reply.error) || "后台没有响应";
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "session" && changes.job) { job = changes.job.newValue || null; render(); }
});

(async () => {
  ({job} = await chrome.storage.session.get("job"));
  await load();
})();
