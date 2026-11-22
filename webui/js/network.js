"use strict";

/* ----------------------------------------------------------- network panel */

const net = {
  timer: null, results: [], blocked: [], status: "idle", checkedAt: "",
  lastSeq: 0, groups: [], groupState: {},
};

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch (err) {
    return String(url || "");
  }
}

function renderNetConsole(events) {
  const el = $("#net-console");
  if (!el) return;
  const lastSeq = events.length ? (events[events.length - 1].seq || 0) : 0;
  if (lastSeq === net.lastSeq && el.children.length) return;
  net.lastSeq = lastSeq;
  const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
  const kept = el.scrollTop;
  el.replaceChildren();
  if (!events.length) {
    el.appendChild(elem("span", "log-line line-dim",
      "No network events yet. Downloads and their failures show up here.\n"));
  } else {
    for (const item of events) {
      const cls = item.level === "error" ? "line-error"
        : item.level === "warn" ? "line-warn" : "";
      el.appendChild(elem("span", "log-line " + cls,
        `[${item.time}] ${item.message}\n`));
    }
  }
  // Rebuilding the list resets scrollTop; keep the reader's position unless
  // they were already following the tail.
  el.scrollTop = stick ? el.scrollHeight : kept;
}

function netTargetRow(item) {
  const row = elem("div", "net-target " + (item.ok ? "ok" : "bad"));
  row.appendChild(elem("span", "net-dot"));
  const meta = elem("div", "net-meta");
  meta.appendChild(elem("span", "net-name", item.label));
  meta.appendChild(elem("span", "net-detail",
    item.ok ? hostOf(item.url) : (item.error || "unreachable")));
  row.appendChild(meta);
  row.appendChild(elem("span", "net-ms",
    item.ok ? `${item.ms} ms` : "fail"));
  row.title = item.url + (item.note ? ` — ${item.note}` : "");
  return row;
}

function renderNetTargets(results) {
  const box = $("#net-targets");
  if (!box) return;
  box.replaceChildren();
  if (!results.length) {
    box.appendChild(elem("p", "hint net-empty",
      "Run the check to see which game hosts this network can reach."));
    return;
  }
  const buckets = new Map();
  for (const item of results) {
    const id = item.group || "other";
    if (!buckets.has(id)) buckets.set(id, []);
    buckets.get(id).push(item);
  }
  const groups = (net.groups || []).filter((group) => buckets.has(group.id));
  const known = new Set(groups.map((group) => group.id));
  for (const id of buckets.keys()) {
    if (!known.has(id)) groups.push({ id, title: id });
  }
  for (const group of groups) {
    const items = buckets.get(group.id) || [];
    const bad = items.filter((item) => !item.ok).length;
    const details = elem("details", "net-group");
    const manual = Object.prototype.hasOwnProperty.call(
      net.groupState, group.id);
    details.open = manual ? net.groupState[group.id] : bad > 0;
    details.dataset.autoOpen = details.open ? "1" : "0";
    details.addEventListener("toggle", () => {
      const auto = details.dataset.autoOpen;
      if (auto !== undefined && auto === (details.open ? "1" : "0")) {
        delete details.dataset.autoOpen;
        return;
      }
      net.groupState[group.id] = details.open;
    });
    const head = elem("summary", "net-group-head");
    head.appendChild(elem("span", "net-group-dot " + (bad ? "bad" : "ok")));
    head.appendChild(elem("span", "net-group-title", group.title));
    head.appendChild(elem("span", "net-group-count",
      `${items.length - bad}/${items.length}`));
    details.appendChild(head);
    const rows = elem("div", "net-rows");
    for (const item of items) rows.appendChild(netTargetRow(item));
    details.appendChild(rows);
    box.appendChild(details);
  }
}

async function pollNetwork() {
  if (screen !== "settings") {
    stopNetworkTimer();
    return;
  }
  const result = await call("network_log");
  if (!result.error) renderNetConsole(result.events || []);
}

function startNetworkTimer() {
  stopNetworkTimer();
  net.timer = setInterval(pollNetwork, 1500);
}

