"use strict";

/* ------------------------------------------------------- zapret (DPI bypass) */

const zap = {
  status: null, loading: false, confirm: false, confirmTimer: null,
  presetKey: "", error: "", suggest: [], pendingExtra: "",
};

const zapretLog = {
  pending: "", buffer: [], timer: null, stick: true,
  el: "#zapret-console",
  visible: () => screen === "settings" && settingsTab === "bypass",
};

function zapretActive(status = zap.status) {
  return !!status && (!!status.running || status.service === "running");
}

function zapretVersionLabel(status) {
  const version = String((status && status.version) || "").trim();
  return version ? `zapret ${version}` : "Zapret";
}

function setZapretStatus(text, error = false) {
  const node = $("#zapret-status");
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("error", !!error);
  if (text) appendZapretLog(text);
}

function appendZapretLog(line) {
  if (!line) return;
  appendText(String(line) + "\n", undefined, zapretLog);
}

function clearZapretLog() {
  clearLogsView(zapretLog);
}

function setZapretProgress(done, total) {
  const bar = $("#zapret-progress");
  if (!bar) return;
  if (!total) {
    bar.style.width = "";
    bar.classList.add("indeterminate");
    return;
  }
  bar.classList.remove("indeterminate");
  bar.style.width = `${Math.round((done / total) * 100)}%`;
}

function resetZapretConfirm() {
  zap.confirm = false;
  if (zap.confirmTimer) {
    window.clearTimeout(zap.confirmTimer);
    zap.confirmTimer = null;
  }
  const button = $("#btn-zapret-apply");
  if (button) button.classList.remove("confirm");
  renderZapret();
}

function fillZapretPresets(status) {
  const select = $("#zapret-preset");
  if (!select) return;
  const presets = (status && status.presets) || [];
  const key = presets.join("|");
  if (key !== zap.presetKey) {
    zap.presetKey = key;
    select.replaceChildren();
    for (const name of presets) {
      const option = elem("option", "", name.replace(/\.bat$/i, ""));
      option.value = name;
      select.appendChild(option);
    }
  }
  const wanted = (status && status.preset) || "";
  if (wanted && select.value !== wanted) select.value = wanted;
}

