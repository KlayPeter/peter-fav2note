// ==UserScript==
// @name         小红书收藏导出（fav2note）
// @namespace    fav2note.xhs
// @version      1.1.0
// @description  把收藏夹导出为 JSON，交给 fav2note 生成知识库。只读收藏列表，不点赞、不关注。
// @match        https://www.xiaohongshu.com/*
// @match        https://www.rednote.com/*
// @run-at       document-start
// @grant        GM_registerMenuCommand
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_deleteValue
// ==/UserScript==

(function () {
  "use strict";

  const STORE_KEY = "fav2note_notes";
  const state = {
    notes: GM_getValue(STORE_KEY, []),
    seen: new Set(),
    running: false,
    timer: null,
    lastHeight: 0,
    still: 0,
  };
  state.seen = new Set(state.notes.map((n) => n && n.note_id).filter(Boolean));

  const log = (...args) => console.log("%c[fav2note]", "color:#3b82f6;font-weight:600", ...args);

  /* ---------- 面板 ---------- */
  const panel = document.createElement("div");
  panel.style.cssText = [
    "position:fixed", "right:18px", "bottom:18px", "z-index:2147483647",
    "background:#0f172a", "color:#e2e8f0", "font:13px/1.6 system-ui,sans-serif",
    "padding:12px 14px", "border-radius:10px", "box-shadow:0 10px 30px rgba(0,0,0,.35)",
    "min-width:180px", "text-align:left",
  ].join(";");
  panel.innerHTML =
    '<div style="font-weight:600;margin-bottom:6px">收藏导出</div>' +
    '<div>已收集 <b id="fn-count" style="color:#60a5fa">0</b> 条</div>' +
    '<div id="fn-tip" style="opacity:.6;margin:4px 0 8px">未开始</div>' +
    '<button id="fn-run" style="all:unset;cursor:pointer;background:#3b82f6;color:#fff;padding:5px 10px;border-radius:6px;font-size:12px">开始滚动</button>' +
    '<button id="fn-save" style="all:unset;cursor:pointer;background:#1e293b;color:#e2e8f0;padding:5px 10px;border-radius:6px;font-size:12px;margin-left:6px">保存 JSON</button>';

  function mount() {
    if (!document.body || document.getElementById("fn-count")) return;
    document.body.appendChild(panel);
    document.getElementById("fn-count").textContent = String(state.notes.length);
    document.getElementById("fn-run").addEventListener("click", () => {
      state.running ? stop("已暂停") : start();
    });
    document.getElementById("fn-save").addEventListener("click", save);
  }
  setInterval(mount, 800);

  const tip = (text) => {
    const el = document.getElementById("fn-tip");
    if (el) el.textContent = text;
  };
  const refresh = () => {
    const el = document.getElementById("fn-count");
    if (el) el.textContent = String(state.notes.length);
  };

  /* ---------- 抓响应 ---------- */
  const isListApi = (url) => typeof url === "string" && url.includes("/api/sns/web/");

  function ingest(payload) {
    const list = payload && payload.data && payload.data.notes;
    if (!Array.isArray(list)) return;
    let added = 0;
    for (const note of list) {
      if (!note || !note.note_id || state.seen.has(note.note_id)) continue;
      state.seen.add(note.note_id);
      state.notes.push(note);
      added++;
    }
    if (added) {
      GM_setValue(STORE_KEY, state.notes);
      refresh();
      tip("已收集新的一页");
      log("新增", added, "累计", state.notes.length);
    }
  }

  const rawFetch = window.fetch;
  window.fetch = function (...args) {
    const promise = rawFetch.apply(this, args);
    try {
      const url = String((args[0] && args[0].url) || args[0] || "");
      if (isListApi(url)) {
        promise.then((res) => res.clone().json().then(ingest).catch(() => {})).catch(() => {});
      }
    } catch (e) {}
    return promise;
  };

  const rawOpen = XMLHttpRequest.prototype.open;
  const rawSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__fnUrl = url;
    return rawOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener("load", () => {
      try {
        if (isListApi(String(this.__fnUrl))) ingest(JSON.parse(this.responseText));
      } catch (e) {}
    });
    return rawSend.apply(this, args);
  };

  /* ---------- 滚动 ---------- */
  function start() {
    if (state.running) return;
    state.running = true;
    state.still = 0;
    state.lastHeight = 0;
    tip("滚动中，别切走标签页");
    document.getElementById("fn-run").textContent = "暂停";
    state.timer = setInterval(() => {
      window.scrollTo(0, document.body.scrollHeight);
      const height = document.body.scrollHeight;
      if (height === state.lastHeight) state.still++;
      else {
        state.still = 0;
        state.lastHeight = height;
      }
      if (state.still > 12) stop("到底了，点保存");
    }, 1500);
  }

  function stop(text) {
    state.running = false;
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
    tip(text || "已暂停");
    const btn = document.getElementById("fn-run");
    if (btn) btn.textContent = "开始滚动";
  }

  /* ---------- 导出 ---------- */
  function save() {
    const blob = new Blob([JSON.stringify({ data: { notes: state.notes } })], {
      type: "application/json",
    });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "fav_all.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 5000);
    tip(`已保存 ${state.notes.length} 条`);
  }

  try {
    GM_registerMenuCommand("开始/暂停滚动", () => (state.running ? stop("已暂停") : start()));
    GM_registerMenuCommand("保存 fav_all.json", save);
    GM_registerMenuCommand("清空已收集", () => {
      if (!confirm(`清空 ${state.notes.length} 条？`)) return;
      state.notes = [];
      state.seen.clear();
      GM_deleteValue(STORE_KEY);
      refresh();
      tip("已清空");
    });
  } catch (e) {
    log("菜单注册失败", e);
  }

  window.__fav2note = { state, start, stop, save };
  log("脚本已注入");
})();