function stopNetworkTimer() {
  if (net.timer) {
    clearInterval(net.timer);
    net.timer = null;
  }
}

function renderNetChecking() {
  const box = $("#net-targets");
  if (!box) return;
  box.replaceChildren();
  for (let i = 0; i < 8; i += 1) {
    const row = elem("div", "net-target waiting net-skeleton");
    row.appendChild(elem("span", "net-dot"));
    const meta = elem("div", "net-meta");
    meta.appendChild(elem("span", "net-skeleton-line wide"));
    meta.appendChild(elem("span", "net-skeleton-line"));
    row.appendChild(meta);
    box.appendChild(row);
  }
}

async function openNetwork() {
  stopNetworkTimer();
  await pollNetwork();
  if (net.results.length) renderNetTargets(net.results);
  if (net.status === "running") {
    const sub = $("#net-sub");
    if (sub) {
      sub.textContent = "Checking all hosts…";
      sub.classList.add("busy");
    }
    renderNetChecking();
  } else if (!net.results.length) {
    runNetworkCheck();
  }
  startNetworkTimer();
}

let netAutoRan = false;

/* Probe the hosts once per launch so the Network tab opens with data. */
function autoNetworkCheck() {
  if (netAutoRan) return;
  netAutoRan = true;
  setTimeout(() => {
    if (net.status !== "running" && !net.results.length) runNetworkCheck();
  }, 1500);
}

function renderNetworkSettings() {
  const proxy = $("#proxy-url");
  if (proxy && document.activeElement !== proxy) proxy.value = S.proxy || "";
  const dns = $("#dns-servers");
  if (dns && document.activeElement !== dns) dns.value = S.dns || "";
  $$("#dns-presets [data-dns-preset]").forEach((button) => {
    button.classList.toggle(
      "on", (button.dataset.dnsPreset || "") === (S.dns || ""));
  });
  const key = $("#curseforge-key");
  if (key && document.activeElement !== key) {
    key.placeholder = S.curseforge_key_set
      ? "Saved — paste a new key to replace"
      : "Paste a personal API key";
  }
}

async function saveProxySetting() {
  const button = $("#btn-save-proxy");
  const value = $("#proxy-url").value.trim();
  if (button) button.disabled = true;
  try {
    const result = await call("set_proxy", value);
    if (!result || !result.ok) {
      setStatus((result && result.error) || "Could not save the proxy.", true);
      return;
    }
    if (result.state) applyState(result.state);
    const input = $("#proxy-url");
    if (input) input.value = result.proxy || "";
    setStatus(result.proxy ? "Proxy saved." : "Proxy disabled.");
  } finally {
    if (button) button.disabled = false;
  }
}

async function saveDnsSetting() {
  const button = $("#btn-save-dns");
  const value = $("#dns-servers").value.trim();
  if (button) button.disabled = true;
  try {
    const result = await call("set_dns", value);
    if (!result || !result.ok) {
      setStatus((result && result.error)
        || "Could not save the DNS servers.", true);
      return;
    }
    if (result.state) applyState(result.state);
    const input = $("#dns-servers");
    if (input) input.value = result.dns || "";
    setStatus(result.dns ? "DNS servers saved." : "System DNS restored.");
  } finally {
    if (button) button.disabled = false;
  }
}

async function saveCurseforgeKey() {
  const input = $("#curseforge-key");
  const button = $("#btn-save-curseforge-key");
  if (!input) return;
  const value = input.value.trim();
  if (button) button.disabled = true;
  try {
    const result = await call("set_curseforge_key", value);
    if (!result || !result.ok) {
      setStatus((result && result.error)
        || "Could not save the CurseForge API key.", true);
      return;
    }
    if (result.state) applyState(result.state);
    input.value = "";
    renderNetworkSettings();
    syncKindUi();
    setStatus(result.set
      ? "CurseForge API key saved."
      : "CurseForge API key cleared.");
  } finally {
    if (button) button.disabled = false;
  }
}

