"use strict";

window.__errors = [];
const reportedErrors = new Set();

function reportError(text) {
  const message = String(text);
  window.__errors.push(message);
  if (reportedErrors.size >= 50 || reportedErrors.has(message)) return;
  reportedErrors.add(message);
  try {
    const bridge = window.pywebview && window.pywebview.api;
    if (bridge && typeof bridge.log_js === "function") {
      Promise.resolve(bridge.log_js(message.slice(0, 2000))).catch(() => {});
    }
  } catch (_) { /* logging must never break the page */ }
}

window.addEventListener("error", (event) => reportError(
  `${event.message} @ ${event.filename || ""}:${event.lineno || 0}`));
window.addEventListener("unhandledrejection", (event) => reportError(
  "promise: " + String(event.reason)));

/* Nexi Launcher — web interface.
   Talks to Python through window.pywebview.api (see LauncherApi in launcher.py).
   Long tasks stream progress through a polled event queue. */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const LOADER_KEYS = { Fabric: "fabric", Forge: "forge", NeoForge: "neoforge" };
const LOADER_LABELS = { fabric: "Fabric", forge: "Forge", neoforge: "NeoForge" };
const MOD_LOADERS = ["any", "fabric", "forge", "neoforge"];

const CONTENT_KINDS = {
  mod: {
    title: "Mods", plural: "mods", unit: "mod",
    placeholder: "Search mods by name",
    empty: "Search Modrinth to find mods for this profile.",
    install: "Install", select: "Select a mod",
  },
  resourcepack: {
    title: "Resource packs", plural: "resource packs", unit: "resource pack",
    placeholder: "Search resource packs by name",
    empty: "Search Modrinth to find resource packs for this profile.",
    install: "Install", select: "Select a resource pack",
  },
  shader: {
    title: "Shaders", plural: "shaders", unit: "shader pack",
    placeholder: "Search shaders by name",
    empty: "Search Modrinth to find shaders for this profile.",
    install: "Install", select: "Select a shader pack",
  },
  modpack: {
    title: "Modpacks", plural: "modpacks", unit: "modpack",
    placeholder: "Search modpacks by name",
    empty: "Search Modrinth to find a modpack — it installs as a new profile.",
    install: "Add profile", select: "Select a modpack",
  },
};

let S = {
  instances: [], selected: "", instance: null,
  player: "", ram: 2, default_ram: 2, java: "", ms: {}, ely: {},
  accounts: [], active_account: "", account: "offline", paths: {},
  busy: "", launching: false, game_running: false, game_instance: "",
};
let screen = "profiles";
let booted = false;

const msFlow = { active: false };
const elyFlow = { active: false };
let accountMethod = "microsoft";

const versions = {
  loaded: false, loading: false, all: [], installed: new Set(),
  rows: [], selected: "", query: "",
  filters: { release: true, snapshot: false, old_beta: false,
             old_alpha: false },
};
let loaderSel = "None";
let editSlug = "";
const builds = { list: [], selected: -1, loading: false, request: 0 };
/* Version & loader editor in the profile settings pane. */
const vedit = { key: "", mc: "", loader: "any", build: "", origMc: "",
                req: 0, busy: false, optionsFor: "" };

const mods = { hits: [], selected: -1, loader: "any", kind: "mod", key: "",
               searchedKey: "", busy: false, installed: null,
               statusSeq: 0, statusLoading: false, profile: "",
               checked: new Set(), query: "", offset: 0, total: 0,
               loadingMore: false, searchSeq: 0 };
/* Each profile keeps its own mod browser: search text, results and selection. */
const browserStates = new Map();
const detail = { slug: "", contents: null, loading: false, pane: "mods",
                 request: 0 };
let iconsKey = "";
const lb = { label: "Fabric", builds: [], selected: -1, key: "", loading: false, busy: false };
const logs = { key: null, pending: "", buffer: [], timer: null, stick: true };

const createLogLines = [];
const loaderLogLines = [];

/* ---------------------------------------------------------------- helpers */

function api() { return window.pywebview && window.pywebview.api; }

async function call(method, ...args) {
  const bridge = api();
  if (!bridge || typeof bridge[method] !== "function") {
    return { error: "The interface is still starting." };
  }
  try {
    return (await bridge[method](...args)) ?? {};
  } catch (err) {
    return { error: String((err && err.message) || err) };
  }
}

