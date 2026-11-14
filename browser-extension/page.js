"use strict";
// Functions run inside the RoyaleAPI page via chrome.scripting.executeScript({func}).
// Each one must be self-contained: no outer variables, helpers defined inside.

/** Every battle row on the page that has a Replay button -> plain objects for the popup. */
function listPageReplays() {
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const tags = s => (s || "").split(",").map(t => t.trim().replace(/^#/, "").toUpperCase()).filter(Boolean);
  const nameOf = (row, tag) => {
    const link = [...row.querySelectorAll("a.player_name_header")]
      .find(a => (a.getAttribute("href") || "").toUpperCase().startsWith("/PLAYER/" + tag + "/") ||
                 (a.getAttribute("href") || "").toUpperCase() === "/PLAYER/" + tag);
    if (!link) return "";
    // Only the link's own text: badges such as "Supercell Creator" sit in child elements.
    const own = [...link.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join(" ");
    return clean(own) || clean(link.textContent);
  };
  const seen = new Set(), out = [];
  for (const row of document.querySelectorAll("div.battle[data-timestamp]")) {
    const b = row.querySelector("button.replay_button[data-replay]");
    if (!b) continue;
    const tag = b.dataset.replay.replace(/^#/, "").toUpperCase();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    const team = tags(b.dataset.teamTags), opponent = tags(b.dataset.opponentTags);
    out.push({
      tag,
      timestamp: Number(row.dataset.timestamp) || null,
      mode: clean(row.querySelector(".game_mode_header")?.textContent),
      result: clean(row.querySelector(".win_loss .label")?.textContent),
      team, opponent,
      teamNames: team.map(t => nameOf(row, t) || t),
      opponentNames: opponent.map(t => nameOf(row, t) || t),
      teamCrowns: b.dataset.teamCrowns ?? "", opponentCrowns: b.dataset.opponentCrowns ?? "",
      draft: b.dataset.draft ?? "",
      deckGrids: row.querySelectorAll('[id^="deck_"]').length
    });
  }
  return {url: location.href, title: document.title, replays: out};
}

/** Fetch one replay's action markers and build the export file (battle row + fragment). */
async function exportPageReplay(item) {
  const row = [...document.querySelectorAll("div.battle[data-timestamp]")].find(r =>
    [...r.querySelectorAll("button.replay_button[data-replay]")]
      .some(b => b.dataset.replay.replace(/^#/, "").toUpperCase() === item.tag));
  if (!row) return {ok: false, error: "页面上找不到这一场（页面已切换或刷新？）"};
  const b = row.querySelector("button.replay_button[data-replay]");
  const query = new URLSearchParams({
    tag: b.dataset.replay, team_tags: b.dataset.teamTags || "", opponent_tags: b.dataset.opponentTags || "",
    team_crowns: b.dataset.teamCrowns || "0", opponent_crowns: b.dataset.opponentCrowns || "0"
  });
  const request = "/data/replay?" + query + "&" + new URLSearchParams({referrer_path: location.href});
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 45000);
  let status = 0, body = "";
  try {
    const r = await fetch(request, {credentials: "include", signal: controller.signal,
                                    headers: {"X-Requested-With": "XMLHttpRequest"}});
    status = r.status; body = await r.text();
  } catch (e) {
    return {ok: false, status: 0, error: "请求失败：" + (e.name === "AbortError" ? "45 秒超时" : e.message)};
  } finally { clearTimeout(timer); }
  if (status !== 200) return {ok: false, status, error: "RoyaleAPI 返回 HTTP " + status};
  let data;
  try { data = JSON.parse(body); } catch (_) {
    return {ok: false, status, error: "回答不是 JSON（可能是 Cloudflare 验证页）", cloudflare: /<title>Just a moment/i.test(body)};
  }
  const fragment = data && data.html || "";
  if (/Replay not found/i.test(fragment) || /Replay not found/i.test(body)) return {ok: false, status, notFound: true, error: "RoyaleAPI：Replay not found"};
  if (/requires login/i.test(fragment) || /href="\\?\/login\//.test(fragment))
    return {ok: false, status, needsLogin: true, error: "RoyaleAPI 要求登录才能看回放"};
  if (!data.success || !/class="battle_replay/.test(fragment)) return {ok: false, status, error: "回答里没有回放数据"};
  const answeredTag = (fragment.match(/class="battle_replay[^"]*"[^>]*\bdata-tag="#?([0-9A-Z]+)"/i) ||
                       fragment.match(/\bdata-tag="#?([0-9A-Z]+)"/i) || [])[1];
  if (answeredTag && answeredTag.toUpperCase() !== item.tag) return {ok: false, status, error: "回答的回放标签不符：" + answeredTag};
  const actions = (fragment.match(/\bdata-x=/g) || []).length;
  if (actions < 1) return {ok: false, status, error: "回放里没有操作标记"};

  // The row's own content (mode, decks with levels, tower HP, names), without any replay already
  // loaded into it by hand: that would duplicate the actions.
  const clone = row.cloneNode(true);
  clone.querySelectorAll("div.battle_replay").forEach(e => e.remove());
  const exported = new Date().toISOString();
  const meta = {
    schema: "royaleapi-replay-export.v1", exported_at: exported, page_url: location.href,
    request: new URL(request, location.origin).href, replay_tag: item.tag,
    team_tags: item.team, opponent_tags: item.opponent, team_names: item.teamNames, opponent_names: item.opponentNames,
    team_crowns: b.dataset.teamCrowns ?? null, opponent_crowns: b.dataset.opponentCrowns ?? null,
    battle_timestamp: Number(row.dataset.timestamp) || null, game_mode: item.mode, action_markers: actions,
    deck_grids: clone.querySelectorAll('[id^="deck_"]').length
  };
  const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const html = "<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\">\n" +
    "<base href=\"https://royaleapi.com/\">\n" +
    "<title>" + esc(item.teamNames.join(" & ") + " vs " + item.opponentNames.join(" & ") + " · " + item.tag) + "</title>\n" +
    "<script type=\"application/json\" id=\"royaleapi-replay-export\">" + JSON.stringify(meta).replace(/</g, "\\u003c") + "</script>\n" +
    "</head><body>\n" +
    "<!-- RoyaleAPI /data/replay fragment + its battle row, " + exported + " -->\n" +
    "<a href=\"/replay?" + esc(query.toString()) + "\"></a>\n" +
    clone.outerHTML + "\n" + fragment + "\n</body></html>\n";
  return {ok: true, status, html, actions, bytes: html.length};
}
