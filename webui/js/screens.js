"use strict";

/* ------------------------------------------------------------- app state */

const THEMES = ["mint", "orange", "indigo"];
const THEME_NAMES = { mint: "Mint", orange: "Soft orange", indigo: "Indigo" };
const THEME_BRAND_ICONS = {
  mint: "star_icon.svg",
  orange: "star_icon_orange.svg",
  indigo: "star_icon_blue.svg",
};
const MODES = ["dark", "light"];
const LANGUAGES = ["en", "ru"];
let activeTheme = "";
let activeMode = "";
let activeLanguage = "";

function applyTheme(theme) {
  const next = THEMES.includes(theme) ? theme : "mint";
  if (next === activeTheme) return;
  activeTheme = next;
  document.documentElement.dataset.theme = next;
  // The wordmark icon is a separate SVG per accent so it keeps its sparkle
  // colour in every theme.
  const brandIcon = document.querySelector(".brand-icon");
  if (brandIcon) brandIcon.src = THEME_BRAND_ICONS[next] || THEME_BRAND_ICONS.mint;
  startOrb();
}

function applyMode(mode) {
  const next = MODES.includes(mode) ? mode : "dark";
  if (next === activeMode) return;
  activeMode = next;
  document.documentElement.dataset.mode = next;
  startOrb();
}

function applyLanguage(language) {
  const next = LANGUAGES.includes(language) ? language : "en";
  if (next === activeLanguage) return;
  activeLanguage = next;
  if (window.I18n) window.I18n.setLanguage(next);
}

function applyState(next) {
  if (!next || !next.instances) return;
  const previous = S.instance ? S.instance.slug : null;
  saveBrowserState();
  S = next;
  applyTheme(S.theme);
  applyMode(S.color_mode);
  applyLanguage(S.language);
  if (editSlug && (!S.instance || S.instance.slug !== editSlug)) {
    resetCreateMode();
  }
  renderProfiles();
  renderTabs();
  updateScreenHeads();
  fillSettings();
  if (screen === "skin") loadSkin();
  if (previous !== (S.instance ? S.instance.slug : null)) resetDeleteConfirm();
  syncBusy();
  ensureScreenData();
}

async function refreshState() {
  const result = await call("state");
  if (result && result.instances) {
    applyState(result);
    return true;
  }
  return false;
}

function ensureScreenData() {
  if (!S.instance && ["mods", "loaders"].includes(screen)) {
    setScreen("profiles");
    return;
  }
  if (screen === "mods" || screen === "modpacks") {
    initMods(screen === "modpacks" ? "modpack" : "");
    if (mods.searchedKey !== browserKey()) searchMods();
  } else if (screen === "loaders") {
    initLoaders();
    if (lb.key !== instanceKey()) loadLoaderBuilds();
  }
}

/* --------------------------------------------------------------- screens */

function setScreen(name) {
  if (["mods", "loaders"].includes(name) && !S.instance) {
    setStatus("Create or select a profile first.");
    name = "profiles";
  }
  /* The Modpacks page and the mods browser share one layout but keep their
     own content kind, so normalise the kind before rendering. */
  if (name === "modpacks") {
    if (mods.kind !== "modpack") {
      mods.kind = "modpack";
      mods.key = "";
      mods.busy = false;
      mods.loadingMore = false;
      mods.searchSeq += 1;
    }
  } else if (name === "mods" && mods.kind === "modpack") {
    mods.kind = modsAllowed() ? "mod" : "resourcepack";
    mods.key = "";
    mods.busy = false;
    mods.loadingMore = false;
    mods.searchSeq += 1;
  }
  screen = name;
  const sectionName = name === "modpacks" ? "mods" : name;
  $$(".screen").forEach((section) => {
    section.classList.toggle("active", section.id === `screen-${sectionName}`);
  });
  renderTabs();
  if (name !== "settings") stopLogsTimer();
  if (name !== "profiles") stopGameLogsTimer();
  if (name !== "skin") stopSkinView();

  if (name === "profiles") {
    renderProfiles();
  } else if (name === "create") {
    if (!versions.loaded && !versions.loading) loadVersions(false);
    // The version list can already be loaded by the profile settings pane,
    // which never renders the create list itself.
    else if (versions.loaded) renderVersions();
  } else if (name === "mods" || name === "modpacks") {
    initMods(name === "modpacks" ? "modpack" : "");
    if (mods.searchedKey !== browserKey()) searchMods();
  } else if (name === "loaders") {
    initLoaders();
    if (lb.key !== instanceKey()) loadLoaderBuilds();
  } else if (name === "settings") {
    fillSettings();
    openLogs();
    openNetwork();
  } else if (name === "skin") {
    loadSkin();
  }
  requestAnimationFrame(() => {
    updateAllSegFills();
    resetSegHovers();
  });
}

function renderTabs() {
  $$("#tabs .tab").forEach((tab) => {
    const name = tab.dataset.screen;
    tab.classList.toggle("active", name === screen);
    const locked = ["loaders"].includes(name) && !S.instance;
    tab.disabled = locked;
  });
  updateSegFill($("#tabs"));
}

function updateScreenHeads() {
  const meta = CONTENT_KINDS[mods.kind] || CONTENT_KINDS.mod;
  if (!S.instance) {
    $("#mods-sub").textContent = mods.kind === "modpack"
      ? "Modrinth · modpacks · installs as a new profile"
      : `Select a profile to manage its ${meta.plural}.`;
    $("#loaders-sub").textContent = "Select a profile to install a loader.";
    return;
  }
  const inst = S.instance;
  const loader = inst.loader === "any"
    ? "vanilla" : (LOADER_LABELS[inst.loader] || inst.loader);
  const target = mods.kind === "modpack"
    ? "all versions" : `Minecraft ${inst.base}`;
  const loaderPart = mods.kind === "mod"
    ? ` · ${mods.loader === "any" ? "any loader" : mods.loader}` : "";
  $("#mods-sub").textContent =
    `Modrinth · ${meta.plural} · ${target}${loaderPart} · ${inst.name}`;
  $("#loaders-sub").textContent =
    `${inst.name} · Minecraft ${inst.base} · currently ${loader === "vanilla" ? inst.version : loader}`;
}