function elem(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function setStatus(text, error = false) {
  const bar = $("#status");
  bar.textContent = text;
  bar.classList.toggle("error", !!error);
}

function screenStatus(name, text, error = false) {
  const id = { create: "#create-status", mods: "#mods-status", loaders: "#loaders-status" }[name];
  const node = id && $(id);
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("error", !!error);
}

function instanceKey() {
  return S.instance ? `${S.instance.slug}|${S.instance.version}` : "";
}

/* Mods only work in profiles that have a mod loader installed. */
function modsAllowed() {
  return !S.instance
    || ["fabric", "forge", "neoforge", "quilt"].includes(S.instance.loader);
}

function browserKey() {
  return `${mods.kind}|${instanceKey()}`;
}

function stateInstanceKey(state) {
  return state && state.instance ? `${state.instance.slug}|${state.instance.version}` : "";
}

function fmtCount(value) {
  const n = Number(value) || 0;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1).replace(/\.0$/, "")}k`;
  return String(n);
}

function fmtSize(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function profileLetter(name) {
  return (String(name || "?").trim().charAt(0) || "?").toUpperCase();
}

function fillAvatar(node, url, name) {
  node.replaceChildren();
  const letter = (name || "?").trim().charAt(0).toUpperCase() || "?";
  node.appendChild(elem("span", "avatar-letter", letter));
  if (!url) return;
  const img = new Image();
  img.alt = "";
  img.decoding = "async";
  img.src = url;
  img.addEventListener("error", () => img.remove());
  node.appendChild(img);
}

function avatarNode(url, name, cls) {
  const node = elem("span", "avatar" + (cls ? ` ${cls}` : ""));
  fillAvatar(node, url, name);
  return node;
}

/* Mod icon: the Modrinth picture first, the icon inside the jar as fallback. */
function modAvatar(mod) {
  const node = elem("span", "avatar pane-icon");
  node.appendChild(elem("span", "avatar-letter",
    (mod.title || "?").trim().charAt(0).toUpperCase() || "?"));
  const sources = [mod.icon_url, mod.icon].filter(Boolean);
  if (!sources.length) return node;
  const img = new Image();
  img.alt = "";
  img.decoding = "async";
  let index = 0;
  img.addEventListener("error", () => {
    index += 1;
    if (index < sources.length) img.src = sources[index];
    else img.remove();
  });
  img.src = sources[0];
  node.appendChild(img);
  return node;
}

function makeRow({ title, side, selected, cls, icon, onClick }) {
  const hasIcon = icon !== undefined;
  const row = elem("button", "row" + (cls ? ` ${cls}` : "") +
    (hasIcon ? " has-icon" : ""));
  row.type = "button";
  if (hasIcon) row.appendChild(avatarNode(icon, title));
  row.appendChild(elem("span", "row-title", title));
  if (side) row.appendChild(elem("span", "row-side", side));
  if (selected) row.classList.add("selected");
  if (onClick) row.addEventListener("click", onClick);
  return row;
}

function setSeg(selector, value) {
  $$(`${selector} button`).forEach((button) => {
    const key = button.dataset.loader ?? button.dataset.kind;
    button.classList.toggle("on", key === value);
  });
  updateSegFill($(selector));
}

/* ------------------------------------------- sliding active fill for tabs */

const FILL_CONTAINERS = [
  "#tabs", "#detail-tabs", "#account-methods",
  "#kind-seg", "#loader-seg", "#mods-seg", "#loaders-seg",
];

const hoverButtons = new WeakMap();

function segActiveButton(container) {
  return [...container.querySelectorAll(":scope > button")].find(
    (button) => button.classList.contains("on")
      || button.classList.contains("active")) || null;
}

function updateSegFill(container, instant = false) {
  if (!container) return;
  let fill = container.querySelector(".seg-fill");
  if (!fill) {
    fill = document.createElement("span");
    fill.className = "seg-fill";
    fill.setAttribute("aria-hidden", "true");
    container.appendChild(fill);
  }
  const active = segActiveButton(container);
  if (!active || !active.offsetWidth) {
    fill.classList.add("off");
    return;
  }
  const snap = instant || !fill.classList.contains("animate")
    || fill.classList.contains("off");
  fill.classList.remove("off");
  if (snap) fill.classList.add("instant");
  fill.style.width = `${active.offsetWidth}px`;
  fill.style.height = `${active.offsetHeight}px`;
  fill.style.transform =
    `translate(${active.offsetLeft}px, ${active.offsetTop}px)`;
  if (!fill.classList.contains("animate")) {
    requestAnimationFrame(() => {
      fill.classList.add("animate");
      fill.classList.remove("instant");
    });
  } else if (snap) {
    requestAnimationFrame(() => fill.classList.remove("instant"));
  }
}

function updateAllSegFills(instant = false) {
  for (const selector of FILL_CONTAINERS) {
    updateSegFill($(selector), instant);
  }
}

/* The translucent pill that follows the pointer over the buttons. */

function updateSegHover(container) {
  if (!container) return;
  let pill = container.querySelector(".seg-hover");
  if (!pill) {
    pill = document.createElement("span");
    pill.className = "seg-hover";
    pill.setAttribute("aria-hidden", "true");
    container.appendChild(pill);
  }
  const button = hoverButtons.get(container) || null;
  if (!button || !button.isConnected || button.disabled
      || button.parentElement !== container || !button.offsetWidth) {
    pill.classList.remove("on");
    return;
  }
  const snap = !pill.classList.contains("animate");
  if (snap) pill.classList.add("instant");
  pill.style.width = `${button.offsetWidth}px`;
  pill.style.height = `${button.offsetHeight}px`;
  pill.style.transform =
    `translate(${button.offsetLeft}px, ${button.offsetTop}px)`;
  if (!pill.classList.contains("animate")) {
    requestAnimationFrame(() => {
      pill.classList.add("animate");
      pill.classList.remove("instant");
    });
  }
  pill.classList.add("on");
}

function updateAllSegHovers() {
  for (const selector of FILL_CONTAINERS) {
    updateSegHover($(selector));
  }
}

function resetSegHovers() {
  for (const selector of FILL_CONTAINERS) {
    const container = $(selector);
    if (!container) continue;
    hoverButtons.delete(container);
    updateSegHover(container);
  }
}

function initSegHover() {
  for (const selector of FILL_CONTAINERS) {
    const container = $(selector);
    if (!container) continue;
    container.addEventListener("pointerover", (event) => {
      const button = event.target.closest("button");
      if (!button || button.parentElement !== container) return;
      if (button.disabled) {
        if (!hoverButtons.has(container)) return;
        hoverButtons.delete(container);
        updateSegHover(container);
        return;
      }
      if (hoverButtons.get(container) === button) return;
      hoverButtons.set(container, button);
      updateSegHover(container);
    });
    container.addEventListener("pointerleave", () => {
      if (!hoverButtons.has(container)) return;
      hoverButtons.delete(container);
      updateSegHover(container);
    });
  }
}

/* ------------------------------------------------------------- app state */

function applyState(next) {
  if (!next || !next.instances) return;
  const previous = S.instance ? S.instance.slug : null;
  saveBrowserState();
  S = next;
  if (editSlug && (!S.instance || S.instance.slug !== editSlug)) {
    resetCreateMode();
  }
  renderProfiles();
  renderTabs();
  updateScreenHeads();
  fillSettings();
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
  if (!S.instance && ["mods", "loaders", "logs"].includes(screen)
      && !(screen === "mods" && mods.kind === "modpack")) {
    setScreen("profiles");
    return;
  }
  if (screen === "mods") {
    initMods();
    if (mods.searchedKey !== browserKey()) searchMods();
  } else if (screen === "loaders") {
    initLoaders();
    if (lb.key !== instanceKey()) loadLoaderBuilds();
  } else if (screen === "logs") {
    if (logs.key !== S.instance.slug) openLogs();
  }
}

/* --------------------------------------------------------------- screens */

function setScreen(name) {
  const modpackBrowser = name === "mods" && mods.kind === "modpack";
  if (["mods", "loaders", "logs"].includes(name) && !S.instance
      && !modpackBrowser) {
    setStatus("Create or select a profile first.");
    name = "profiles";
  }
  screen = name;
  $$(".screen").forEach((section) => {
    section.classList.toggle("active", section.id === `screen-${name}`);
  });
  renderTabs();
  if (name !== "logs") stopLogsTimer();

  if (name === "profiles") {
    renderProfiles();
  } else if (name === "create") {
    if (!versions.loaded && !versions.loading) loadVersions(false);
  } else if (name === "mods") {
    initMods();
    if (mods.searchedKey !== browserKey()) searchMods();
  } else if (name === "loaders") {
    initLoaders();
    if (lb.key !== instanceKey()) loadLoaderBuilds();
  } else if (name === "logs") {
    openLogs();
  } else if (name === "settings") {
    fillSettings();
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
    const locked = ["loaders", "logs"].includes(name) && !S.instance;
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
    $("#logs-sub").textContent = "Select a profile to read its logs.";
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
  const logsSub = $("#logs-sub");
  if (logsSub.dataset.path) logsSub.textContent = `${inst.name} · ${logsSub.dataset.path}`;
  else logsSub.textContent = `${inst.name} · logs/latest.log`;
}

/* -------------------------------------------------------------- profiles */

function hideProfileTip() {
  const tip = $("#profile-tip");
  if (tip) tip.classList.remove("show");
}

function showProfileTip(card, name) {
  const tip = $("#profile-tip");
  if (!tip) return;
  tip.textContent = name;
  tip.classList.add("show");
  const rect = card.getBoundingClientRect();
  const half = tip.offsetHeight / 2;
  const left = Math.min(rect.right + 10,
                        window.innerWidth - tip.offsetWidth - 8);
  const top = Math.min(Math.max(rect.top + rect.height / 2, half + 8),
                       window.innerHeight - half - 8);
  tip.style.left = `${Math.max(8, left)}px`;
  tip.style.top = `${top}px`;
}

function hideProfileMenu() {
  const menu = $("#profile-menu");
  if (!menu || !menu.classList.contains("open")) return;
  menu.classList.remove("open");
  resetDeleteConfirm();
}

function showProfileMenu(x, y) {
  const menu = $("#profile-menu");
  if (!menu || !S.instance) return;
  hideProfileTip();
  resetDeleteConfirm();
  menu.classList.add("open");
  const rect = menu.getBoundingClientRect();
  const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
  const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  syncBusy();
}

function runProfileMenuAction(action) {
  switch (action) {
    case "open-folder": call("open", "game"); break;
    case "mods": openBrowser("mod"); break;
    case "logs": setScreen("logs"); break;
    case "icon": setProfileIcon(); break;
    case "edit": openEditProfile(); break;
    case "duplicate": duplicateProfile(); break;
    case "backup": backupWorlds(); break;
    case "verify": verifyFiles(); break;
    case "settings": setScreen("settings"); break;
    default: break;
  }
}

function renderProfiles() {
  hideProfileTip();
  hideProfileMenu();
  const list = $("#profile-list");
  list.replaceChildren();
  $("#profiles-count").textContent = S.instances.length
    ? `${S.instances.length} total` : "empty";

  for (const inst of S.instances) {
    const card = elem("button", "profile-card");
    card.type = "button";
    if (inst.slug === S.selected) card.classList.add("selected");
    card.dataset.name = inst.name;
    const loader = inst.loader === "any"
      ? "vanilla" : (LOADER_LABELS[inst.loader] || inst.loader);
    card.title = `${inst.name} — Minecraft ${inst.base} · ${loader}`;
    if (inst.icon) {
      const img = new Image();
      img.className = "profile-icon";
      img.alt = "";
      img.decoding = "async";
      img.src = inst.icon;
      img.addEventListener("error", () => {
        img.remove();
        if (!card.querySelector(".profile-card-letter")) {
          card.appendChild(elem("span", "profile-card-letter",
                               profileLetter(inst.name)));
        }
      });
      card.appendChild(img);
    } else {
      card.appendChild(elem("span", "profile-card-letter",
                           profileLetter(inst.name)));
    }
    card.addEventListener("click", () => selectInstance(inst.slug));
    card.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      hideProfileTip();
      if (S.selected === inst.slug) {
        showProfileMenu(event.clientX, event.clientY);
        return;
      }
      selectInstance(inst.slug).then(() => {
        if (S.instance && S.instance.slug === inst.slug) {
          showProfileMenu(event.clientX, event.clientY);
        }
      });
    });
    card.addEventListener("mouseenter", () => showProfileTip(card, inst.name));
    card.addEventListener("mouseleave", hideProfileTip);
    card.addEventListener("focus", () => showProfileTip(card, inst.name));
    card.addEventListener("blur", hideProfileTip);
    list.appendChild(card);
  }

  const has = !!S.instance;
  $("#profile-empty").classList.toggle("hidden", has);
  $("#profile-detail").classList.toggle("hidden", !has);
  if (has) fillDetail(S.instance);
}

function fillDetail(inst) {
  $("#detail-name").textContent = inst.name;
  const loader = inst.loader === "any"
    ? "vanilla" : (LOADER_LABELS[inst.loader] || inst.loader);
  const loaderText = inst.loader_version
    ? `${loader} ${inst.loader_version}` : loader;
  $("#detail-meta").textContent = `Minecraft ${inst.base} · ${loaderText}`;
  $("#detail-path").textContent = inst.path;
  $("#detail-path").title = inst.path;
  $("#detail-badge").textContent = loader;

  $("#pane-player").textContent = S.player || "Player";
  $("#pane-ram-value").textContent = `${S.ram} GB`;
  $("#pane-java").textContent = S.java ? S.java.split(/[\\/]/).pop() : "Automatic";
  $("#pane-java").title = S.java || "Downloaded automatically for each version";
  $("#pane-java-hint").textContent = S.java
    ? "Custom executable from Settings" : "Downloaded automatically";
  $("#pane-version").textContent = `Minecraft ${inst.base} · ${loaderText}`;
  $("#pane-version-hint").textContent = inst.version;
  $("#pane-settings-sub").textContent = inst.name;
  $("#pane-path").textContent = inst.path;
  $("#pane-path").title = inst.path;

  const changed = detail.slug !== inst.slug;
  if (changed) {
    detail.slug = inst.slug;
    detail.contents = null;
    detail.loading = false;
    detail.pane = "mods";
  }
  syncDetailTabs();
  fillVersionEditor();
  loadProfileContents();
  syncPlay();
}

function syncDetailTabs() {
  $$("#detail-tabs .detail-tab").forEach((tab) => {
    tab.classList.toggle("on", tab.dataset.pane === detail.pane);
  });
  $$(".detail-pane").forEach((pane) => {
    pane.classList.toggle("on", pane.dataset.pane === detail.pane);
  });
  updateSegFill($("#detail-tabs"));
}

function setDetailPane(name) {
  detail.pane = name;
  syncDetailTabs();
  if (!detail.contents) loadProfileContents();
}

async function loadProfileContents(force = false) {
  if (!S.instance) {
    detail.slug = "";
    detail.contents = null;
    detail.loading = false;
    renderDetailPanes();
    return;
  }
  const slug = S.instance.slug;
  if (!force && detail.contents && detail.slug === slug) {
    renderDetailPanes();
    return;
  }
  detail.slug = slug;
  detail.loading = true;
  if (force) detail.contents = null;
  const seq = ++detail.request;
  renderDetailPanes();
  const result = await call("profile_contents");
  if (seq !== detail.request || detail.slug !== slug) return;
  detail.loading = false;
  if (result && result.ok) {
    detail.contents = result;
    resolveModIcons(slug);
  } else {
    detail.contents = null;
    if (result && result.error) setStatus(result.error, true);
  }
  renderDetailPanes();
}

function paneEmpty(text) {
  return elem("div", "pane-empty", text);
}

/* Modrinth knows the names and icons of installed mods; ask once per profile. */
async function resolveModIcons(slug) {
  if (!slug || iconsKey === slug) return;
  iconsKey = slug;
  const result = await call("resolve_mod_icons");
  if (!result.ok) {
    iconsKey = "";
    return;
  }
  if (detail.slug !== slug || !detail.contents) return;
  const map = result.projects || {};
  let changed = false;
  for (const mod of detail.contents.mods || []) {
    const info = map[mod.filename];
    if (!info) continue;
    if (info.title && info.title !== mod.title) mod.title = info.title;
    if (info.icon_url && !mod.icon_url) mod.icon_url = info.icon_url;
    if (!mod.project_id && info.project_id) mod.project_id = info.project_id;
    if (!mod.slug && info.slug) mod.slug = info.slug;
    changed = true;
  }
  if (changed) renderDetailPanes();
}

function paneSub(count, label) {
  return `${count} ${label}${count === 1 ? "" : "s"} in this profile`;
}

function renderDetailPanes() {
  const data = detail.contents;
  const counts = (data && data.counts) || {};
  for (const key of ["mods", "resourcepacks", "shaderpacks", "worlds",
                     "screenshots"]) {
    const node = $("#count-" + key);
    if (node) node.textContent = data ? String(counts[key] || 0) : "–";
  }

  const loading = detail.loading && !data;

  const modsList = $("#pane-mods-list");
  modsList.replaceChildren();
  $("#pane-mods-sub").textContent = data
    ? paneSub(counts.mods || 0, "mod") : (loading ? "Loading…" : "—");
  if (loading) {
    modsList.appendChild(paneEmpty("Reading the profile folder…"));
  } else if (!counts.mods) {
    modsList.appendChild(paneEmpty(
      "No mods yet. Use Browse mods to install one."));
  } else {
    for (const mod of data.mods) {
      const row = elem("div", "pane-row");
      row.appendChild(modAvatar(mod));
      const text = elem("div", "pane-row-text");
      text.appendChild(elem("span", "pane-row-title", mod.title));
      const meta = [mod.version || mod.filename,
                    mod.tracked ? "" : "untracked",
                    fmtSize(mod.size)].filter(Boolean).join(" · ");
      text.appendChild(elem("span", "pane-row-meta", meta));
      row.appendChild(text);
      const button = elem("button", "btn ghost sm", "Uninstall");
      button.type = "button";
      button.disabled = !!S.busy;
      button.addEventListener("click", () => uninstallPaneMod(mod));
      row.appendChild(button);
      modsList.appendChild(row);
    }
  }

  renderPackPane("resourcepacks", "pane-rp-list", "pane-rp-sub",
                 data, loading, "No resource packs installed.");
  renderPackPane("shaderpacks", "pane-shaders-list", "pane-shaders-sub",
                 data, loading, "No shader packs installed.");

  const worldsList = $("#pane-worlds-list");
  worldsList.replaceChildren();
  $("#pane-worlds-sub").textContent = data
    ? paneSub(counts.worlds || 0, "world") : (loading ? "Loading…" : "—");
  if (loading) {
    worldsList.appendChild(paneEmpty("Reading the profile folder…"));
  } else if (!counts.worlds) {
    worldsList.appendChild(paneEmpty(
      "No worlds yet. Start the game to create one."));
  } else {
    for (const world of data.worlds) {
      const row = elem("button", "pane-row");
      row.type = "button";
      row.title = "Open the world folder";
      const text = elem("div", "pane-row-text");
      text.appendChild(elem("span", "pane-row-title", world.name));
      text.appendChild(elem("span", "pane-row-meta",
        [fmtSize(world.size), world.modified].filter(Boolean).join(" · ")));
      row.appendChild(text);
      row.addEventListener("click", () =>
        call("open_instance", "worlds", world.name));
      worldsList.appendChild(row);
    }
  }

  const shotsList = $("#pane-shots-list");
  shotsList.replaceChildren();
  $("#pane-shots-sub").textContent = data
    ? paneSub(counts.screenshots || 0, "screenshot")
    : (loading ? "Loading…" : "—");
  if (loading) {
    shotsList.appendChild(paneEmpty("Reading the profile folder…"));
  } else if (!counts.screenshots) {
    shotsList.appendChild(paneEmpty(
      "No screenshots yet. Press F2 in game to take one."));
  } else {
    for (const shot of data.screenshots) {
      const card = elem("button", "shot");
      card.type = "button";
      card.title = `${shot.name}\n${fmtSize(shot.size)} · ${shot.modified}`;
      if (shot.url) {
        const img = new Image();
        img.className = "shot-thumb";
        img.alt = "";
        img.loading = "lazy";
        img.src = shot.url;
        img.addEventListener("error", () => {
          const placeholder = elem("div", "shot-thumb");
          img.replaceWith(placeholder);
        });
        card.appendChild(img);
      } else {
        card.appendChild(elem("div", "shot-thumb"));
      }
      card.appendChild(elem("span", "shot-name", shot.name));
      card.addEventListener("click", () =>
        call("open_instance", "screenshots", shot.name));
      shotsList.appendChild(card);
    }
  }

  $("#btn-pane-clear-icon").disabled = !!S.busy
    || !S.instance || !S.instance.icon;
  const browseMods = $("#btn-pane-browse-mods");
  if (browseMods) {
    browseMods.disabled = !!S.busy || !modsAllowed();
    browseMods.title = modsAllowed() ? ""
      : "This profile is vanilla — install a mod loader first";
  }
  syncBusy();
}

function renderPackPane(kind, listId, subId, data, loading, emptyText) {
  const list = $("#" + listId);
  const entries = (data && data[kind]) || [];
  list.replaceChildren();
  $(`#${subId}`).textContent = data
    ? paneSub(entries.length, kind === "resourcepacks"
              ? "resource pack" : "shader pack")
    : (loading ? "Loading…" : "—");
  if (loading) {
    list.appendChild(paneEmpty("Reading the profile folder…"));
    return;
  }
  if (!entries.length) {
    list.appendChild(paneEmpty(emptyText));
    return;
  }
  for (const entry of entries) {
    const row = elem("div", "pane-row");
    const text = elem("div", "pane-row-text");
    text.appendChild(elem("span", "pane-row-title", entry.name));
    text.appendChild(elem("span", "pane-row-meta",
      [entry.kind === "folder" ? "folder" : "archive",
       fmtSize(entry.size), entry.modified].filter(Boolean).join(" · ")));
    row.appendChild(text);
    list.appendChild(row);
  }
}