function bindNetworkSettings() {
  const bind = (inputId, buttonId, handler) => {
    const button = $("#" + buttonId);
    if (button) button.addEventListener("click", handler);
    const input = $("#" + inputId);
    if (input) input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      handler();
    });
  };
  bind("proxy-url", "btn-save-proxy", saveProxySetting);
  bind("dns-servers", "btn-save-dns", saveDnsSetting);
  bind("curseforge-key", "btn-save-curseforge-key", saveCurseforgeKey);
  const keyPage = $("#btn-curseforge-key-page");
  if (keyPage) keyPage.addEventListener("click", () => {
    call("curseforge_key_page");
  });
  $$("#dns-presets [data-dns-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = $("#dns-servers");
      if (input) input.value = button.dataset.dnsPreset || "";
      saveDnsSetting();
    });
  });
}

async function runNetworkCheck() {
  const button = $("#btn-net-check");
  const sub = $("#net-sub");
  if (net.status === "running") return;
  net.status = "running";
  if (button) button.disabled = true;
  if (sub) {
    sub.textContent = "Checking all hosts…";
    sub.classList.add("busy");
  }
  renderNetChecking();
  try {
    const result = await call("network_check");
    if (result.error) {
      if (sub) sub.textContent = "The check could not run";
      renderNetTargets(net.results);
      return;
    }
    net.results = result.results || [];
    net.blocked = result.blocked || [];
    net.groups = result.groups || [];
    net.checkedAt = `${result.time || ""}`.trim();
    renderNetTargets(net.results);
    const bad = net.results.filter((item) => !item.ok).length;
    if (sub) {
      sub.textContent = bad
        ? `${bad} of ${net.results.length} hosts unreachable`
        : `All ${net.results.length} hosts reachable`;
    }
    await pollNetwork();
  } finally {
    net.status = "idle";
    if (button) button.disabled = false;
    if (sub) sub.classList.remove("busy");
  }
}

function netReport() {
  const lines = ["Nexi Launcher — network report"];
  lines.push(`Check: ${net.checkedAt ? `at ${net.checkedAt}` : "not run"}`);
  for (const item of net.results) {
    const state = item.ok
      ? `OK ${item.ms} ms${item.note ? ` (${item.note})` : ""}`
      : `FAIL ${item.error || "unreachable"}`;
    lines.push(`${item.label} — ${hostOf(item.url)}: ${state}`);
  }
  if (net.blocked.length) {
    lines.push(`Skipped this session: ${net.blocked.join(", ")}`);
  }
  const el = $("#net-console");
  if (el) {
    lines.push("", "Events:");
    for (const span of el.querySelectorAll(".log-line")) {
      lines.push(span.textContent.replace(/\r?\n$/, ""));
    }
  }
  return lines.join("\r\n");
}

function copyPlainText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text) {
  const area = elem("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  try {
    document.execCommand("copy");
  } catch (err) {
    /* clipboard is unavailable; the report stays visible in the log */
  }
  area.remove();
}

function copyNetReport() {
  copyPlainText(netReport());
  setStatus("Network report copied.");
}

async function openGameLogs() {
  stopGameLogsTimer();
  clearLogsView(gameLogs);
  const result = await call("game_logs_open");
  const sub = $("#game-logs-sub");
  sub.dataset.path = result.path || "";
  sub.textContent = result.path || "logs/latest.log";
  sub.title = result.path || "";
  if (!result.exists) {
    appendLines(["Waiting for logs/latest.log — the file appears when the "
                 + "game starts."], "line-dim", gameLogs);
  } else {
    appendText(result.text, undefined, gameLogs);
  }
  if (gameLogs.visible()) startGameLogsTimer();
}

function startGameLogsTimer() {
  stopGameLogsTimer();
  gameLogs.timer = setInterval(pollGameLogs, 700);
}

function stopGameLogsTimer() {
  if (gameLogs.timer) {
    clearInterval(gameLogs.timer);
    gameLogs.timer = null;
  }
}

async function pollGameLogs() {
  if (!gameLogs.visible()) {
    stopGameLogsTimer();
    return;
  }
  const result = await call("game_logs_read");
  if (result.reset) clearLogsView(gameLogs);
  if (result.text) appendText(result.text, undefined, gameLogs);
}
