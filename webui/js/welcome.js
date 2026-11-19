"use strict";

/* First-run setup: language, theme and the optional network bypass.
 *
 * Shown once, before the launcher is usable, while settings.json has no
 * "onboarded" flag. Everything it changes goes through the same API as the
 * Settings screen, so the result is indistinguishable from a manual setup.
 * The final step calls complete_onboarding() and never appears again. */

const WELCOME_STEPS = ["language", "appearance", "bypass"];
let welcomeStep = 0;
let welcomeBound = false;
let welcomeZapretBusy = false;
let welcomeZapretFound = null;

function welcomeRoot() {
  return $("#welcome");
}

function welcomeShown() {
  const root = welcomeRoot();
  return !!root && !root.classList.contains("hidden");
}

function maybeShowWelcome() {
  if (!S || S.onboarded !== false) return;
  showWelcome();
}

function showWelcome() {
  const root = welcomeRoot();
  if (!root) return;
  welcomeStep = 0;
  root.classList.remove("hidden");
  renderWelcome();
}

function hideWelcome() {
  const root = welcomeRoot();
  if (root) root.classList.add("hidden");
}

/* ---------------------------------------------------------------- steps */

function welcomeNextLabel() {
  if (welcomeStep === WELCOME_STEPS.length - 1) return "Finish";
  return "Continue";
}

function renderWelcome() {
  const step = WELCOME_STEPS[welcomeStep];
  $$("[data-wstep]").forEach((section) => {
    section.classList.toggle("hidden", section.dataset.wstep !== step);
  });

  const dots = $("#welcome-dots");
  dots.innerHTML = "";
  WELCOME_STEPS.forEach((name, index) => {
    const dot = document.createElement("span");
    dot.className = "welcome-dot" + (index === welcomeStep ? " on" : "");
    dots.appendChild(dot);
  });

  const back = $("#btn-welcome-back");
  back.classList.toggle("hidden", welcomeStep === 0);
  $("#btn-welcome-next").textContent = welcomeNextLabel();
  renderWelcomeChoices();

  if (step === "bypass") loadWelcomeZapret();
}

function renderWelcomeChoices() {
  $$("#welcome [data-wlang]").forEach((button) => {
    const on = button.dataset.wlang === S.language;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
  });
  $$("#welcome-themes [data-theme-option]").forEach((button) => {
    const on = button.dataset.themeOption === S.theme;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
  });
  $$("#welcome-mode [data-wmode]").forEach((button) => {
    const on = button.dataset.wmode === S.color_mode;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
  });
}

function welcomeGo(delta) {
  const next = welcomeStep + delta;
  if (next < 0 || next >= WELCOME_STEPS.length) return;
  welcomeStep = next;
  renderWelcome();
}

async function finishWelcome(skipped) {
  try {
    const result = await call("complete_onboarding");
    if (result && result.state) applyState(result.state);
  } catch (_) {
    /* The flag will be written next time; not worth blocking the app. */
  }
  S.onboarded = true;
  hideWelcome();
  setStatus(skipped
    ? "Setup skipped — everything can be changed in Settings."
    : "Ready.");
}

/* --------------------------------------------------------------- bypass */

function welcomeSetStatus(text, error = false) {
  const node = $("#welcome-zapret-status");
  if (!node) return;
  // English on purpose: the i18n observer swaps the text when the interface
  // language is Russian and restores it when the user switches back.
  node.textContent = text;
  node.classList.toggle("welcome-status-error", !!error);
}

function welcomeZapretButtons() {
  const apply = $("#btn-welcome-zapret");
  const download = $("#btn-welcome-zapret-download");
  apply.disabled = welcomeZapretBusy || welcomeZapretFound === false;
  apply.classList.toggle("hidden", welcomeZapretFound === true);
  download.disabled = welcomeZapretBusy;
  download.classList.toggle("hidden", welcomeZapretFound !== false);
  const warn = $("#welcome-zapret-warn");
  if (warn) warn.classList.toggle("hidden", welcomeZapretFound === true);
}

async function loadWelcomeZapret() {
  welcomeSetStatus("Checking for zapret…");
  let result = null;
  try {
    result = await call("zapret_status");
  } catch (_) {
    result = null;
  }
  if (!result || !result.ok) {
    welcomeZapretFound = null;
    welcomeSetStatus((result && result.error) || "Could not check for zapret.",
      true);
    welcomeZapretButtons();
    return;
  }
  const status = result.status || {};
  welcomeZapretFound = !!status.found;
  if (!status.found) {
    welcomeSetStatus("zapret is not installed on this computer.");
  } else if (status.running || status.service === "running") {
    const label = status.strategy || status.preset || "";
    welcomeSetStatus("zapret found" + (label ? " · bypass is running ("
      + label + ")" : " · bypass is running") + ".");
  } else {
    welcomeSetStatus("zapret found in " + (status.root || "") + " · the bypass "
      + "is not running.");
  }
  welcomeZapretButtons();
}

async function runWelcomeZapret(download) {
  if (welcomeZapretBusy) return;
  welcomeZapretBusy = true;
  welcomeZapretButtons();
  welcomeSetStatus(download
    ? "Downloading zapret and turning the bypass on… Confirm the Windows "
      + "administrator prompt."
    : "Turning the bypass on… Confirm the Windows administrator prompt.");
  let result = null;
  try {
    result = await call("zapret_apply", !!download);
  } catch (_) {
    result = null;
  }
  welcomeZapretBusy = false;
  if (!result) {
    welcomeSetStatus("Could not run the bypass.", true);
  } else if (result.ok) {
    welcomeZapretFound = true;
    welcomeSetStatus("The bypass is running. You can change it later in "
      + "the Bypass tab.");
  } else if (result.cancelled) {
    welcomeSetStatus("Cancelled — the bypass was not changed.");
  } else if (result.needs_download) {
    welcomeZapretFound = false;
    welcomeSetStatus("zapret is not installed. Use “Download and enable” to "
      + "install it.");
  } else {
    welcomeSetStatus(result.error || "Could not turn the bypass on.", true);
  }
  welcomeZapretButtons();
  if (result && result.ok) refreshState();
}

/* --------------------------------------------------------------- wiring */

function bindWelcome() {
  if (welcomeBound) return;
  welcomeBound = true;

  $("#btn-welcome-next").addEventListener("click", () => {
    if (welcomeStep === WELCOME_STEPS.length - 1) finishWelcome(false);
    else welcomeGo(1);
  });
  $("#btn-welcome-back").addEventListener("click", () => welcomeGo(-1));
  $("#btn-welcome-skip").addEventListener("click", () => finishWelcome(true));

  $$("#welcome [data-wlang]").forEach((button) => {
    button.addEventListener("click", async () => {
      await changeLanguage(button.dataset.wlang);
      renderWelcomeChoices();
    });
  });
  $("#welcome-themes").addEventListener("click", async (event) => {
    const option = event.target.closest("[data-theme-option]");
    if (!option) return;
    await changeTheme(option.dataset.themeOption);
    renderWelcomeChoices();
  });
  $("#welcome-mode").addEventListener("click", async (event) => {
    const option = event.target.closest("[data-wmode]");
    if (!option) return;
    await changeMode(option.dataset.wmode);
    renderWelcomeChoices();
  });

  $("#btn-welcome-zapret").addEventListener("click", () => runWelcomeZapret(false));
  $("#btn-welcome-zapret-download").addEventListener(
    "click", () => runWelcomeZapret(true));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindWelcome, { once: true });
} else {
  bindWelcome();
}