async function uninstallPaneMod(mod) {
  if (!S.instance || S.busy) return;
  const result = await call("mods_uninstall", mod.project_id || "",
                            mod.filename || "");
  if (!result.ok) {
    setStatus(result.error || "Could not remove the mod.", true);
    return;
  }
  setStatus(result.message || "Mod removed.");
  await refreshState();
  await loadProfileContents(true);
}

async function updatePaneMods() {
  if (!S.instance || S.busy) return;
  setStatus("Checking installed mods…");
  const result = await call("mods_update_all", S.instance.loader);
  setStatus(result.message || result.error || "Done.", !result.ok);
  await refreshState();
  if (result.ok) await loadProfileContents(true);
}

async function changePaneRam(delta) {
  if (!S.instance) return;
  const value = Math.max(1, Math.min(16, Number(S.ram) + delta));
  if (value === Number(S.ram)) return;
  const result = await call("set_ram", value);
  if (result.state) applyState(result.state);
}

async function setProfileIcon() {
  if (!S.instance) return;
  const result = await call("set_profile_icon");
  if (result.cancelled) return;
  if (result.error) {
    setStatus(result.error, true);
    return;
  }
  setStatus("Profile icon updated.");
  if (result.state) applyState(result.state);
  else await refreshState();
}

async function clearProfileIcon() {
  if (!S.instance || !S.instance.icon) return;
  const result = await call("clear_profile_icon");
  if (result.error) {
    setStatus(result.error, true);
    return;
  }
  setStatus("Profile icon removed.");
  if (result.state) applyState(result.state);
  else await refreshState();
}

async function selectInstance(slug) {
  if (!slug || slug === S.selected) return;
  resetDeleteConfirm();
  const result = await call("select", slug);
  if (result.state) applyState(result.state);
  else await refreshState();
}

async function changeRam(delta) {
  if (!S.instance) return;
  const value = Math.max(1, Math.min(16, Number(S.ram) + delta));
  if (value === S.ram) return;
  const result = await call("set_ram", value);
  if (result.state) applyState(result.state);
}

/* -------------------------------------------------------------- settings */

function fillSettings() {
  $("#default-ram-value").textContent = `${S.default_ram} GB`;

  const hasProfile = !!S.instance;
  $("#ram-value").textContent = hasProfile ? `${S.ram} GB` : "—";
  $("#ram-down").disabled = !hasProfile;
  $("#ram-up").disabled = !hasProfile;
  $("#ram-profile-name").textContent = hasProfile
    ? `Memory for “${S.instance.name}”` : "Memory for this profile";
  $("#ram-profile-hint").textContent = hasProfile
    ? "Used when this profile starts the game."
    : "Select a profile to change its memory.";

  const javaInput = $("#java-path");
  if (document.activeElement !== javaInput) javaInput.value = S.java || "";
  $("#btn-auto-java").disabled = !S.java;
  $("#java-hint").textContent = S.java
    ? "Custom Java — Minecraft starts with this executable."
    : "Leave empty — the launcher downloads the Java runtime each " +
      "version needs (once per Java version).";

  $("#settings-shared").textContent = (S.paths && S.paths.shared) || "—";
  $("#settings-instances").textContent = (S.paths && S.paths.instances) || "—";

  fillAccount();
}

function accountAvatar(account) {
  const avatar = document.createElement("span");
  avatar.className = "account-avatar";
  if (account.type === "microsoft"
      && /^[0-9a-f]{32}$/i.test(account.uuid || "")) {
    const img = document.createElement("img");
    img.alt = "";
    img.referrerPolicy = "no-referrer";
    img.src = `https://mc-heads.net/avatar/${account.uuid}/80`;
    img.addEventListener("error", () => {
      img.remove();
      avatar.textContent = (account.name || "?").slice(0, 1);
    });
    avatar.appendChild(img);
  } else if (account.type === "ely" && account.name) {
    const url = "https://skinsystem.ely.by/skins/"
      + encodeURIComponent(account.name) + ".png";
    avatar.textContent = account.name.slice(0, 1);
    const probe = new Image();
    probe.addEventListener("load", () => {
      if (!avatar.isConnected) return;
      const head = document.createElement("div");
      head.className = "skin-head";
      head.style.backgroundImage = `url("${url}")`;
      head.style.backgroundPosition =
        `${(64 / (7 * probe.naturalWidth)) * 100}% ` +
        `${(64 / (7 * probe.naturalHeight)) * 100}%`;
      avatar.replaceChildren(head);
    });
    probe.src = url;
  } else {
    avatar.textContent = (account.name || "?").slice(0, 1);
  }
  return avatar;
}

function renderAccountList(accounts) {
  const list = $("#account-list");
  if (!list) return;
  list.replaceChildren();
  if (!accounts.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "No accounts yet — add one below.";
    list.appendChild(empty);
    return;
  }
  for (const account of accounts) {
    const row = document.createElement("div");
    row.className = "account-item" + (account.active ? " on" : "");
    row.appendChild(accountAvatar(account));
    const text = document.createElement("div");
    text.className = "setting-text";
    const name = document.createElement("span");
    name.className = "account-name";
    name.textContent = account.name;
    const hint = document.createElement("span");
    hint.className = "hint";
    hint.textContent = account.type === "microsoft"
      ? "Microsoft account"
      : account.type === "ely" ? "Ely.by account" : "Offline account";
    text.append(name, hint);
    row.appendChild(text);
    if (account.active) {
      const badge = document.createElement("span");
      badge.className = "account-badge";
      badge.textContent = "Active";
      row.appendChild(badge);
    } else {
      const use = document.createElement("button");
      use.type = "button";
      use.className = "btn sm ghost";
      use.dataset.accountUse = account.id;
      use.textContent = "Use";
      row.appendChild(use);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn sm ghost";
    remove.dataset.accountRemove = account.id;
    remove.title = `Remove ${account.name}`;
    remove.textContent = "Remove";
    row.appendChild(remove);
    list.appendChild(row);
  }
}

function fillAccount() {
  const ms = S.ms || {};
  const ely = S.ely || {};
  const accounts = S.accounts || [];
  const activeAccount = accounts.find((account) => account.active) || null;
  const provider = activeAccount ? activeAccount.type : "offline";

  const input = $("#ms-client-id");
  if (input && document.activeElement !== input) {
    input.value = ms.client_id || "";
    input.placeholder = ms.built_in
      ? "Built-in Client ID is used" : "Application (client) ID";
  }

  $("#account-status").textContent =
    provider === "microsoft" ? "microsoft"
      : provider === "ely" ? "ely.by" : "offline";

  renderAccountList(accounts);

  $("#account-signed-out").classList.toggle("hidden", msFlow.active);
  $("#ms-code").classList.toggle("hidden", !msFlow.active);
  $("#ely-wait").classList.toggle("hidden", !elyFlow.active);
  $("#btn-ely-browser").disabled = elyFlow.active;
  for (const method of ["microsoft", "ely", "offline"]) {
    $("#panel-" + method).classList.toggle(
      "hidden", method !== accountMethod);
    $("#btn-method-" + method).classList.toggle(
      "on", accountMethod === method);
  }

  const oauth = ely.oauth || {};
  const oauthId = $("#ely-oauth-client-id");
  if (oauthId && document.activeElement !== oauthId) {
    oauthId.value = oauth.client_id || "";
    oauthId.placeholder = oauth.built_in
      ? "Built-in Client ID is used" : "Client ID from account.ely.by";
  }
  const oauthRedirect = $("#ely-oauth-redirect");
  if (oauthRedirect && document.activeElement !== oauthRedirect) {
    oauthRedirect.value = oauth.redirect_uri
      || "http://localhost:26206/ely-callback";
  }
  const oauthSecret = $("#ely-oauth-client-secret");
  if (oauthSecret) {
    if (document.activeElement !== oauthSecret) oauthSecret.value = "";
    oauthSecret.placeholder = oauth.pkce
      ? "Leave blank to use PKCE (no secret)"
      : "Saved — leave blank to keep";
  }
  $("#ely-browser-hint").textContent = oauth.configured
    ? "A browser page opens on ely.by — sign in there and the launcher "
      + "adds that account automatically. No password to type here."
    : "Browser sign-in is not configured yet. Open “Advanced: browser "
      + "sign-in (OAuth) setup” below and add an Ely.by Client ID — a "
      + "“Desktop application” app (PKCE) needs no secret — or use the "
      + "password form.";
  $("#ely-oauth-status").textContent = oauth.configured
    ? (oauth.built_in && !oauth.client_id
      ? "Browser sign-in is ready — a built-in Ely.by Client ID is used "
        + "(PKCE, no secret). You can override it below."
      : "Browser sign-in is configured. You can change the credentials below "
        + "at any time.")
    : "Browser sign-in only needs an Ely.by Client ID for a “Desktop "
      + "application” (PKCE, no secret). A “Website” app also works — then "
      + "paste its Client Secret too. Enter them here once; everyone using "
      + "this copy of the launcher can then sign in with the button above.";
  updateSegFill($("#account-methods"));
}

function setAccountMethod(method) {
  if (!["microsoft", "ely", "offline"].includes(method)) return;
  accountMethod = method;
  fillAccount();
  if (method === "ely") $("#ely-username").focus();
}

async function elyLogin() {
  const username = $("#ely-username").value.trim();
  const password = $("#ely-password").value;
  const totp = $("#ely-totp").value.trim();
  if (!username || !password) {
    setStatus("Enter your Ely.by e-mail/username and password.", true);
    return;
  }
  const button = $("#btn-ely-login");
  button.disabled = true;
  setStatus("Signing in to Ely.by…");
  const result = await call("ely_login", username, password, totp);
  button.disabled = false;
  if (!result || !result.ok) {
    if (result && result.two_factor) {
      $("#ely-totp-field").classList.remove("hidden");
      $("#ely-totp").focus();
    }
    setStatus((result && result.error) || "Ely.by sign-in failed.", true);
    return;
  }
  $("#ely-password").value = "";
  $("#ely-totp").value = "";
  $("#ely-totp-field").classList.add("hidden");
  if (result.state) applyState(result.state);
  setStatus(`Signed in to Ely.by as ${result.name}.`);
}

async function elyBrowserLogin() {
  if (elyFlow.active) return;
  const result = await call("ely_browser_login");
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not start Ely.by browser sign-in.", true);
    if (result && result.setup) {
      const box = $("#ely-oauth-help");
      if (box) box.open = true;
      const field = $("#ely-oauth-client-id");
      if (field) field.focus();
    }
    return;
  }
  elyFlow.active = true;
  fillAccount();
  setStatus("Waiting for Ely.by sign-in in the browser…");
}

