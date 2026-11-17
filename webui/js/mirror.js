"use strict";

/* -------------------------------------------- mirror / bypass choice modal */

/* When a blocked host falls back to the BMCLAPI mirror, the page asks once
   whether that host should always use the mirror or whether the DPI bypass
   should be used instead. The answer is stored in settings.json, so it
   survives restarts; the same choice is available in Settings → Network. */

const mirrorPrompt = {
  host: "", mirror: "", open: false, muted: false, busy: false,
};

const MIRROR_MODE_TEXT = {
  auto: "The launcher will pick the mirror automatically.",
  always: "The launcher will always use the BMCLAPI mirror.",
  never: "The launcher will never use the mirror.",
};

function mirrorSetBusy(busy) {
  for (const id of ["btn-mirror-always", "btn-mirror-bypass"]) {
    const node = $("#" + id);
    if (node) node.disabled = busy;
  }
  const later = $("#btn-mirror-later");
  if (later) later.disabled = busy;
}

function mirrorActionText(text, error = false) {
  const node = $("#mirror-action-text");
  if (!node) return;
  node.textContent = text || "";
  node.classList.toggle("hidden", !text);
  node.classList.toggle("error", !!error);
}

function renderMirrorMode() {
  const select = $("#mirror-mode");
  if (!select) return;
  const mode = ["auto", "always", "never"].includes(S.mirror)
    ? S.mirror : "auto";
  if (select.value !== mode) select.value = mode;
  select.disabled = S.busy === "zapret";
}

function showMirrorPrompt(host, mirror) {
  if (mirrorPrompt.muted || mirrorPrompt.busy) return;
  const modal = $("#mirror-modal");
  if (!modal) return;
  mirrorPrompt.host = String(host || "").trim();
  mirrorPrompt.mirror = String(mirror || "").trim();
  const text = $("#mirror-text");
  if (text) {
    text.textContent = mirrorPrompt.host
      ? `${mirrorPrompt.host} is blocked on this network. Choose how the `
        + "launcher should download from now on."
      : "A download server is blocked on this network. Choose how the "
        + "launcher should download from now on.";
  }
  mirrorActionText("");
  mirrorSetBusy(false);
  mirrorPrompt.open = true;
  document.body.classList.add("mirror-open");
  modal.classList.remove("hidden");
  const close = $("#btn-mirror-close");
  if (close) close.focus();
}

function closeMirrorPrompt(mute = true) {
  const modal = $("#mirror-modal");
  if (modal) modal.classList.add("hidden");
  document.body.classList.remove("mirror-open");
  mirrorPrompt.open = false;
  mirrorPrompt.busy = false;
  if (mute) mirrorPrompt.muted = true;
  mirrorSetBusy(false);
  mirrorActionText("");
}

async function mirrorSetMode(mode, message) {
  const result = await call("mirror_set_mode", mode);
  if (result && result.ok) {
    if (result.state) applyState(result.state);
    if (message) setStatus(message);
    renderMirrorMode();
    return true;
  }
  if (result && result.error) setStatus(result.error, true);
  renderMirrorMode();
  return false;
}

async function mirrorChooseAlways() {
  if (mirrorPrompt.busy) return;
  mirrorPrompt.busy = true;
  mirrorSetBusy(true);
  mirrorActionText("Saving the choice…");
  const ok = await mirrorSetMode("always", MIRROR_MODE_TEXT.always);
  if (!ok) {
    mirrorPrompt.busy = false;
    mirrorSetBusy(false);
    mirrorActionText("The choice could not be saved.", true);
    return;
  }
  closeMirrorPrompt();
}

async function mirrorChooseAuto() {
  if (mirrorPrompt.busy) return;
  mirrorPrompt.busy = true;
  mirrorSetBusy(true);
  const ok = await mirrorSetMode("auto", MIRROR_MODE_TEXT.auto);
  if (!ok) {
    mirrorPrompt.busy = false;
    mirrorSetBusy(false);
    return;
  }
  closeMirrorPrompt();
}

async function mirrorChooseBypass() {
  if (mirrorPrompt.busy) return;
  mirrorPrompt.busy = true;
  mirrorSetBusy(true);
  mirrorActionText("Checking the bypass…");

  if (!zap.status) await refreshZapret();
  if (!zap.status || !zap.status.found) {
    // Installing zapret downloads third-party binaries and needs an explicit
    // confirmation, so the Bypass tab handles it.
    closeMirrorPrompt(false);
    mirrorPrompt.muted = true;
    setScreen("bypass");
    await refreshZapret();
    setStatus("Confirm the zapret download in the Bypass tab to use the "
              + "bypass.");
    if (typeof zapretApply === "function") {
      zapretApply(mirrorPrompt.host);
    }
    return;
  }

  mirrorActionText("Turning the bypass on — confirm the administrator "
                   + "prompt…");
  const host = mirrorPrompt.host;
  const result = await call("zapret_apply", false, host);
  if (result && result.status) {
    zap.status = result.status;
    renderZapret();
  }
  if (result && result.ok) {
    await mirrorSetMode("never", "The bypass is on; the mirror will not be "
                                 + "used.");
    closeMirrorPrompt();
    return;
  }
  mirrorPrompt.busy = false;
  mirrorSetBusy(false);
  mirrorActionText((result && result.error)
    || (result && result.cancelled ? "Cancelled." : "Could not turn the "
       + "bypass on."), true);
}

function bindMirror() {
  const on = (id, handler) => {
    const node = $("#" + id);
    if (node) node.addEventListener("click", handler);
  };
  on("btn-mirror-close", () => closeMirrorPrompt());
  on("btn-mirror-later", () => closeMirrorPrompt());
  on("btn-mirror-always", () => mirrorChooseAlways());
  on("btn-mirror-bypass", () => mirrorChooseBypass());
  on("btn-mirror-auto", () => mirrorChooseAuto());
  const modal = $("#mirror-modal");
  if (modal) {
    modal.addEventListener("click", (event) => {
      if (event.target.hasAttribute("data-mirror-close")) closeMirrorPrompt();
    });
  }
  const select = $("#mirror-mode");
  if (select) select.addEventListener("change", async (event) => {
    const mode = event.target.value;
    const ok = await mirrorSetMode(mode, MIRROR_MODE_TEXT[mode]);
    if (!ok) renderMirrorMode();
  });
}
