"use strict";

/* ------------------------------------------------------------------ logs */

function canvasText(text) {
  return elem("span", "log-line", text + "\n");
}

function lineClass(line) {
  if (/\/ERROR\]|\/FATAL\]/.test(line) || /^(Error:|Exception)/.test(line)) return "line-error";
  if (/\/WARN\]/.test(line) || /^WARNING/.test(line)) return "line-warn";
  return "";
}

function appendText(text, cls, state = logs) {
  if (!text) return;
  state.pending += text;
  if (!state.pending.includes("\n")) return;
  const parts = state.pending.split("\n");
  state.pending = parts.pop();
  appendLines(parts, cls, state);
}

function appendLines(lines, cls, state = logs) {
  if (!lines.length) return;
  const consoleEl = $(state.el);
  if (!consoleEl) return;
  const fragment = document.createDocumentFragment();
  for (const line of lines) {
    const clean = line.replace(/\r$/, "");
    const span = elem("span", "log-line " + (cls !== undefined ? cls : lineClass(clean)), clean + "\n");
    state.buffer.push(span);
    fragment.appendChild(span);
  }
  consoleEl.appendChild(fragment);
  trimBuffer(state, consoleEl);
  if (state.visible() && state.stick) {
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
}

function trimBuffer(state, consoleEl) {
  while (state.buffer.length > 2000) {
    const old = state.buffer.shift();
    if (old && old.parentNode) old.parentNode.removeChild(old);
  }
}

function clearLogsView(state = logs) {
  state.pending = "";
  state.buffer.length = 0;
  const consoleEl = $(state.el);
  if (consoleEl) consoleEl.replaceChildren();
}

async function openLogs() {
  stopLogsTimer();
  clearLogsView(logs);
  logs.stick = true;
  const result = await call("logs_open");
  const sub = $("#logs-sub");
  sub.dataset.path = result.path || "";
  sub.textContent = result.path || "logs\\launcher.log";
  sub.title = result.path || "";
  if (!result.exists) {
    appendLines(["The launcher log is empty for now."], "line-dim", logs);
  } else {
    appendText(result.text, undefined, logs);
  }
  if (logs.visible()) startLogsTimer();
}

function startLogsTimer() {
  stopLogsTimer();
  logs.timer = setInterval(pollLogs, 700);
}

function stopLogsTimer() {
  if (logs.timer) {
    clearInterval(logs.timer);
    logs.timer = null;
  }
}

async function pollLogs() {
  if (!logs.visible()) {
    stopLogsTimer();
    return;
  }
  const result = await call("logs_read");
  if (result.reset) clearLogsView(logs);
  if (result.text) appendText(result.text, undefined, logs);
}