async function elyCancel() {
  await call("ely_cancel_login");
  elyFlow.active = false;
  fillAccount();
  setStatus("Ely.by browser sign-in cancelled.");
}

async function saveElyOauth() {
  const clientId = $("#ely-oauth-client-id").value.trim();
  const clientSecret = $("#ely-oauth-client-secret").value.trim();
  const redirect = $("#ely-oauth-redirect").value.trim();
  if (!clientId) {
    setStatus("Enter the Ely.by OAuth Client ID.", true);
    return;
  }
  const button = $("#btn-save-ely-oauth");
  button.disabled = true;
  const result = await call("set_ely_oauth", clientId, clientSecret, redirect);
  button.disabled = false;
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not save the OAuth settings.", true);
    return;
  }
  $("#ely-oauth-client-secret").value = "";
  if (result.state) applyState(result.state);
  const configured = !!(S.ely && S.ely.oauth && S.ely.oauth.configured);
  setStatus(configured
    ? "Browser sign-in is ready. Press “Sign in with browser”."
    : "Saved. Add the Ely.by Client ID before browser sign-in works.");
}

async function selectAccount(accountId) {
  const result = await call("account_select", accountId);
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not switch accounts.", true);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus("Active account switched.");
}

async function removeAccount(accountId) {
  const account = (S.accounts || []).find((item) => item.id === accountId);
  const result = await call("account_remove", accountId);
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not remove the account.",
      true);
    return;
  }
  msFlow.active = false;
  elyFlow.active = false;
  if (result.state) applyState(result.state);
  setStatus(account ? `Removed ${account.name}.` : "Account removed.");
}

async function addOfflineAccount() {
  const input = $("#player-name");
  const name = input.value.trim();
  if (!name) {
    setStatus("Type an offline player name first.", true);
    input.focus();
    return;
  }
  const result = await call("account_add_offline", name);
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not add the account.",
      true);
    return;
  }
  input.value = "";
  if (result.state) applyState(result.state);
  setStatus(`Offline account “${result.name}” is active.`);
}

async function saveMsClientId(verbose = true) {
  const value = $("#ms-client-id").value.trim();
  const result = await call("set_ms_client_id", value);
  if (!result.ok) {
    setStatus(result.error || "Could not save the Client ID.", true);
    return false;
  }
  if (result.state) applyState(result.state);
  if (verbose) {
    setStatus(value ? "Client ID saved." : "Client ID cleared.");
  }
  return true;
}

function showMsCode(code, uri) {
  msFlow.active = true;
  accountMethod = "microsoft";
  $("#ms-code-value").textContent = code || "…";
  $("#ms-code-hint").textContent =
    `Enter this code at ${uri || "microsoft.com/link"} — the browser ` +
    "should open by itself; you can also open the page on any device.";
  fillAccount();
  if (code && navigator.clipboard) {
    navigator.clipboard.writeText(code).catch(() => {});
  }
}

async function msLogin() {
  const typed = $("#ms-client-id").value.trim();
  if (typed !== ((S.ms && S.ms.client_id) || "")) {
    if (!(await saveMsClientId(false))) return;
  }
  const result = await call("ms_login");
  if (!result.ok) {
    setStatus(result.error || "Could not start Microsoft sign-in.", true);
    return;
  }
  showMsCode(result.user_code, result.verification_uri);
  setStatus("Waiting for Microsoft sign-in…");
}

async function msCancel() {
  await call("ms_cancel_login");
  msFlow.active = false;
  fillAccount();
  setStatus("Microsoft sign-in cancelled.");
}

async function changeDefaultRam(delta) {
  const value = Math.max(1, Math.min(16, Number(S.default_ram) + delta));
  if (value === S.default_ram) return;
  const result = await call("set_default_ram", value);
  if (result.state) applyState(result.state);
}

async function applyJavaPath() {
  const value = $("#java-path").value.trim();
  const result = await call("set_java", value);
  if (result.state) applyState(result.state);
  if (result.ok) {
    setStatus(result.state && result.state.java
      ? `Java set: ${result.state.java}`
      : "Java set to automatic.");
  } else {
    setStatus(result.error || "That Java path is not valid.", true);
  }
}

async function pickJava() {
  const result = await call("pick_java");
  if (result.cancelled) return;
  if (result.state) applyState(result.state);
  if (result.ok) setStatus(`Java set: ${result.state.java}`);
  else setStatus(result.error || "Could not set Java.", true);
}

async function useAutoJava() {
  const result = await call("set_java", "");
  if (result.state) applyState(result.state);
  setStatus("Java set to automatic.");
}

let playBusy = false;

function syncPlay() {
  const starting = !!S.launching;
  const running = !!S.game_running;
  const play = $("#btn-play");
  const row = $("#play-running");
  const mine = !!S.instance && S.game_instance === S.instance.slug;
  const showRunning = running && mine;
  play.classList.toggle("hidden", showRunning);
  row.classList.toggle("hidden", !showRunning);
  play.classList.toggle("starting", starting);
  play.disabled = starting || playBusy || (running && !mine);
  play.title = running && !mine ? "The game is already running." : "";
  $("#play-label").textContent = starting ? "Starting…" : "Play";
  $("#btn-stop").disabled = playBusy || !showRunning;
  $("#btn-restart").disabled = playBusy || !showRunning;
}

async function play() {
  if (!S.instance || S.launching || S.game_running || playBusy) return;
  S.launching = true;
  syncPlay();
  setStatus(`Starting "${S.instance.name}"…`);
  const result = await call("play");
  if (!result.ok) {
    S.launching = false;
    syncPlay();
    setStatus(result.error || "Could not start the game.", true);
  }
}

async function stopGame() {
  if (playBusy) return;
  playBusy = true;
  syncPlay();
  setStatus("Stopping the game…");
  const result = await call("game_stop");
  playBusy = false;
  S.launching = false;
  S.game_running = false;
  S.game_instance = "";
  syncPlay();
  if (!result.ok) setStatus(result.error || "Could not stop the game.", true);
  else setStatus(result.message || "Game stopped.");
}

async function restartGame() {
  if (playBusy) return;
  playBusy = true;
  S.game_running = false;
  S.launching = true;
  syncPlay();
  setStatus("Restarting the game…");
  const result = await call("game_restart");
  playBusy = false;
  if (!result.ok) {
    S.launching = false;
    syncPlay();
    setStatus(result.error || "Could not restart the game.", true);
  }
}

/* delete: two clicks, the second one really removes the profile */
let confirmTimer = null;

function resetDeleteConfirm() {
  clearTimeout(confirmTimer);
  const button = $('#profile-menu [data-profile-action="delete"]');
  if (!button) return;
  button.classList.remove("confirm");
  button.querySelector(".ctx-label").textContent = "Delete";
}

function onDelete() {
  if (!S.instance) return;
  const button = $('#profile-menu [data-profile-action="delete"]');
  if (!button) return;
  if (!button.classList.contains("confirm")) {
    button.classList.add("confirm");
    button.querySelector(".ctx-label").textContent = "Confirm delete";
    setStatus(`Press Delete again to permanently remove "${S.instance.name}" — its worlds, mods and configs are deleted, shared versions stay.`);
    confirmTimer = setTimeout(resetDeleteConfirm, 5000);
    return;
  }
  clearTimeout(confirmTimer);
  const slug = S.instance.slug;
  hideProfileMenu();
  call("delete", slug).then(async (result) => {
    resetDeleteConfirm();
    if (result.state) applyState(result.state);
    else await refreshState();
    if (result.message) setStatus(result.message);
  });
}

/* ---------------------------------------------------------------- create */

function resetCreateMode() {
  if (!editSlug) return;
  editSlug = "";
  $("#new-name").value = "";
  $("#create-title").textContent = "New profile";
  $("#create-sub").textContent = "Pick any Minecraft version — missing files are downloaded from Mojang.";
  $("#btn-create").textContent = "Create profile";
}

function openEditProfile() {
  if (!S.instance) return;
  editSlug = S.instance.slug;
  $("#create-title").textContent = "Edit profile";
  $("#create-sub").textContent = "Change the name, Minecraft version or mod loader. Worlds, mods and configs stay in place.";
  $("#btn-create").textContent = "Save changes";
  $("#new-name").value = S.instance.name || "";
  $("#version-search").value = "";
  loaderSel = LOADER_LABELS[S.instance.loader] || "None";
  setSeg("#loader-seg", loaderSel);
  versions.selected = S.instance.base || "";
  builds.request += 1;
  builds.loading = false;
  builds.list = [];
  builds.selected = -1;
  renderBuilds();
  setScreen("create");
  if (!versions.loaded) loadVersions(false);
  else renderVersions();
  if (loaderSel !== "None") loadBuilds();
}

/* --------------------------------------- version & loader (profile pane) */

function versionOptions(current) {
  const installed = versions.installed || new Set();
  let rows = (versions.all || []).filter(
    (entry) => entry.type === "release" || installed.has(entry.id));
  if (current && !rows.some((entry) => entry.id === current)) {
    rows = [{ id: current, type: "installed" }, ...rows];
  }
  return rows;
}

function fillVersionSelect() {
  const select = $("#edit-version");
  if (!select) return;
  const current = select.value || vedit.mc
    || (S.instance ? S.instance.base : "") || "";
  const rows = versionOptions(current);
  const signature = rows.length
    ? `${rows.length}|${rows[0].id}|${rows[rows.length - 1].id}`
    : "0";
  if (signature !== vedit.optionsFor) {
    vedit.optionsFor = signature;
    select.replaceChildren();
    for (const entry of rows) {
      const option = elem("option", "", entry.id);
      option.value = entry.id;
      select.appendChild(option);
    }
  }
  if (current && rows.some((entry) => entry.id === current)) {
    select.value = current;
  }
  if (S.instance) vedit.mc = select.value || vedit.mc;
}

function ensureVersionOptions() {
  if (versions.loaded || versions.loading) return;
  versions.loading = true;
  call("versions", false).then((result) => {
    versions.loading = false;
    versions.loaded = true;
    versions.all = result.versions || [];
    versions.installed = new Set(result.installed || []);
    fillVersionSelect();
  });
}

function loadEditBuilds() {
  const select = $("#edit-build");
  if (!select) return;
  const loaderKey = vedit.loader;
  const mc = vedit.mc;
  vedit.req += 1;
  const request = vedit.req;
  select.replaceChildren();
  if (loaderKey === "any") {
    const option = elem("option", "", "No loader");
    option.value = "";
    select.appendChild(option);
    vedit.build = "";
    syncVersionEditor();
    return;
  }
  const loading = elem("option", "", "Loading builds…");
  loading.value = "";
  select.appendChild(loading);
  call("builds", loaderKey, mc).then((result) => {
    if (request !== vedit.req) return;
    const builds = result.builds || [];
    select.replaceChildren();
    if (!builds.length) {
      const option = elem("option", "",
        result.error || "No builds for this version");
      option.value = "";
      select.appendChild(option);
      vedit.build = "";
      syncVersionEditor();
      return;
    }
    for (const build of builds) {
      const option = elem("option", "", build.label || build.version);
      option.value = build.version;
      select.appendChild(option);
    }
    const keep = mc === vedit.origMc && vedit.build
      && builds.some((build) => String(build.version).toLowerCase()
        === vedit.build.toLowerCase());
    select.value = keep ? vedit.build : builds[0].version;
    vedit.build = select.value;
    syncVersionEditor();
  });
}

function syncVersionEditor() {
  const mc = $("#edit-version");
  if (!mc) return;
  const busy = vedit.busy || !!S.busy;
  mc.disabled = busy;
  $("#edit-loader").disabled = busy;
  $("#edit-build").disabled = busy || vedit.loader === "any";
  $("#btn-apply-version").disabled = busy;
}

function fillVersionEditor(force = false) {
  if (!S.instance) return;
  const inst = S.instance;
  const key = `${inst.slug}|${inst.version}`;
  if (force || vedit.key !== key) {
    vedit.key = key;
    vedit.mc = inst.base || "";
    vedit.loader = LOADER_LABELS[inst.loader] ? inst.loader : "any";
    vedit.build = String(inst.loader_version || "");
    vedit.origMc = inst.base || "";
    $("#edit-loader").value = vedit.loader;
    fillVersionSelect();
    loadEditBuilds();
  } else {
    fillVersionSelect();
  }
  ensureVersionOptions();
  syncVersionEditor();
}

