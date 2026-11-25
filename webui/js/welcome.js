"use strict";

/* First-run setup: language, theme, performance, network bypass, and optional
 * build import.
 *
 * Shown once, before the launcher is usable, while settings.json has no
 * "onboarded" flag. Everything it changes goes through the same API as the
 * Settings screen, so the result is indistinguishable from a manual setup.
 * The final step calls complete_onboarding() and never appears again. */

const WELCOME_STEPS = ["language", "appearance", "game", "bypass", "packs"];
let welcomeStep = 0;
let welcomeBound = false;
let welcomeZapretBusy = false;
let welcomeZapretFound = null;
let welcomeSetup = null;
let welcomeSetupLoading = false;
let welcomePackSource = "modrinth";
let welcomePackBusy = false;
let welcomeInstances = [];
let welcomeInstanceSelected = new Set();
let welcomeInstancesLoading = false;

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

function reopenWelcome() {
  // Drop cached step data so the setup reads the current saved values again.
  welcomeSetup = null;
  welcomeSetupLoading = false;
  welcomeZapretFound = null;
  welcomeZapretBusy = false;
  welcomePackSource = "modrinth";
  welcomePackBusy = false;
  welcomeInstances = [];
  welcomeInstancesError = "";
  welcomeInstanceSelected = new Set();
  welcomeInstancesLoading = false;
  showWelcome();
}

/* ---------------------------------------------------------------- steps */

const welcomeHeightAnims = new WeakMap();

/* Animate an element from the height it had before a DOM update to the height
   it just got, so steps and lists grow into new content instead of jumping. */
function welcomeAnimateHeight(element, fromHeight) {
  if (!element || !fromHeight) return;
  if (typeof element.animate !== "function") return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const toHeight = element.getBoundingClientRect().height;
  if (Math.abs(toHeight - fromHeight) < .5) return;
  const previous = welcomeHeightAnims.get(element);
  if (previous) previous.cancel();
  const animation = element.animate(
    [{ height: `${fromHeight}px` }, { height: `${toHeight}px` }],
    { duration: 240, easing: "cubic-bezier(.3, .8, .25, 1)" });
  welcomeHeightAnims.set(element, animation);
  animation.addEventListener("finish", () => {
    if (welcomeHeightAnims.get(element) === animation) {
      welcomeHeightAnims.delete(element);
    }
  });
}

/* Run a synchronous DOM update and animate the card to the height it got. */
function welcomeAnimateCard(update) {
  const card = $("#welcome .welcome-card");
  const fromHeight = card ? card.getBoundingClientRect().height : 0;
  update();
  welcomeAnimateHeight(card, fromHeight);
}

function welcomeNextLabel() {
  if (welcomeStep === WELCOME_STEPS.length - 1) return "Finish";
  return "Continue";
}

function renderWelcome(animate = false) {
  const card = animate ? $("#welcome .welcome-card") : null;
  const fromHeight = card ? card.getBoundingClientRect().height : 0;
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

  if (step === "game") loadWelcomeSetup();
  else if (step === "packs") {
    welcomeRenderPackSource();
    if (!welcomeInstances.length && !welcomeInstancesLoading) {
      loadWelcomeInstances();
    } else {
      renderWelcomeInstances();
    }
  }
  else if (step === "bypass") loadWelcomeZapret();

  welcomeAnimateHeight(card, fromHeight);
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
  $$("#welcome-design [data-wdesign]").forEach((button) => {
    const on = button.dataset.wdesign === S.design;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
  });
  updateSegFill($("#welcome-mode"));
  updateSegFill($("#welcome-design"));
}

function welcomeGo(delta) {
  const next = welcomeStep + delta;
  if (next < 0 || next >= WELCOME_STEPS.length) return;
  welcomeStep = next;
  renderWelcome(true);
}