function renderZapret() {
  const sub = $("#zapret-sub");
  const hint = $("#zapret-hint");
  const path = $("#zapret-path");
  const apply = $("#btn-zapret-apply");
  const stop = $("#btn-zapret-stop");
  const cancel = $("#btn-zapret-cancel");
  const pick = $("#btn-zapret-folder");
  const open = $("#btn-zapret-open");
  const presetRow = $("#zapret-preset-row");
  const auto = $("#zapret-auto");
  const suggestRow = $("#zapret-suggest-row");
  const suggestText = $("#zapret-suggest-text");
  const suggestBtn = $("#btn-zapret-suggest");
  if (!sub || !hint || !path || !apply || !stop || !cancel) return;

  const status = zap.status;
  const busy = S.busy === "zapret";
  const found = !!(status && status.found && status.root);
  const rootless = !!(status && status.found && !status.root);
  const active = found && zapretActive(status);

  if (auto) {
    auto.checked = !!(status && status.auto);
    auto.disabled = !status || busy;
  }
  const suggested = (zap.suggest || []).filter(Boolean);
  if (suggestRow) {
    suggestRow.classList.toggle("hidden", !suggested.length);
  }
  if (suggestText) {
    suggestText.textContent = suggested.length
      ? `${suggested.join(", ")} did not load. Add `
        + `${suggested.length > 1 ? "these addresses" : "this address"} `
        + "to the bypass list and turn the bypass on?"
      : "";
  }
  if (suggestBtn) {
    suggestBtn.disabled = busy;
    gateControl(suggestBtn, !found ? "Install zapret first." : "");
  }

  if (!status) {
    sub.textContent = "Checking…";
    hint.textContent = "Checking for an installed copy…";
    hint.classList.remove("error");
    path.textContent = "—";
    path.removeAttribute("title");
    apply.textContent = "Enable bypass";
    apply.disabled = true;
    stop.classList.add("hidden");
    cancel.classList.add("hidden");
    pick.disabled = true;
    open.disabled = true;
    presetRow.classList.add("hidden");
    return;
  }

  const service = status.service || "absent";
  const strategy = status.strategy || (status.preset || "").replace(/\.bat$/i, "");
  const pieces = [];
  if (!found) pieces.push("Not installed");
  else {
    pieces.push(zapretVersionLabel(status));
    if (service === "running") pieces.push("service running");
    else if (service === "stopped") pieces.push("service stopped");
    else if (status.running) pieces.push("running");
    else pieces.push("not running");
    if (strategy) pieces.push(strategy);
  }
  sub.textContent = pieces.join(" · ");

  if (!found) {
    hint.textContent = status.service === "running"
      ? "The zapret service is running, but its folder could not be read. "
        + "Choose the folder manually."
      : "zapret was not found. Downloading puts it in the launcher's data "
        + "folder and configures the general list automatically.";
    hint.classList.toggle("error", false);
    path.textContent = "not found";
    path.removeAttribute("title");
  } else {
    const missing = (status.missing || []).length;
    const listName = (status.list_path || "").split(/[\\/]/).pop() || "list";
    hint.textContent = missing
      ? `${missing} launcher address(es) missing from ${listName}.`
      : `All launcher addresses are already in ${listName}.`;
    hint.classList.toggle("error", false);
    path.textContent = status.root;
    path.title = status.root;
  }

  apply.textContent = rootless
    ? "Enable bypass"
    : !found
      ? (zap.confirm ? "Confirm download" : "Download & enable")
      : active ? "Apply domains again" : "Enable bypass";
  apply.classList.toggle("confirm", !!zap.confirm);
  apply.disabled = busy;
  gateControl(apply, rootless
    ? "zapret needs administrator rights — restart the launcher as administrator."
    : "");

  stop.classList.toggle("hidden", !active || busy);
  stop.disabled = busy;
  cancel.classList.toggle("hidden", !busy);
  cancel.disabled = false;

  pick.disabled = busy;
  open.disabled = busy;
  gateControl(open, !found ? "Choose the zapret folder first." : "");
  presetRow.classList.toggle("hidden", !found);
  fillZapretPresets(status);
  const select = $("#zapret-preset");
  if (select) {
    // An existing service starts the strategy from its registry key; the
    // selector only matters for the current-user presets.
    const serviceBound = service === "running" || service === "stopped";
    select.disabled = busy || !found || serviceBound;
    select.title = serviceBound
      ? "The zapret service starts the strategy saved in its own settings."
      : "";
  }
}

function fillZapret() {
  if (zap.status) renderZapret();
}

async function refreshZapret() {
  if (zap.loading) return;
  zap.loading = true;
  try {
    const result = await call("zapret_status");
    if (result && result.ok && result.status) {
      zap.status = result.status;
      zap.suggest = Array.isArray(result.suggest) ? result.suggest : [];
      zap.error = "";
    } else {
      zap.status = null;
      zap.suggest = [];
      zap.error = (result && result.error) || "Could not check zapret.";
    }
  } finally {
    zap.loading = false;
    renderZapret();
    if (zap.error) {
      const hint = $("#zapret-hint");
      if (hint) hint.textContent = zap.error;
      if (hint) hint.classList.add("error");
    }
  }
}

async function openZapret() {
  await refreshZapret();
}