async function applyVersionChange() {
  if (!S.instance || vedit.busy || S.busy) return;
  const mc = $("#edit-version").value || vedit.mc;
  const loaderKey = vedit.loader === "any" ? null : vedit.loader;
  const build = loaderKey ? ($("#edit-build").value || "") : null;
  if (!mc) {
    setStatus("Pick a Minecraft version first.", true);
    return;
  }
  if (loaderKey && !build) {
    setStatus("Pick a loader version first.", true);
    return;
  }
  vedit.busy = true;
  syncVersionEditor();
  setStatus("Updating the profile — files may be downloaded…");
  const result = await call("update_instance", S.instance.name || "",
                            mc, loaderKey, build);
  vedit.busy = false;
  if (result.state) {
    vedit.key = "";
    vedit.optionsFor = "";
    applyState(result.state);
  } else {
    syncVersionEditor();
  }
  setStatus(result.message || result.error || "Done.", !result.ok);
}

function loadVersions(force) {
  if (versions.loading) return;
  versions.loading = true;
  screenStatus("create", force
    ? "Refreshing the Mojang version list…"
    : "Loading the Minecraft version list from Mojang…");
  syncBusy();
  call("versions", !!force).then((result) => {
    versions.loading = false;
    versions.loaded = true;
    versions.all = result.versions || [];
    versions.installed = new Set(result.installed || []);
    renderVersions();
    if (result.error) {
      screenStatus("create", `Could not load the Mojang version list: ${result.error}`, true);
    } else if (versions.rows.length) {
      screenStatus("create", `${versions.rows.length} versions — pick one`);
      if (loaderSel !== "None" && versions.selected && !builds.list.length) {
        loadBuilds();
      }
    } else {
      screenStatus("create", "No versions found — refresh the list.", true);
    }
    fillVersionSelect();
    syncBusy();
  });
}

function renderVersions() {
  const list = $("#version-list");
  list.replaceChildren();
  versions.query = $("#version-search").value.trim().toLowerCase();

  const rows = versions.all.filter((entry) => {
    if (versions.query) return entry.id.toLowerCase().includes(versions.query);
    if (versions.installed.has(entry.id)) return true;
    return !!versions.filters[entry.type];
  }).slice(0, 600);

  versions.rows = rows;
  if (!rows.some((row) => row.id === versions.selected)) {
    versions.selected = rows.length ? rows[0].id : "";
  }

  if (!rows.length) {
    list.appendChild(elem("div", "empty-row",
      versions.loading ? "Loading…"
        : "Nothing matches — clear the search or enable more types."));
    return;
  }

  for (const entry of rows) {
    const row = makeRow({
      title: entry.id,
      side: versions.installed.has(entry.id) ? "installed" : "download",
      selected: entry.id === versions.selected,
      cls: "version-row",
      onClick: () => {
        if (versions.selected === entry.id) return;
        versions.selected = entry.id;
        renderVersions();
        if (loaderSel !== "None") loadBuilds();
      },
    });
    list.appendChild(row);
  }
}

function setLoader(label) {
  if (S.busy === "create" || label === loaderSel) return;
  loaderSel = label;
  setSeg("#loader-seg", label);
  if (label === "None") {
    builds.request += 1;
    builds.loading = false;
    builds.list = [];
    builds.selected = -1;
    renderBuilds();
    screenStatus("create", "Vanilla profile — no mod loader will be installed.");
    return;
  }
  loadBuilds();
}

function loadBuilds() {
  const key = LOADER_KEYS[loaderSel];
  if (!key || builds.loading || S.busy === "create") return;
  if (!versions.selected) {
    screenStatus("create", "Pick a Minecraft version first.", true);
    return;
  }
  builds.loading = true;
  builds.request += 1;
  const request = builds.request;
  builds.list = [];
  builds.selected = -1;
  renderBuilds();
  screenStatus("create", `Looking up ${loaderSel} builds for ${versions.selected}…`);
  call("builds", key, versions.selected).then((result) => {
    if (request !== builds.request) return;
    builds.loading = false;
    builds.list = result.builds || [];
    builds.selected = builds.list.length ? 0 : -1;
    const wanted = editSlug && S.instance && versions.selected === S.instance.base
      ? String(S.instance.loader_version || "") : "";
    if (wanted) {
      const index = builds.list.findIndex(
        (build) => String(build.version).toLowerCase() === wanted.toLowerCase());
      if (index >= 0) builds.selected = index;
    }
    renderBuilds();
    if (result.error) {
      screenStatus("create", `Could not list builds: ${result.error}`, true);
    } else if (!builds.list.length) {
      screenStatus("create", `No ${loaderSel} builds for ${versions.selected} — try another loader.`, true);
    } else {
      screenStatus("create", `${builds.list.length} ${loaderSel} builds found.`);
    }
    syncBusy();
  });
}

function renderBuilds() {
  const list = $("#build-list");
  list.replaceChildren();
  if (!builds.list.length) {
    let text = "Pick a loader above.";
    if (loaderSel === "None") text = "No loader — vanilla profile.";
    else if (builds.loading) text = "Loading…";
    list.appendChild(elem("div", "empty-row", text));
    return;
  }
  builds.list.forEach((build, index) => {
    list.appendChild(makeRow({
      title: build.label,
      side: "",
      selected: index === builds.selected,
      onClick: () => {
        builds.selected = index;
        renderBuilds();
      },
    }));
  });
}

async function createProfile() {
  if (S.busy === "create") return;
  const name = $("#new-name").value.trim();
  if (!versions.selected) {
    screenStatus("create", "Select a Minecraft version first.", true);
    return;
  }
  const key = LOADER_KEYS[loaderSel] || null;
  if (key && builds.selected < 0) {
    screenStatus("create", "Pick a loader build, or set the loader to None.", true);
    return;
  }
  const build = key ? builds.list[builds.selected].version : null;
  const editing = editSlug;
  clearCreateLog();
  screenStatus("create", editing ? "Saving changes…" : "Creating…");
  S.busy = "create";
  syncBusy();
  const result = editing
    ? await call("update_instance", name, versions.selected, key, build)
    : await call("create", name, versions.selected, key, build);
  S.busy = "";
  syncBusy();
  if (result.cancelled) {
    screenStatus("create", editing
      ? "Cancelled — the profile was not changed."
      : "Cancelled — no profile was created.");
    return;
  }
  if (result.ok) {
    if (result.message) setStatus(result.message);
    if (result.state) applyState(result.state);
    else await refreshState();
    resetCreateMode();
    setScreen("profiles");
    if (result.partial) screenStatus("create", result.message, true);
  } else {
    screenStatus("create", result.error || (editing
      ? "Could not update the profile." : "Could not create the profile."), true);
  }
}

async function duplicateProfile() {
  if (!S.instance || S.busy) return;
  S.busy = "duplicate";
  syncBusy();
  setStatus("Copying the profile — worlds and logs are skipped…");
  const result = await call("duplicate_profile");
  S.busy = "";
  syncBusy();
  if (result.state) applyState(result.state);
  setStatus(result.message || result.error || "Done.", !result.ok);
}

async function backupWorlds() {
  if (!S.instance || S.busy) return;
  S.busy = "backup";
  syncBusy();
  setStatus("Packing the worlds…");
  const result = await call("backup_worlds");
  S.busy = "";
  syncBusy();
  setStatus(result.message || result.error || "Done.", !result.ok);
}

async function verifyFiles() {
  if (!S.instance || S.busy) return;
  S.busy = "verify";
  syncBusy();
  setStatus("Checking game files — this can take a minute…");
  const result = await call("verify_files");
  S.busy = "";
  syncBusy();
  setStatus(result.message || result.error || "Done.", !result.ok);
}

async function importModpack() {
  if (S.busy) return;
  const picked = await call("pick_modpack");
  if (picked.cancelled) {
    setStatus("Import cancelled.");
    return;
  }
  if (!picked.ok) {
    setStatus(picked.error || "Could not open the file picker.", true);
    return;
  }
  if (editSlug) resetCreateMode();
  const fallbackVersion = versions.selected
    || (S.instance ? S.instance.base : "");
  const key = LOADER_KEYS[loaderSel] || null;
  const build = key && builds.selected >= 0
    ? builds.list[builds.selected].version : null;
  S.busy = "import";
  syncBusy();
  setStatus("Importing the modpack — this can take a few minutes…");
  const result = await call("import_modpack", picked.path,
                            fallbackVersion, key, build);
  S.busy = "";
  syncBusy();
  if (result.ok) {
    if (result.state) applyState(result.state);
    else await refreshState();
    setStatus(result.message || "Modpack imported.");
    setScreen("profiles");
  } else {
    setStatus(result.error || "Could not import the modpack.", true);
  }
}

function appendCreateLog(line) {
  createLogLines.push(line);
  const log = $("#create-log");
  log.appendChild(canvasText(line));
  log.scrollTop = log.scrollHeight;
}

function clearCreateLog() {
  createLogLines.length = 0;
  $("#create-log").replaceChildren();
}

/* ------------------------------------------------------------------ mods */

function syncKindUi() {
  const meta = CONTENT_KINDS[mods.kind] || CONTENT_KINDS.mod;
  $("#mods-title").textContent = meta.title;
  $("#mods-query").placeholder = meta.placeholder;
  const modButton = $('#kind-seg button[data-kind="mod"]');
  if (modButton) {
    modButton.disabled = !modsAllowed();
    modButton.title = modsAllowed() ? ""
      : "This profile is vanilla — install a mod loader first";
  }
  $("#mods-seg").classList.toggle("hidden", mods.kind !== "mod");
  $("#btn-mod-update-all").classList.toggle("hidden", mods.kind !== "mod");
  $("#btn-open-mods-folder").classList.toggle("hidden",
    mods.kind === "modpack");
  $("#btn-open-folder-label").textContent = mods.kind === "resourcepack"
    ? "Open resource packs"
    : mods.kind === "shader" ? "Open shaders" : "Open mods folder";
  $("#btn-mod-install").textContent = meta.install;
  syncBatch();
}

function resetBrowser() {
  mods.hits = [];
  mods.selected = -1;
  mods.installed = null;
  mods.searchedKey = "";
  mods.statusSeq += 1;
  mods.statusLoading = false;
  mods.checked.clear();
  mods.offset = 0;
  mods.total = 0;
  mods.loadingMore = false;
  mods.searchSeq += 1;
  $("#mods-query").value = "";
  renderHits();
  showModInfo(null);
}

function saveBrowserState() {
  if (!mods.profile) return;
  browserStates.delete(mods.profile);
  browserStates.set(mods.profile, {
    kind: mods.kind,
    loader: mods.loader,
    query: $("#mods-query").value,
    hits: mods.hits,
    selected: mods.selected,
    installed: mods.installed,
    searchedKey: mods.searchedKey,
    checked: new Set(mods.checked),
    offset: mods.offset,
    total: mods.total,
  });
  // Keep only the few most recently used profiles in memory.
  while (browserStates.size > 6) {
    const oldest = browserStates.keys().next().value;
    browserStates.delete(oldest);
  }
}

function restoreBrowserState(saved, detected) {
  mods.kind = CONTENT_KINDS[saved.kind] ? saved.kind : "mod";
  mods.loader = saved.loader || detected;
  mods.hits = saved.hits || [];
  mods.selected = Number.isInteger(saved.selected) ? saved.selected : -1;
  mods.installed = saved.installed || null;
  mods.searchedKey = saved.searchedKey || "";
  mods.checked = saved.checked instanceof Set ? saved.checked : new Set();
  mods.offset = Number(saved.offset) || 0;
  mods.total = Number(saved.total) || mods.hits.length;
  mods.query = saved.query || "";
  $("#mods-query").value = saved.query || "";
  renderHits();
  showModInfo(mods.hits[mods.selected] || null);
  if (mods.selected >= 0) refreshModStatus();
}

