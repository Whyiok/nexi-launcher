"use strict";

/* ----------------------------------------------------------- network panel */

const net = {
  timer: null, results: [], blocked: [], status: "idle", checkedAt: "",
  lastSeq: 0,
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
  if (stick) el.scrollTop = el.scrollHeight;
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
  for (const item of results) {
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
    box.appendChild(row);
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

async function openNetwork() {
  stopNetworkTimer();
  await pollNetwork();
  if (net.results.length) renderNetTargets(net.results);
  startNetworkTimer();
}

async function runNetworkCheck() {
  const button = $("#btn-net-check");
  const sub = $("#net-sub");
  if (net.status === "running") return;
  net.status = "running";
  button.disabled = true;
  sub.textContent = "Checking all hosts…";
  try {
    const result = await call("network_check");
    if (result.error) {
      sub.textContent = "The check could not run";
      return;
    }
    net.results = result.results || [];
    net.blocked = result.blocked || [];
    net.checkedAt = `${result.time || ""}`.trim();
    renderNetTargets(net.results);
    const bad = net.results.filter((item) => !item.ok).length;
    sub.textContent = bad
      ? `${bad} of ${net.results.length} hosts unreachable`
      : `All ${net.results.length} hosts reachable`;
    await pollNetwork();
  } finally {
    net.status = "idle";
    button.disabled = false;
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