async function zapretApply(extra = "") {
  if (S.busy === "zapret") return;
  const status = zap.status || {};
  const needsDownload = !status.found;
  if (extra) zap.pendingExtra = extra;
  if (needsDownload && !zap.confirm) {
    zap.confirm = true;
    if (zap.confirmTimer) window.clearTimeout(zap.confirmTimer);
    zap.confirmTimer = window.setTimeout(() => {
      zap.confirm = false;
      zap.confirmTimer = null;
      renderZapret();
    }, 8000);
    setZapretStatus(needsDownload
      ? "Click again to download the latest zapret release and configure it."
      : "Click again to confirm.");
    renderZapret();
    return;
  }
  resetZapretConfirm();
  const hosts = zap.pendingExtra || "";
  zap.pendingExtra = "";
  setZapretStatus(needsDownload
    ? "Downloading zapret — confirm the administrator prompt…"
    : hosts
      ? "Adding the failed address and turning the bypass on — confirm the "
        + "administrator prompt…"
      : "Applying the list — confirm the administrator prompt…");
  const result = await call("zapret_apply", needsDownload, hosts);
  if (result && result.status) {
    zap.status = result.status;
    renderZapret();
  } else {
    await refreshZapret();
  }
  if (result && result.ok && result.message) {
    setZapretStatus(result.message);
  } else if (result && result.cancelled) {
    setZapretStatus("Cancelled.");
  } else if (result && result.error) {
    setZapretStatus(result.error, true);
  }
}

async function zapretStop() {
  if (S.busy === "zapret") return;
  setZapretStatus("Stopping the bypass…");
  const result = await call("zapret_stop");
  if (result && result.status) {
    zap.status = result.status;
    renderZapret();
  } else {
    await refreshZapret();
  }
  if (result && result.ok && result.message) setZapretStatus(result.message);
  else if (result && result.error) setZapretStatus(result.error, true);
}

async function zapretPickFolder() {
  if (S.busy === "zapret") return;
  const result = await call("zapret_pick_folder");
  if (result && result.ok && result.status) {
    zap.status = result.status;
    renderZapret();
    setZapretStatus(`Using ${result.status.root}.`);
  } else if (result && result.error) {
    setZapretStatus(result.error, true);
  }
}

async function zapretSetPreset(value) {
  if (S.busy === "zapret") return;
  const result = await call("zapret_set_preset", value);
  if (result && result.ok && result.status) {
    zap.status = result.status;
    renderZapret();
    setZapretStatus(`Strategy: ${String(value).replace(/\.bat$/i, "")}.`);
  } else if (result && result.error) {
    setZapretStatus(result.error, true);
    renderZapret();
  }
}

async function zapretSetAuto(value) {
  const result = await call("zapret_set_auto", !!value);
  if (result && result.ok) {
    if (zap.status) zap.status.auto = !!result.auto;
    setZapretStatus(result.auto
      ? "The bypass will start together with the launcher."
      : "The bypass will not start automatically.");
  } else if (result && result.error) {
    setZapretStatus(result.error, true);
  }
  renderZapret();
}

function zapretCancel() {
  call("cancel");
  setZapretStatus("Cancelling…");
}

function zapretOpen(kind) {
  call("zapret_open", kind);
}

function syncZapret() {
  renderZapret();
}

function bindZapret() {
  const on = (id, handler) => {
    const node = $("#" + id);
    if (node) node.addEventListener("click", handler);
  };
  on("btn-zapret-refresh", () => refreshZapret());
  on("btn-zapret-apply", () => zapretApply());
  on("btn-zapret-suggest", () => zapretApply((zap.suggest || []).join(" ")));
  on("btn-zapret-stop", () => zapretStop());
  on("btn-zapret-cancel", () => zapretCancel());
  on("btn-zapret-folder", () => zapretPickFolder());
  on("btn-zapret-open", () => zapretOpen("folder"));
  on("btn-zapret-site", () => zapretOpen("site"));
  on("btn-zapret-clear", () => clearZapretLog());
  const preset = $("#zapret-preset");
  if (preset) preset.addEventListener("change", (event) => {
    zapretSetPreset(event.target.value);
  });
  const auto = $("#zapret-auto");
  if (auto) auto.addEventListener("change", (event) => {
    zapretSetAuto(event.target.checked);
  });
  const consoleEl = $("#zapret-console");
  if (consoleEl) consoleEl.addEventListener("scroll", () => {
    zapretLog.stick =
      consoleEl.scrollTop + consoleEl.clientHeight >= consoleEl.scrollHeight - 24;
  });
}
