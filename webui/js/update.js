"use strict";

/* ------------------------------------------------------ launcher update */

const upd = {
  info: null, checking: false, silent: false, busy: false, confirm: false,
  confirmTimer: null, status: "", error: false, done: 0, total: 0,
};

function updVersionLabel(value) {
  const version = String(value || "").trim();
  return version ? `v${version.replace(/^v/i, "")}` : "—";
}

function setUpdateStatus(text, error = false) {
  upd.status = String(text || "");
  upd.error = !!error;
  const node = $("#update-status");
  if (node) {
    node.textContent = upd.status;
    node.classList.toggle("error", upd.error);
  }
}

function setUpdateSub(text) {
  const node = $("#update-sub");
  if (node) node.textContent = text;
}

function setUpdateProgress(done, total) {
  upd.done = Number(done) || 0;
  upd.total = Number(total) || 0;
  const wrap = $("#update-progress-wrap");
  const bar = $("#update-progress");
  if (!wrap || !bar) return;
  wrap.classList.remove("hidden");
  if (!upd.total) {
    bar.style.width = "";
    bar.classList.add("indeterminate");
  } else {
    bar.classList.remove("indeterminate");
    bar.style.width =
      `${Math.round((upd.done / upd.total) * 100)}%`;
  }
  syncUpdate();
}

function hideUpdateProgress() {
  upd.done = 0;
  upd.total = 0;
  const wrap = $("#update-progress-wrap");
  const bar = $("#update-progress");
  if (wrap) wrap.classList.add("hidden");
  if (bar) {
    bar.classList.remove("indeterminate");
    bar.style.width = "0";
  }
}

function resetUpdateConfirm() {
  upd.confirm = false;
  if (upd.confirmTimer) {
    window.clearTimeout(upd.confirmTimer);
    upd.confirmTimer = null;
  }
  syncUpdate();
}

function updateBusy() {
  return upd.busy || S.busy === "update";
}

function updateVersionText() {
  const info = upd.info;
  if (updateBusy()) return "Updating…";
  if (!info) return "Update";
  if (upd.confirm) return "Confirm update";
  if (info.available) return `Update to ${updVersionLabel(info.latest)}`;
  return "Update";
}

function syncUpdate() {
  const card = $("#update-card");
  if (!card) return;
  const info = upd.info;
  const busy = updateBusy();
  const available = !!(info && info.available);
  const check = $("#btn-update-check");
  const install = $("#btn-update-install");
  const cancel = $("#btn-update-cancel");

  if (check) check.disabled = busy || upd.checking;
  if (install) {
    install.classList.toggle("hidden", !available);
    install.disabled = busy || upd.checking;
    install.classList.toggle("confirm", upd.confirm);
    const label = install.querySelector("span");
    if (label) label.textContent = updateVersionText();
  }
  if (cancel) cancel.classList.toggle("hidden", !busy);

  card.classList.toggle("has-update", available && !busy);
  card.classList.toggle("is-busy", busy);

  if (busy) setUpdateSub("Updating…");
  else if (upd.checking && !upd.silent) setUpdateSub("Checking…");
  else if (available) setUpdateSub(`${updVersionLabel(info.latest)} available`);
  else if (info) setUpdateSub("Up to date");
  else setUpdateSub("Not checked");
}

function fillUpdate() {
  const label = $("#launcher-version");
  if (label) label.textContent = updVersionLabel(S.version);
  syncUpdate();
  if (upd.status) setUpdateStatus(upd.status, upd.error);
}

async function checkUpdates(silent = false) {
  if (upd.checking || updateBusy()) return;
  upd.checking = true;
  upd.silent = !!silent;
  upd.info = null;
  if (!silent) setUpdateStatus("");
  if (!silent) setUpdateSub("Checking…");
  syncUpdate();
  let result;
  try {
    result = await call("update_check");
  } finally {
    upd.checking = false;
    upd.silent = false;
  }
  if (!result || result.ok === false || result.error) {
    if (!silent) {
      setUpdateStatus((result && result.error) || "Could not check for updates.",
                      true);
    }
    syncUpdate();
    return;
  }
  upd.info = result;
  let message = result.message || "";
  if (result.available) {
    message = `Nexi Launcher ${updVersionLabel(result.latest)} is available. `
      + "Press Update to install it — the launcher will restart, and "
      + "accounts, settings and profiles are kept.";
  }
  setUpdateStatus(message);
  syncUpdate();
}

async function installUpdate() {
  if (updateBusy()) return;
  if (!upd.info) {
    await checkUpdates();
    if (!upd.info || !upd.info.available) return;
  }
  if (!upd.info.available) {
    setUpdateStatus("You are running the latest version.");
    return;
  }
  if (!upd.confirm) {
    upd.confirm = true;
    if (upd.confirmTimer) window.clearTimeout(upd.confirmTimer);
    upd.confirmTimer = window.setTimeout(() => {
      upd.confirm = false;
      upd.confirmTimer = null;
      syncUpdate();
    }, 10000);
    setUpdateStatus(`Click Update again to download Nexi Launcher `
      + `${updVersionLabel(upd.info.latest)} and restart the launcher.`);
    syncUpdate();
    return;
  }
  resetUpdateConfirm();
  upd.busy = true;
  setUpdateStatus(`Downloading Nexi Launcher `
    + `${updVersionLabel(upd.info.latest)}…`);
  syncUpdate();
  setUpdateProgress(0, 0);
  let result;
  try {
    result = await call("update_install");
  } finally {
    upd.busy = false;
  }
  if (result && result.restarting) {
    setUpdateStatus("Update downloaded. The launcher will close and restart.");
    setUpdateProgress(1, 1);
    syncUpdate();
    window.setTimeout(() => call("window_close"), 1400);
    return;
  }
  hideUpdateProgress();
  if (result && result.cancelled) {
    setUpdateStatus("Update cancelled.");
  } else if (result && result.up_to_date) {
    setUpdateStatus("You are running the latest version.");
    await checkUpdates();
    return;
  } else {
    setUpdateStatus((result && result.error) || "Update failed.", true);
  }
  syncUpdate();
}

function cancelUpdate() {
  if (!updateBusy()) return;
  call("cancel");
  setUpdateStatus("Cancelling…");
}

function bindUpdate() {
  const on = (id, handler) => {
    const node = $("#" + id);
    if (node) node.addEventListener("click", handler);
  };
  on("btn-update-check", () => checkUpdates());
  on("btn-update-install", installUpdate);
  on("btn-update-cancel", cancelUpdate);
  window.setTimeout(() => {
    if (!upd.info && !upd.checking) checkUpdates(true);
  }, 3000);
}