function initMods() {
  const detected = S.instance
    && ["fabric", "forge", "neoforge"].includes(S.instance.loader)
    ? S.instance.loader : "any";
  const profile = instanceKey();
  if (mods.profile !== profile) {
    saveBrowserState();
    mods.profile = profile;
    if (profile) {
      const saved = browserStates.get(profile);
      if (saved) {
        restoreBrowserState(saved, detected);
      } else {
        mods.kind = "mod";
        mods.loader = detected;
        resetBrowser();
      }
    }
    mods.key = browserKey();
  } else if (mods.key !== browserKey()) {
    mods.key = browserKey();
    resetBrowser();
  }
  if (mods.kind === "mod" && !modsAllowed()) {
    mods.kind = "resourcepack";
    mods.key = "";
    resetBrowser();
    mods.key = browserKey();
  }
  setSeg("#kind-seg", mods.kind);
  setSeg("#mods-seg", mods.loader);
  syncKindUi();
  updateScreenHeads();
  syncMods();
}

function setBrowserKind(kind) {
  if (!CONTENT_KINDS[kind] || mods.kind === kind || mods.busy) return;
  if (kind === "mod" && !modsAllowed()) {
    setStatus("This profile is vanilla — install Fabric, Forge or NeoForge "
      + "to use mods.", true);
    return;
  }
  mods.kind = kind;
  mods.key = "";
  resetBrowser();
  setSeg("#kind-seg", kind);
  syncKindUi();
  updateScreenHeads();
  syncMods();
  const meta = CONTENT_KINDS[kind];
  if (!S.instance && kind !== "modpack") {
    setStatus(`Select a profile to browse ${meta.plural}.`);
    setScreen("profiles");
    return;
  }
  searchMods();
}

function openBrowser(kind) {
  if (kind === "mod" && !modsAllowed()) {
    setStatus("This profile is vanilla — install Fabric, Forge or NeoForge "
      + "to use mods.", true);
    return;
  }
  if (CONTENT_KINDS[kind] && mods.kind !== kind) {
    mods.kind = kind;
    mods.key = "";
    resetBrowser();
    setSeg("#kind-seg", kind);
    syncKindUi();
  }
  setScreen("mods");
}

async function searchMods(more = false) {
  if (mods.busy) return;
  if (!S.instance && mods.kind !== "modpack") return;
  if (more) {
    if (mods.loadingMore || !mods.hits.length || mods.hits.length >= mods.total) {
      return;
    }
  } else {
    mods.offset = 0;
    mods.total = 0;
    mods.selected = -1;
    mods.checked.clear();
    mods.loadingMore = false;
    mods.query = $("#mods-query").value.trim();
    mods.searchedKey = browserKey();
  }
  const request = more ? mods.searchSeq : ++mods.searchSeq;
  if (more) mods.loadingMore = true;
  else mods.busy = true;
  screenStatus("mods", more ? "Loading more…" : "Searching Modrinth…");
  renderHits();
  syncMods();
  const result = await call("content_search", mods.kind, mods.query || "",
                            mods.loader, mods.offset);
  if (request !== mods.searchSeq) return;
  if (more) mods.loadingMore = false;
  else mods.busy = false;
  syncMods();
  if (result.error) {
    mods.searchedKey = "";
    screenStatus("mods", result.error, true);
    renderHits();
    return;
  }
  const hits = result.hits || [];
  mods.total = Number(result.total) || (mods.offset + hits.length);
  mods.offset += hits.length;
  mods.hits = more ? mods.hits.concat(hits) : hits;
  if (!more) {
    if (mods.hits.length) {
      mods.selected = 0;
    } else {
      mods.selected = -1;
      showModInfo(null);
    }
  }
  renderHits();
  if (mods.selected >= 0) applyHitSelection();
  const meta = CONTENT_KINDS[mods.kind] || CONTENT_KINDS.mod;
  if (!mods.hits.length) {
    screenStatus("mods", "Nothing found — try another name"
      + (mods.kind === "mod" ? " or loader" : ""));
  } else {
    screenStatus("mods",
      `${mods.hits.length} of ${mods.total} ${meta.plural}`
      + (mods.hits.length < mods.total ? " — scroll for more" : ""));
  }
}

function maybeLoadMore() {
  const list = $("#mod-list");
  if (!list) return;
  if (mods.busy || mods.loadingMore) return;
  if (!mods.hits.length || mods.hits.length >= mods.total) return;
  if (!mods.searchedKey) return;
  // Start the next page well before the very bottom (about one and a half
  // screens with a 700 px floor) so scrolling never waits on the network.
  const margin = Math.max(700, Math.round(list.clientHeight * 1.6));
  const remaining = list.scrollHeight - list.clientHeight - list.scrollTop;
  if (remaining <= margin || list.scrollHeight <= list.clientHeight + 4) {
    searchMods(true);
  }
}

function syncBatch() {
  const button = $("#btn-mod-install-many");
  if (!button) return;
  const count = mods.checked.size;
  const usable = count > 0 && mods.kind !== "modpack";
  button.classList.toggle("hidden", !usable);
  button.disabled = !!mods.busy || !!S.busy
    || (mods.kind === "mod" && !modsAllowed());
  button.textContent = `Install selected (${count})`;
}

function renderHits() {
  const list = $("#mod-list");
  const meta = CONTENT_KINDS[mods.kind] || CONTENT_KINDS.mod;
  list.replaceChildren();
  if (!mods.hits.length) {
    list.appendChild(elem("div", "empty-row", mods.busy
      ? "Searching…" : meta.empty));
    syncBatch();
    return;
  }
  mods.hits.forEach((hit, index) => {
    const row = elem("div", "row mod-row has-icon");
    row.tabIndex = 0;
    if (index === mods.selected) row.classList.add("selected");
    const box = elem("input", "mod-check");
    box.type = "checkbox";
    box.checked = mods.checked.has(hit.project_id);
    box.title = "Add to the batch";
    box.addEventListener("click", (event) => event.stopPropagation());
    box.addEventListener("change", () => {
      if (box.checked) mods.checked.add(hit.project_id);
      else mods.checked.delete(hit.project_id);
      syncBatch();
    });
    row.appendChild(box);
    row.appendChild(avatarNode(hit.icon_url || "", hit.title));
    row.appendChild(elem("span", "row-title", hit.title));
    row.appendChild(elem("span", "row-side",
      `${fmtCount(hit.downloads)} downloads`));
    row.addEventListener("click", () => {
      mods.selected = index;
      if (mods.checked.has(hit.project_id)) mods.checked.delete(hit.project_id);
      else mods.checked.add(hit.project_id);
      applyHitSelection();
    });
    row.addEventListener("dblclick", () => {
      mods.selected = index;
      mods.checked.add(hit.project_id);
      applyHitSelection();
      installMod();
    });
    list.appendChild(row);
  });
  if (mods.loadingMore) {
    list.appendChild(elem("div", "empty-row", "Loading more…"));
  } else if (mods.hits.length < mods.total) {
    list.appendChild(elem("div", "empty-row", "Scroll for more"));
  }
  syncBatch();
  maybeLoadMore();
}

function updateHitRows() {
  const rows = $("#mod-list").querySelectorAll(".mod-row");
  rows.forEach((row, index) => {
    row.classList.toggle("selected", index === mods.selected);
    const box = row.querySelector(".mod-check");
    const hit = mods.hits[index];
    if (box && hit) box.checked = mods.checked.has(hit.project_id);
  });
  syncBatch();
}

function applyHitSelection() {
  updateHitRows();
  showModInfo(mods.hits[mods.selected] || null);
  refreshModStatus();
  syncMods();
}

function showModInfo(hit) {
  const meta = CONTENT_KINDS[mods.kind] || CONTENT_KINDS.mod;
  const holder = $("#mod-avatar");
  if (hit) {
    $("#mod-name").textContent = hit.title;
    $("#mod-author").textContent = hit.author || "";
    $("#mod-desc").textContent = hit.description || "";
    fillAvatar(holder, hit.icon_url || "", hit.title);
  } else {
    $("#mod-name").textContent = meta.select;
    $("#mod-author").textContent = "";
    $("#mod-desc").textContent = "";
    holder.replaceChildren();
    mods.installed = null;
  }
}

async function refreshModStatus() {
  const hit = mods.hits[mods.selected];
  const seq = ++mods.statusSeq;
  if (!hit || mods.kind === "modpack") {
    mods.installed = null;
    mods.statusLoading = false;
    syncMods();
    return;
  }
  mods.statusLoading = true;
  syncMods();
  const result = await call("content_status", mods.kind, hit.project_id,
                            mods.loader, hit.slug || "");
  if (seq !== mods.statusSeq) return;
  mods.statusLoading = false;
  mods.installed = result && result.installed ? {
    filename: result.filename || "",
    versionId: result.version_id || "",
    versionNumber: result.version_number || "",
  } : null;
  syncMods();
}

function syncMods() {
  const busy = mods.busy || mods.statusLoading || !!S.busy;
  const hasHit = mods.selected >= 0 && !!mods.hits[mods.selected];
  const installed = !!mods.installed && mods.kind !== "modpack";
  const needsProfile = mods.kind !== "modpack";
  $("#btn-mod-search").disabled = busy || (needsProfile && !S.instance);
  $("#btn-mod-update-all").disabled = busy || !S.instance
    || mods.kind !== "mod";
  $("#btn-mod-install").classList.toggle("hidden", installed);
  $("#mod-manage").classList.toggle("hidden",
    mods.kind === "modpack" || !installed);
  $("#btn-mod-install").disabled = busy || !hasHit;
  $("#btn-mod-uninstall").disabled = busy || !installed;
  $("#btn-mod-update").disabled = busy || !installed;
  syncBatch();
}

async function installMod() {
  if (mods.busy) return;
  if (!S.instance && mods.kind !== "modpack") return;
  const hit = mods.hits[mods.selected];
  if (!hit) return;
  mods.busy = true;
  screenStatus("mods", mods.kind === "modpack"
    ? `Preparing ${hit.title} — this can take a while…`
    : `Preparing ${hit.title}…`);
  syncMods();
  const result = await call("content_install", mods.kind, hit.project_id,
                            mods.loader, hit.slug || "");
  mods.busy = false;
  syncMods();
  if (mods.kind === "modpack" && result.ok) {
    setStatus(result.message || "Modpack installed.");
    await refreshState();
    setScreen("profiles");
    return;
  }
  screenStatus("mods", result.message || result.error || "Done.", !result.ok);
  if (result.ok) {
    await refreshModStatus();
    await loadProfileContents(true);
  }
}

async function installSelected() {
  if (mods.busy || !S.instance || mods.kind === "modpack") return;
  if (mods.kind === "mod" && !modsAllowed()) return;
  const hits = mods.hits.filter((hit) => mods.checked.has(hit.project_id));
  if (!hits.length) return;
  mods.busy = true;
  syncMods();
  syncBatch();
  const errors = [];
  let done = 0;
  for (let index = 0; index < hits.length; index += 1) {
    const hit = hits[index];
    screenStatus("mods",
      `Downloading ${hit.title} (${index + 1}/${hits.length})…`);
    const result = await call("content_install", mods.kind, hit.project_id,
                              mods.loader, hit.slug || "");
    if (result.ok) {
      done += 1;
      mods.checked.delete(hit.project_id);
    } else {
      errors.push(`${hit.title}: ${result.error || result.message || "failed"}`);
    }
    updateHitRows();
  }
  mods.busy = false;
  syncMods();
  renderHits();
  screenStatus("mods", errors.length
    ? `Installed ${done} of ${hits.length} — ${errors[0]}`
    : `Installed ${done} ${done === 1 ? "item" : "items"}.`, !!errors.length);
  if (done) {
    await refreshModStatus();
    await loadProfileContents(true);
  }
}

async function uninstallMod() {
  if (!S.instance || mods.busy) return;
  const hit = mods.hits[mods.selected];
  if (!hit) return;
  mods.busy = true;
  screenStatus("mods", `Removing ${hit.title}…`);
  syncMods();
  const result = await call("content_uninstall", mods.kind, hit.project_id,
                            mods.installed ? mods.installed.filename : "");
  mods.busy = false;
  syncMods();
  screenStatus("mods", result.message || result.error || "Done.", !result.ok);
  if (result.ok) {
    await refreshModStatus();
    await loadProfileContents(true);
  }
}