async function finishWelcome(skipped) {
  // Only save the game step when it was actually shown and loading worked;
  // skipping from an earlier step must not overwrite anything.
  if (!skipped && welcomeSetup) {
    const values = welcomeReadSetup();
    try {
      const applied = await call("apply_setup", values.ram, values.game);
      if (applied && applied.state) applyState(applied.state);
    } catch (_) {
      /* Onboarding should never be blocked by a failed save. */
    }
  }
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

/* ----------------------------------------------------------- game setup */

const WELCOME_GAME_FIELDS = {
  gui_scale: "#welcome-gui-scale",
  particles: "#welcome-particles",
  fps_limit: "#welcome-fps",
  fov: "#welcome-fov",
  render_distance: "#welcome-distance",
  brightness: "#welcome-brightness",
};

function welcomeSetupHint(text, error = false) {
  const node = $("#welcome-setup-hint");
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("welcome-status-error", !!error);
}

function welcomeRenderSetupValues() {
  const ram = $("#welcome-ram");
  if (ram) {
    updateRangeFill(ram);
    const label = $("#welcome-ram-value");
    if (label) label.textContent = `${ram.value} GB`;
  }
  const ranges = [
    ["#welcome-distance", "#welcome-distance-value", ""],
    ["#welcome-fov", "#welcome-fov-value", "°"],
    ["#welcome-brightness", "#welcome-brightness-value", "%"],
  ];
  for (const [selector, labelSelector, suffix] of ranges) {
    const input = $(selector);
    if (!input) continue;
    updateRangeFill(input);
    const label = $(labelSelector);
    if (label) label.textContent = input.value + suffix;
  }
}

function welcomeFillSetup(ram, game) {
  const data = normalizeGameDefaults(game);
  for (const [key, selector] of Object.entries(WELCOME_GAME_FIELDS)) {
    const input = $(selector);
    if (input) input.value = String(data[key]);
  }
  const ramInput = $("#welcome-ram");
  if (ramInput) ramInput.value = String(ram);
  welcomeRenderSetupValues();
}

function welcomeReadSetup() {
  const read = (selector, fallback) => {
    const input = $(selector);
    return input ? Number(input.value) : fallback;
  };
  return {
    ram: read("#welcome-ram", 4),
    game: normalizeGameDefaults({
      gui_scale: read("#welcome-gui-scale", 0),
      particles: read("#welcome-particles", 0),
      fps_limit: read("#welcome-fps", 260),
      fov: read("#welcome-fov", 70),
      render_distance: read("#welcome-distance", 12),
      brightness: read("#welcome-brightness", 50),
    }),
  };
}

function welcomeRecommendationText(setup, applied = false) {
  const rec = setup && setup.recommended;
  if (!rec) return "";
  const fps = Number(rec.game.fps_limit) >= 260
    ? "unlimited FPS" : `${rec.game.fps_limit} FPS`;
  const tier = { light: "light", balanced: "balanced", quality: "quality" }
    [rec.tier] || "";
  const lead = applied ? "Applied" : "Recommended for this computer";
  return `${lead}: ${rec.ram} GB RAM · ${rec.game.render_distance} chunks · `
    + fps + (tier ? ` (${tier})` : "") + ".";
}

function welcomeRamHint(setup) {
  const total = setup ? Number(setup.total_ram) || 0 : 0;
  if (!total) {
    return "Memory size was not detected — choose how much RAM Minecraft "
      + "should use.";
  }
  return `This computer has ${total} GB of RAM. Leave room for Windows: `
    + `${setup.recommended.ram} GB is a good choice.`;
}

async function loadWelcomeSetup() {
  if (welcomeSetup || welcomeSetupLoading) return;
  welcomeSetupLoading = true;
  welcomeAnimateCard(() => welcomeSetupHint("Checking this computer…"));
  let result = null;
  try {
    result = await call("setup_defaults");
  } catch (_) {
    result = null;
  }
  welcomeSetupLoading = false;
  if (!result || !result.ok) {
    welcomeAnimateCard(() => welcomeSetupHint(
      "Could not detect this computer — pick the values manually.", true));
    return;
  }
  welcomeSetup = result;
  welcomeAnimateCard(() => {
    const ram = $("#welcome-ram");
    if (ram) {
      ram.min = String(result.ram_min);
      ram.max = String(result.ram_max);
    }
    welcomeFillSetup(result.ram, result.game);
    const hint = $("#welcome-ram-hint");
    if (hint) hint.textContent = welcomeRamHint(result);
    welcomeSetupHint(welcomeRecommendationText(result));
  });
}

function applyWelcomeAuto() {
  if (!welcomeSetup) {
    loadWelcomeSetup();
    return;
  }
  const rec = welcomeSetup.recommended;
  welcomeAnimateCard(() => {
    welcomeFillSetup(rec.ram, rec.game);
    const hint = $("#welcome-ram-hint");
    if (hint) hint.textContent = welcomeRamHint(welcomeSetup);
    welcomeSetupHint(welcomeRecommendationText(welcomeSetup, true));
  });
}

/* ----------------------------------------------- first build import */

let welcomeInstancesError = "";

function welcomePackStatus(text, error = false) {
  const node = $("#welcome-pack-status");
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("welcome-status-error", !!error);
}

function welcomeSourceName(source) {
  return source === "prism" ? "Prism Launcher" : "Modrinth App";
}

function welcomeBuildLabel(count) {
  return `${count} build${count === 1 ? "" : "s"}`;
}

function welcomeRenderPackSource() {
  $$("#welcome-pack-sources [data-wpack-source]").forEach((button) => {
    const source = button.dataset.wpackSource;
    const on = source === welcomePackSource;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
    button.disabled = welcomePackBusy;
    const count = button.querySelector("[data-wpack-count]");
    if (!count) return;
    count.textContent = welcomeInstancesLoading
      ? "…"
      : String(welcomeInstances.filter((item) => item.source === source).length);
  });
}

function welcomeEmptyState(text, rescan = false) {
  const box = elem("div", "import-empty");
  box.appendChild(iconNode("i-import"));
  box.appendChild(elem("p", "", text));
  if (rescan) {
    const button = elem("button", "btn ghost sm", "Scan again");
    button.type = "button";
    button.addEventListener("click", loadWelcomeInstances);
    box.appendChild(button);
  }
  return box;
}

function renderWelcomeInstances(animate = false) {
  const list = $("#welcome-instance-list");
  if (!list) return;
  const fromHeight = animate ? list.getBoundingClientRect().height : 0;
  welcomeRenderPackSource();
  list.replaceChildren();
  const visible = welcomeInstances.filter((instance) =>
    instance.source === welcomePackSource);
  if (welcomeInstancesLoading) {
    list.appendChild(welcomeEmptyState("Searching for installed builds…"));
  } else if (welcomeInstancesError) {
    list.appendChild(welcomeEmptyState(welcomeInstancesError, true));
  } else if (!visible.length) {
    list.appendChild(welcomeEmptyState(
      `No ${welcomeSourceName(welcomePackSource)} builds found on this computer.`,
      true));
  } else {
    visible.forEach((instance) => {
      const index = welcomeInstances.indexOf(instance);
      const selected = welcomeInstanceSelected.has(index);
      const row = elem("button", "import-row" + (selected ? " selected" : ""));
      row.type = "button";
      row.disabled = welcomePackBusy;
      row.setAttribute("aria-pressed", selected ? "true" : "false");
      if (instance.path) row.title = instance.path;
      const initial = Array.from(String(instance.name || "?").trim())[0] || "?";
      const avatar = elem("span", "import-avatar", initial.toUpperCase());
      avatar.setAttribute("aria-hidden", "true");
      row.appendChild(avatar);
      const text = elem("span", "import-row-text");
      text.appendChild(elem("span", "import-row-name",
        instance.name || "Minecraft build"));
      text.appendChild(elem("span", "import-row-meta", [
        instance.game
          ? `Minecraft ${instance.game}` : "Minecraft version unknown",
        instance.loader || "Vanilla",
      ].join(" · ")));
      row.appendChild(text);
      const check = elem("span", "import-check");
      check.setAttribute("aria-hidden", "true");
      if (selected) check.appendChild(iconNode("i-check"));
      row.appendChild(check);
      row.addEventListener("click", () => {
        if (welcomePackBusy) return;
        if (welcomeInstanceSelected.has(index)) {
          welcomeInstanceSelected.delete(index);
        } else {
          welcomeInstanceSelected.add(index);
        }
        renderWelcomeInstances();
      });
      list.appendChild(row);
    });
  }

  const selectedCount = [...welcomeInstanceSelected].filter((index) => {
    const instance = welcomeInstances[index];
    return instance && instance.source === welcomePackSource;
  }).length;
  const selection = $("#welcome-selection-count");
  if (selection) {
    if (welcomeInstancesLoading) {
      selection.textContent = "Reading launcher data…";
    } else if (welcomeInstancesError) {
      selection.textContent = "Scan failed";
    } else if (!visible.length) {
      selection.textContent = "No builds found";
    } else if (selectedCount) {
      selection.textContent = `${welcomeBuildLabel(selectedCount)} selected`;
    } else {
      selection.textContent = "Select builds to import";
    }
    selection.classList.toggle("strong", selectedCount > 0);
  }
  const importButton = $("#btn-welcome-instance-import");
  if (importButton) importButton.disabled = welcomePackBusy || selectedCount === 0;
  const label = $("#welcome-import-label");
  if (label) {
    if (welcomePackBusy) label.textContent = "Importing…";
    else if (selectedCount) {
      label.textContent = `Import ${welcomeBuildLabel(selectedCount)}`;
    } else label.textContent = "Import selected";
  }

  /* Switching sources swaps the list contents, so let the box grow or shrink
     into the new size instead of jumping. */
  if (animate) welcomeAnimateHeight(list, fromHeight);
}

async function loadWelcomeInstances() {
  if (welcomeInstancesLoading) return;
  welcomeInstancesLoading = true;
  welcomeInstancesError = "";
  welcomePackStatus("");
  renderWelcomeInstances(true);
  let result = null;
  try {
    result = await call("discover_launcher_instances");
  } catch (_) {
    result = null;
  }
  welcomeInstancesLoading = false;
  if (result && result.ok) {
    welcomeInstances = Array.isArray(result.instances) ? result.instances : [];
  } else {
    welcomeInstances = [];
    welcomeInstancesError = (result && result.error)
      || "Could not find installed builds.";
  }
  welcomeInstanceSelected = new Set();
  renderWelcomeInstances(true);
}

async function importWelcomePack() {
  if (welcomePackBusy) return;
  const selected = [...welcomeInstanceSelected]
    .map((index) => welcomeInstances[index])
    .filter((instance) => instance && instance.source === welcomePackSource);
  if (!selected.length) return;
  welcomePackBusy = true;
  welcomeAnimateCard(() => {
    welcomePackStatus("");
    renderWelcomeInstances();
  });
  const errors = [];
  let imported = 0;
  for (let index = 0; index < selected.length; index += 1) {
    const instance = selected[index];
    welcomePackStatus(`Importing ${instance.name} (${index + 1}/${selected.length})… This can take a few minutes.`);
    const result = await call("import_launcher_instance", instance.path,
                              instance.source);
    if (result && result.ok) {
      imported += 1;
      if (result.state) applyState(result.state);
    } else {
      errors.push(`${instance.name}: ${(result && result.error) || "failed"}`);
    }
  }
  welcomePackBusy = false;
  await refreshState();
  welcomeAnimateCard(() => {
    welcomePackStatus(errors.length
      ? `Imported ${imported} of ${selected.length}. ${errors[0]}`
      : `Imported ${welcomeBuildLabel(imported)}.`, !!errors.length);
    welcomeInstanceSelected = new Set();
    renderWelcomeInstances();
  });
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
  welcomeAnimateCard(() => welcomeSetStatus("Checking for zapret…"));
  let result = null;
  try {
    result = await call("zapret_status");
  } catch (_) {
    result = null;
  }
  if (!result || !result.ok) {
    welcomeZapretFound = null;
    const text = (result && result.error) || "Could not check for zapret.";
    welcomeAnimateCard(() => {
      welcomeSetStatus(text, true);
      welcomeZapretButtons();
    });
    return;
  }
  const status = result.status || {};
  welcomeZapretFound = !!status.found;
  let text;
  if (!status.found) {
    text = "zapret is not installed on this computer.";
  } else if (status.running || status.service === "running") {
    const label = status.strategy || status.preset || "";
    text = "zapret found" + (label ? " · bypass is running ("
      + label + ")" : " · bypass is running") + ".";
  } else {
    text = "zapret found in " + (status.root || "") + " · the bypass "
      + "is not running.";
  }
  welcomeAnimateCard(() => {
    welcomeSetStatus(text);
    welcomeZapretButtons();
  });
}

async function runWelcomeZapret(download) {
  if (welcomeZapretBusy) return;
  welcomeZapretBusy = true;
  welcomeAnimateCard(() => {
    welcomeZapretButtons();
    welcomeSetStatus(download
      ? "Downloading zapret and turning the bypass on… Confirm the Windows "
        + "administrator prompt."
      : "Turning the bypass on… Confirm the Windows administrator prompt.");
  });
  let result = null;
  try {
    result = await call("zapret_apply", !!download);
  } catch (_) {
    result = null;
  }
  welcomeZapretBusy = false;
  let text;
  let error = false;
  if (!result) {
    text = "Could not run the bypass.";
    error = true;
  } else if (result.ok) {
    welcomeZapretFound = true;
    text = "The bypass is running. You can change it later in the Bypass tab.";
  } else if (result.cancelled) {
    text = "Cancelled — the bypass was not changed.";
  } else if (result.needs_download) {
    welcomeZapretFound = false;
    text = "zapret is not installed. Use “Download and enable” to install it.";
  } else {
    text = result.error || "Could not turn the bypass on.";
    error = true;
  }
  welcomeAnimateCard(() => {
    welcomeSetStatus(text, error);
    welcomeZapretButtons();
  });
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
  $("#btn-reopen-welcome").addEventListener("click", reopenWelcome);

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
  $("#welcome-design").addEventListener("click", async (event) => {
    const option = event.target.closest("[data-wdesign]");
    if (!option) return;
    await changeDesign(option.dataset.wdesign);
    renderWelcomeChoices();
  });

  for (const selector of ["#welcome-ram", "#welcome-distance",
                          "#welcome-fov", "#welcome-brightness"]) {
    const input = $(selector);
    if (input) input.addEventListener("input", welcomeRenderSetupValues);
  }
  $("#btn-welcome-auto").addEventListener("click", applyWelcomeAuto);

  $("#welcome-pack-sources").addEventListener("click", (event) => {
    const button = event.target.closest("[data-wpack-source]");
    if (!button || welcomePackBusy) return;
    welcomePackSource = button.dataset.wpackSource;
    welcomeInstanceSelected = new Set();
    welcomePackStatus("");
    if (!welcomeInstances.length) loadWelcomeInstances();
    else renderWelcomeInstances(true);
  });
  $("#btn-welcome-instance-import").addEventListener("click", importWelcomePack);

  $("#btn-welcome-zapret").addEventListener("click", () => runWelcomeZapret(false));
  $("#btn-welcome-zapret-download").addEventListener(
    "click", () => runWelcomeZapret(true));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindWelcome, { once: true });
} else {
  bindWelcome();
}
