"use strict";
const host = "local.royale.htmlreplay";
const status = document.getElementById("status");
const retry = document.getElementById("retry");
let working = false;
const show = text => { status.textContent = text; };
function validReplay(value) {
  const u = new URL(value);
  return u.protocol === "https:" && ["royaleapi.com", "www.royaleapi.com"].includes(u.hostname) &&
    !u.username && !u.password && (!u.port || u.port === "443") && u.pathname.replace(/\/$/, "") === "/replay" &&
    u.searchParams.getAll("tag").length === 1 && /^[A-Z0-9]{6,32}$/.test(u.searchParams.get("tag"));
}
async function native(message) {
  let reply;
  try {
    reply = await chrome.runtime.sendNativeMessage(host, message);
  } catch (e) {
    throw new Error("本地桥接未连接：" + e.message + "\n请先安装本地桥接并打开官服 HTML 回放控制台。");
  }
  if (!reply || !reply.ok) throw new Error(reply?.error || "本地桥接没有返回成功结果");
  return reply;
}
async function capture() {
  if (working) return;
  working = true; retry.disabled = true;
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab?.id || !tab.url || !validReplay(tab.url))
      throw new Error("请先在本浏览器完成登录，并打开一场 /replay?tag=… 回放详情页。玩家列表、Google 登录页不会被读取。");
    show("正在读取本页已加载的回放 HTML…");
    const results = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: () => ({
      url: location.href,
      html: "<!DOCTYPE html>\n" + document.documentElement.outerHTML,
      markers: document.querySelectorAll("[data-t][data-s][data-c][data-x][data-y]").length
    })});
    const page = results[0]?.result;
    if (!page || !validReplay(page.url) || page.url !== tab.url || !page.markers)
      throw new Error("页面尚无完整回放数据。请先完成登录/网站验证，等待回放详情加载。没有读取账号信息。");
    if (new TextEncoder().encode(page.html).length > 25 * 1024 * 1024) throw new Error("HTML 超过25MB，未发送。");
    const result = await native({command: "capture-play", url: page.url, html: page.html});
    show("HTML 已传到本机，正在等待控制台校验。\n任务：" + result.job_id + "\n这不代表对局已经开始播放。" + (result.launch_warning ? "\n" + result.launch_warning : ""));
    for (let count = 0; count < 90; count++) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      const current = await native({command: "status", job_id: result.job_id});
      show(current.message || current.state || "等待控制台…");
      if (["playing", "complete", "failed", "cancelled", "needs_review", "missing"].includes(current.state)) break;
    }
  } catch (e) { show("未启动播放：\n" + e.message); }
  finally { working = false; retry.disabled = false; }
}
retry.addEventListener("click", capture);
document.getElementById("console").addEventListener("click", async () => {
  try { await native({command: "launch"}); } catch (e) { show(e.message); }
});
capture();