async function updateMod() {
  if (!S.instance || mods.busy) return;
  const hit = mods.hits[mods.selected];
  if (!hit) return;
  mods.busy = true;
  screenStatus("mods", `Checking ${hit.title}…`);
  syncMods();
  const result = await call("content_update", mods.kind, hit.project_id,
                            mods.loader, hit.slug || "");
  mods.busy = false;
  syncMods();
  screenStatus("mods", result.message || result.error || "Done.", !result.ok);
  if (result.ok) {
    await refreshModStatus();
    await loadProfileContents(true);
  }
}

async function updateAllMods() {
  if (!S.instance || mods.busy) return;
  mods.busy = true;
  screenStatus("mods", "Checking installed mods…");
  syncMods();
  const result = await call("mods_update_all", mods.loader);
  mods.busy = false;
  syncMods();
  screenStatus("mods", result.message || result.error || "Done.", !result.ok);
  if (result.ok) refreshModStatus();
}

/* --------------------------------------------------------------- loaders */

function initLoaders() {
  if (!S.instance) return;
  const key = instanceKey();
  if (lb.key !== key) {
    lb.label = S.instance.loader_label || "Fabric";
    setSeg("#loaders-seg", lb.label);
  }
  updateScreenHeads();
}

function loadLoaderBuilds() {
  if (!S.instance || lb.loading || S.busy === "loaders") return;
  lb.key = instanceKey();
  lb.loading = true;
  lb.builds = [];
  lb.selected = -1;
  renderLoaderBuilds();
  screenStatus("loaders", `Looking up ${lb.label} builds for ${S.instance.base}…`);
  syncLoaders();
  call("builds", LOADER_KEYS[lb.label], S.instance.base).then((result) => {
    lb.loading = false;
    lb.builds = result.builds || [];
    lb.selected = lb.builds.length ? 0 : -1;
    renderLoaderBuilds();
    if (result.error) {
      lb.key = "";
      screenStatus("loaders", `Could not list builds: ${result.error}`, true);
    } else if (!lb.builds.length) {
      screenStatus("loaders", `No ${lb.label} builds for ${S.instance.base} — try another loader or Refresh.`);
    } else {
      screenStatus("loaders", `${lb.builds.length} builds found — press Install loader`);
    }
    syncLoaders();
  });
}

function renderLoaderBuilds() {
  const list = $("#loader-build-list");
  list.replaceChildren();
  $("#builds-count").textContent = lb.builds.length ? `${lb.builds.length} total` : "—";
  if (!lb.builds.length) {
    list.appendChild(elem("div", "empty-row",
      lb.loading ? "Loading…" : "No builds loaded."));
    return;
  }
  lb.builds.forEach((build, index) => {
    list.appendChild(makeRow({
      title: build.label,
      side: "",
      selected: index === lb.selected,
      onClick: () => {
        lb.selected = index;
        renderLoaderBuilds();
        syncLoaders();
      },
    }));
  });
}

function syncLoaders() {
  const busy = lb.busy || S.busy === "loaders";
  $("#btn-install-loader").disabled = busy || lb.loading || lb.selected < 0;
  $("#btn-cancel-loader").classList.toggle("hidden", !busy);
  $("#btn-refresh-loader-builds").disabled = busy || lb.loading;
}

async function installLoader() {
  if (!S.instance || lb.busy || lb.selected < 0) return;
  const build = lb.builds[lb.selected];
  if (!build) return;
  lb.busy = true;
  clearLoaderLog();
  screenStatus("loaders", `Installing ${lb.label} ${build.version} for ${S.instance.base}…`);
  syncLoaders();
  const result = await call("loader_install", LOADER_KEYS[lb.label], build.version);
  lb.busy = false;
  if (result.ok && result.state) {
    lb.key = stateInstanceKey(result.state);
    applyState(result.state);
    if (result.message) setStatus(result.message);
  } else if (result.cancelled) {
    screenStatus("loaders", "Cancelled.");
  } else {
    screenStatus("loaders", result.error || "Install failed.", true);
  }
  syncLoaders();
}

function appendLoaderLog(line) {
  loaderLogLines.push(line);
  const log = $("#loader-log");
  log.appendChild(canvasText(line));
  log.scrollTop = log.scrollHeight;
}

function clearLoaderLog() {
  loaderLogLines.length = 0;
  $("#loader-log").replaceChildren();
}

/* ------------------------------------------------------------------ logs */

function canvasText(text) {
  return elem("span", "log-line", text + "\n");
}

function lineClass(line) {
  if (/\/ERROR\]|\/FATAL\]/.test(line) || /^(Error:|Exception)/.test(line)) return "line-error";
  if (/\/WARN\]/.test(line) || /^WARNING/.test(line)) return "line-warn";
  return "";
}

function appendText(text, cls) {
  if (!text) return;
  logs.pending += text;
  if (!logs.pending.includes("\n")) return;
  const parts = logs.pending.split("\n");
  logs.pending = parts.pop();
  appendLines(parts, cls);
}

function appendLines(lines, cls) {
  if (!lines.length) return;
  const consoleEl = $("#log-console");
  const fragment = document.createDocumentFragment();
  for (const line of lines) {
    const clean = line.replace(/\r$/, "");
    const span = elem("span", "log-line " + (cls !== undefined ? cls : lineClass(clean)), clean + "\n");
    logs.buffer.push(span);
    fragment.appendChild(span);
  }
  consoleEl.appendChild(fragment);
  trimBuffer(consoleEl);
  if (screen === "logs" && logs.stick) consoleEl.scrollTop = consoleEl.scrollHeight;
}

function trimBuffer(consoleEl) {
  while (logs.buffer.length > 2000) {
    const old = logs.buffer.shift();
    if (old && old.parentNode) old.parentNode.removeChild(old);
  }
}

function clearLogsView() {
  logs.pending = "";
  logs.buffer.length = 0;
  $("#log-console").replaceChildren();
}

async function openLogs() {
  if (!S.instance) return;
  const slug = S.instance.slug;
  logs.key = slug;
  clearLogsView();
  const result = await call("logs_open");
  const sub = $("#logs-sub");
  if (result.path) {
    sub.dataset.path = result.path;
    sub.textContent = `${S.instance.name} · ${result.path}`;
    sub.title = result.path;
  }
  if (!result.exists) {
    appendLines(["Waiting for logs/latest.log — the file appears when the game starts."], "line-dim");
  } else {
    appendText(result.text);
  }
  startLogsTimer();
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
  if (screen !== "logs") { stopLogsTimer(); return; }
  const result = await call("logs_read");
  if (result.reset) clearLogsView();
  if (result.text) appendText(result.text);
}

function appendGameLine(line) {
  appendLines([line]);
}

/* --------------------------------------------------------------- events */

function handleEvent(ev) {
  switch (ev.t) {
    case "status":
      if (ev.screen === "create") screenStatus("create", ev.text, ev.error);
      else if (ev.screen === "loaders") screenStatus("loaders", ev.text, ev.error);
      else if (ev.screen === "mods") screenStatus("mods", ev.text, ev.error);
      else setStatus(ev.text, ev.error);
      break;
    case "log":
      if (ev.channel === "create") appendCreateLog(ev.line);
      else if (ev.channel === "loaders") appendLoaderLog(ev.line);
      break;
    case "progress":
      setProgress(ev.value, ev.total);
      break;
    case "busy":
      S.busy = ev.on ? ev.task : "";
      syncBusy();
      syncMods();
      syncLoaders();
      break;
    case "refresh":
      refreshState();
      break;
    case "game":
      appendGameLine(ev.line);
      break;
    case "msauth":
      if (ev.status === "code") {
        showMsCode(ev.user_code, ev.verification_uri);
        setStatus("Enter the sign-in code in the browser to finish.");
      } else if (ev.status === "ok") {
        msFlow.active = false;
        setStatus(`Signed in as ${ev.name}.`);
        fillAccount();
        refreshState();
      } else if (ev.status === "error") {
        msFlow.active = false;
        setStatus(ev.message || "Microsoft sign-in failed.", true);
        fillAccount();
      } else if (ev.status === "cancelled" || ev.status === "signed_out") {
        msFlow.active = false;
        fillAccount();
        setStatus(ev.status === "signed_out"
          ? "Microsoft account removed."
          : "Microsoft sign-in cancelled.");
      }
      break;
    case "elyauth":
      if (ev.status === "waiting") {
        elyFlow.active = true;
        fillAccount();
        setStatus("Waiting for Ely.by sign-in in the browser…");
      } else if (ev.status === "ok") {
        elyFlow.active = false;
        setStatus(`Signed in to Ely.by as ${ev.name}.`);
        fillAccount();
        refreshState();
      } else if (ev.status === "error") {
        elyFlow.active = false;
        setStatus(ev.message || "Ely.by browser sign-in failed.", true);
        fillAccount();
      } else if (ev.status === "cancelled") {
        elyFlow.active = false;
        fillAccount();
        setStatus("Ely.by browser sign-in cancelled.");
      }
      break;
    case "play":
      if (ev.ok) {
        if (ev.starting) {
          S.launching = true;
          S.game_running = false;
        } else {
          S.launching = false;
          S.game_running = true;
          S.game_instance = S.instance ? S.instance.slug : "";
        }
        setStatus(ev.message || "Game started.");
      } else {
        S.launching = false;
        S.game_running = false;
        S.game_instance = "";
        setStatus(ev.message || "Could not start the game.", true);
      }
      syncPlay();
      break;
    case "gameproc":
      if (!ev.running) {
        S.launching = false;
        S.game_running = false;
        S.game_instance = "";
        syncPlay();
        if (ev.message) setStatus(ev.message);
      }
      break;
    default:
      break;
  }
}

function setProgress(done, total) {
  if (!total) {
    $("#create-progress").style.width = "0";
    $("#loader-progress").style.width = "0";
    return;
  }
  const bar = S.busy === "loaders" ? $("#loader-progress") : $("#create-progress");
  bar.style.width = `${Math.round((done / total) * 100)}%`;
}

function syncBusy() {
  const creating = S.busy === "create";
  const installing = S.busy === "loaders";
  const busy = !!S.busy;
  $("#btn-create").disabled = busy;
  $("#btn-refresh-versions").disabled = busy || versions.loading;
  $("#btn-refresh-builds").disabled = busy || builds.loading;
  $("#btn-cancel-create").classList.toggle("hidden", !creating);
  $("#btn-cancel-loader").classList.toggle("hidden", !installing);
  $("#btn-install-loader").disabled = busy || lb.loading || lb.selected < 0;
  for (const id of ["btn-new-profile", "btn-empty-create",
                    "btn-import-modpack", "btn-pane-update-all",
                    "btn-pane-backup", "btn-pane-icon", "btn-pane-edit"]) {
    const node = $("#" + id);
    if (node) node.disabled = busy;
  }
  if (!modsAllowed()) {
    const updateMods = $("#btn-pane-update-all");
    if (updateMods) updateMods.disabled = true;
  }
  $$("#profile-menu [data-profile-action]").forEach((node) => {
    node.disabled = busy;
  });
  const clearIcon = $("#btn-pane-clear-icon");
  if (clearIcon) clearIcon.disabled = busy || !S.instance || !S.instance.icon;
  syncVersionEditor();
  syncPlay();
}

/* ---------------------------------------------------------------- wiring */

let bound = false;

function bind() {
  if (bound) return;
  bound = true;
  $("#tabs").addEventListener("click", (event) => {
    const tab = event.target.closest(".tab");
    if (tab && !tab.disabled) {
      if (editSlug) resetCreateMode();
      setScreen(tab.dataset.screen);
    }
  });

  $("#btn-new-profile").addEventListener("click", () => {
    resetCreateMode();
    setScreen("create");
  });
  $("#btn-empty-create").addEventListener("click", () => {
    resetCreateMode();
    setScreen("create");
  });
  $("#btn-import-modpack").addEventListener("click", importModpack);
  $("#btn-browse-modpacks").addEventListener("click",
    () => openBrowser("modpack"));
  $("#profile-list").addEventListener("scroll", () => {
    hideProfileTip();
    hideProfileMenu();
  });
  window.addEventListener("resize", () => {
    hideProfileTip();
    hideProfileMenu();
    updateAllSegFills(true);
    updateAllSegHovers();
  });

  $("#player-name").addEventListener("keydown", (event) => {
    if (event.key === "Enter") addOfflineAccount();
  });
  $("#btn-add-offline").addEventListener("click", addOfflineAccount);
  $("#account-list").addEventListener("click", (event) => {
    const use = event.target.closest("button[data-account-use]");
    if (use) {
      selectAccount(use.dataset.accountUse);
      return;
    }
    const remove = event.target.closest("button[data-account-remove]");
    if (remove) removeAccount(remove.dataset.accountRemove);
  });

  $("#ram-down").addEventListener("click", () => changeRam(-1));
  $("#ram-up").addEventListener("click", () => changeRam(1));
  $("#btn-play").addEventListener("click", play);
  $("#btn-stop").addEventListener("click", stopGame);
  $("#btn-restart").addEventListener("click", restartGame);
  $("#profile-menu").addEventListener("click", (event) => {
    const item = event.target.closest("[data-profile-action]");
    if (!item || item.disabled) return;
    const action = item.dataset.profileAction;
    if (action === "delete") {
      onDelete();
      return;
    }
    hideProfileMenu();
    runProfileMenuAction(action);
  });
  document.addEventListener("mousedown", (event) => {
    const menu = $("#profile-menu");
    if (!menu || !menu.classList.contains("open")) return;
    if (event.target.closest("#profile-menu")) return;
    if (event.target.closest(".profile-card")) return;
    hideProfileMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideProfileMenu();
  });
  window.addEventListener("blur", hideProfileMenu);

  $("#detail-tabs").addEventListener("click", (event) => {
    const tab = event.target.closest(".detail-tab");
    if (tab) setDetailPane(tab.dataset.pane);
  });
  $("#btn-pane-update-all").addEventListener("click", updatePaneMods);
  $("#btn-pane-browse-mods").addEventListener("click", () => openBrowser("mod"));
  $("#btn-pane-browse-rp").addEventListener("click",
    () => openBrowser("resourcepack"));
  $("#btn-pane-browse-shaders").addEventListener("click",
    () => openBrowser("shader"));
  $("#btn-pane-open-mods").addEventListener("click", () =>
    call("open_instance", "mods"));
  $("#btn-pane-open-rp").addEventListener("click", () =>
    call("open_instance", "resourcepacks"));
  $("#btn-pane-open-shaders").addEventListener("click", () =>
    call("open_instance", "shaderpacks"));
  $("#btn-pane-backup").addEventListener("click", backupWorlds);
  $("#btn-pane-open-worlds").addEventListener("click", () =>
    call("open_instance", "worlds"));
  $("#btn-pane-open-shots").addEventListener("click", () =>
    call("open_instance", "screenshots"));
  $("#btn-pane-open-game").addEventListener("click", () => call("open", "game"));
  $("#btn-pane-edit").addEventListener("click", openEditProfile);
  $("#btn-apply-version").addEventListener("click", applyVersionChange);
  $("#edit-version").addEventListener("change", () => {
    vedit.mc = $("#edit-version").value;
    loadEditBuilds();
    syncVersionEditor();
  });
  $("#edit-loader").addEventListener("change", () => {
    vedit.loader = $("#edit-loader").value;
    vedit.build = "";
    loadEditBuilds();
  });
  $("#edit-build").addEventListener("change", () => {
    vedit.build = $("#edit-build").value;
    syncVersionEditor();
  });
  $("#btn-pane-settings").addEventListener("click", () => setScreen("settings"));
  $("#btn-pane-icon").addEventListener("click", setProfileIcon);
  $("#btn-pane-clear-icon").addEventListener("click", clearProfileIcon);
  $("#pane-ram-down").addEventListener("click", () => changePaneRam(-1));
  $("#pane-ram-up").addEventListener("click", () => changePaneRam(1));

  $("#default-ram-down").addEventListener("click", () => changeDefaultRam(-1));
  $("#default-ram-up").addEventListener("click", () => changeDefaultRam(1));
  $("#btn-pick-java").addEventListener("click", pickJava);
  $("#btn-auto-java").addEventListener("click", useAutoJava);
  $("#java-path").addEventListener("keydown", (event) => {
    if (event.key === "Enter") applyJavaPath();
  });
  $("#java-path").addEventListener("change", applyJavaPath);
  $("#btn-open-shared").addEventListener("click", () => call("open_shared"));

  $("#btn-ms-login").addEventListener("click", msLogin);
  $("#btn-ms-cancel").addEventListener("click", msCancel);
  $("#account-methods").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-method]");
    if (button) setAccountMethod(button.dataset.method);
  });
  $("#btn-ely-login").addEventListener("click", elyLogin);
  $("#btn-ely-browser").addEventListener("click", elyBrowserLogin);
  $("#btn-ely-cancel").addEventListener("click", elyCancel);
  $("#btn-save-ely-oauth").addEventListener("click", saveElyOauth);
  for (const id of ["ely-oauth-client-id", "ely-oauth-client-secret",
                    "ely-oauth-redirect"]) {
    $("#" + id).addEventListener("keydown", (event) => {
      if (event.key === "Enter") saveElyOauth();
    });
  }
  for (const id of ["ely-username", "ely-password", "ely-totp"]) {
    $("#" + id).addEventListener("keydown", (event) => {
      if (event.key === "Enter") elyLogin();
    });
  }
  $("#btn-save-client-id").addEventListener("click", () => saveMsClientId(true));
  $("#ms-client-id").addEventListener("keydown", (event) => {
    if (event.key === "Enter") saveMsClientId(true);
  });

  $("#version-search").addEventListener("input", () => {
    clearTimeout(versions.searchTimer);
    versions.searchTimer = setTimeout(renderVersions, 160);
  });
  $("#version-filters").addEventListener("change", () => {
    $$("#version-filters input").forEach((box) => {
      if (box.dataset.vtype) versions.filters[box.dataset.vtype] = box.checked;
    });
    renderVersions();
    const count = versions.rows.length;
    screenStatus("create", count
      ? `${count} versions — pick one`
      : "No versions match the selected types.", !count);
  });
  $("#btn-refresh-versions").addEventListener("click", () => loadVersions(true));
  $("#loader-seg").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-loader]");
    if (button) setLoader(button.dataset.loader);
  });
  $("#btn-refresh-builds").addEventListener("click", () => {
    if (loaderSel === "None") {
      screenStatus("create", "Choose a mod loader first.", true);
      return;
    }
    if (versions.selected) loadBuilds();
  });
  $("#btn-create").addEventListener("click", createProfile);
  $("#btn-cancel-create").addEventListener("click", () => {
    call("cancel");
    screenStatus("create", "Cancelling — stopping downloads…");
  });
  $("#btn-clear-create-log").addEventListener("click", clearCreateLog);

  $("#mods-seg").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-loader]");
    if (!button || mods.busy) return;
    mods.loader = button.dataset.loader;
    setSeg("#mods-seg", mods.loader);
    updateScreenHeads();
    mods.searchedKey = "";
    searchMods();
  });
  $("#kind-seg").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-kind]");
    if (button) setBrowserKind(button.dataset.kind);
  });
  $("#btn-mod-search").addEventListener("click", () => {
    mods.searchedKey = "";
    searchMods();
  });
  $("#mods-query").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      mods.searchedKey = "";
      searchMods();
    }
  });
  $("#btn-mod-install").addEventListener("click", installMod);
  $("#btn-mod-uninstall").addEventListener("click", uninstallMod);
  $("#btn-mod-update").addEventListener("click", updateMod);
  $("#btn-mod-update-all").addEventListener("click", updateAllMods);
  $("#btn-mod-install-many").addEventListener("click", installSelected);
  $("#mod-list").addEventListener("scroll", maybeLoadMore);
  $("#btn-open-mods-folder").addEventListener("click", () => {
    if (mods.kind === "resourcepack") call("open_instance", "resourcepacks");
    else if (mods.kind === "shader") call("open_instance", "shaderpacks");
    else call("open", "mods");
  });

  $("#loaders-seg").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-loader]");
    if (!button || S.busy === "loaders") return;
    if (button.dataset.loader === lb.label) return;
    lb.label = button.dataset.loader;
    setSeg("#loaders-seg", lb.label);
    lb.key = "";
    loadLoaderBuilds();
  });
  $("#btn-refresh-loader-builds").addEventListener("click", () => {
    lb.key = "";
    loadLoaderBuilds();
  });
  $("#btn-install-loader").addEventListener("click", installLoader);
  $("#btn-cancel-loader").addEventListener("click", () => {
    call("cancel");
    screenStatus("loaders", "Cancelling…");
  });
  $("#btn-clear-loader-log").addEventListener("click", clearLoaderLog);
  $("#btn-open-loader-folder").addEventListener("click", () => call("open", "game"));

  $("#btn-open-logs-folder").addEventListener("click", () => call("open", "logs"));
  $("#btn-open-log-file").addEventListener("click", () => call("open", "log"));
  $("#btn-clear-logs").addEventListener("click", clearLogsView);
  $("#log-console").addEventListener("scroll", () => {
    const el = $("#log-console");
    logs.stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && screen !== "profiles") setScreen("profiles");
  });

  window.__go = setScreen;
}

let pollBusy = false;

async function pollOnce() {
  if (pollBusy) return;
  pollBusy = true;
  const result = await call("poll");
  pollBusy = false;
  if (!result || !result.events) return;
  for (const event of result.events) handleEvent(event);
  if (typeof result.busy === "string" && result.busy !== S.busy) {
    S.busy = result.busy;
    syncBusy();
    syncMods();
    syncLoaders();
  }
}

function startOrb() {
  const canvas = document.querySelector(".orb");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const size = Math.max(24, Math.round(
    canvas.getBoundingClientRect().width || 42));
  canvas.width = Math.round(size * dpr);
  canvas.height = Math.round(size * dpr);

  const accentHex = getComputedStyle(document.documentElement)
    .getPropertyValue("--accent").trim();
  const hex = /^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(accentHex);
  const rgb = hex
    ? [parseInt(hex[1], 16), parseInt(hex[2], 16), parseInt(hex[3], 16)]
    : [244, 244, 244];
  const strokePrefix = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, `;

  const COUNT = 150;
  const pts = [];
  let max = 0;
  for (let i = 0; i < COUNT; i += 1) {
    const t = (i / COUNT) * Math.PI * 2;
    const p = {
      x: Math.sin(t) + 2 * Math.sin(2 * t),
      y: Math.cos(t) - 2 * Math.cos(2 * t),
      z: -Math.sin(3 * t),
    };
    max = Math.max(max, Math.hypot(p.x, p.y, p.z));
    pts.push(p);
  }
  for (const p of pts) {
    p.x /= max;
    p.y /= max;
    p.z /= max;
  }

  function frame(now) {
    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const R = Math.min(w, h) * 0.4 * (1 + 0.03 * Math.sin(now * 0.0006));
    const a = now * 0.00028;
    const b = now * 0.00016;
    const ca = Math.cos(a);
    const sa = Math.sin(a);
    const cb = Math.cos(b);
    const sb = Math.sin(b);

    ctx.clearRect(0, 0, w, h);
    ctx.lineWidth = Math.max(1.2, dpr * 1.6);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";

    let prev = null;
    for (let i = 0; i <= COUNT; i += 1) {
      const p = pts[i % COUNT];
      const x1 = p.x * ca + p.z * sa;
      const z1 = -p.x * sa + p.z * ca;
      const y1 = p.y * cb - z1 * sb;
      const z2 = p.y * sb + z1 * cb;
      const k = 3.2 / (3.2 + z2);
      const cur = {
        x: cx + x1 * R * k,
        y: cy + y1 * R * k,
        z: z2,
      };
      if (prev) {
        const depth = 0.3 + 0.65 * (1 - (prev.z + cur.z + 2) / 4);
        ctx.strokeStyle = `${strokePrefix}${depth.toFixed(3)})`;
        ctx.beginPath();
        ctx.moveTo(prev.x, prev.y);
        ctx.lineTo(cur.x, cur.y);
        ctx.stroke();
      }
      prev = cur;
    }

    if (!reduce) requestAnimationFrame(frame);
  }
  frame(reduce ? 1200 : performance.now());
}

async function boot() {
  if (booted) return;
  if (!api()) return;
  booted = true;
  bind();
  initSegHover();
  await refreshState();
  setScreen("profiles");
  setInterval(pollOnce, 160);
  if (!S.instances.length) {
    setStatus("Create a profile to get started.");
  } else {
    setStatus("Ready.");
  }
}

bind();
startOrb();
if (window.pywebview && window.pywebview.api) boot();
window.addEventListener("pywebviewready", boot);
