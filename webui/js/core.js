"use strict";

window.__errors = [];
const reportedErrors = new Set();

function reportError(text) {
  const message = String(text);
  window.__errors.push(message);
  try {
    // Uncaught page errors are crashes the user should actually see, not just
    // a line in the console.
    showErrorToast(message, "Crash");
  } catch (_) { /* the error handler must never throw itself */ }
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

const SOURCE_LABELS = { modrinth: "Modrinth", curseforge: "CurseForge" };

const CONTENT_KINDS = {
  mod: {
    title: "Mods", plural: "mods", unit: "mod",
    placeholder: "Search mods by name",
    install: "Install", select: "Select a mod",
  },
  resourcepack: {
    title: "Resource packs", plural: "resource packs", unit: "resource pack",
    placeholder: "Search resource packs by name",
    install: "Install", select: "Select a resource pack",
  },
  shader: {
    title: "Shaders", plural: "shaders", unit: "shader pack",
    placeholder: "Search shaders by name",
    install: "Install", select: "Select a shader pack",
  },
  modpack: {
    title: "Modpacks", plural: "modpacks", unit: "modpack",
    placeholder: "Search modpacks by name",
    install: "Add profile", select: "Select a modpack",
  },
};

let S = {
  instances: [], selected: "", instance: null,
  player: "", ram: 2, default_ram: 2, java: "", ms: {}, ely: {}, nexi: {},
  accounts: [], active_account: "", account: "offline", paths: {},
  busy: "", launching: false, launching_slugs: [], game_running: false,
  game_instance: "", running: [], theme: "mint",
  color_mode: "dark", language: "en", pet: "axi", version: "",
  curseforge_key_set: false,
};
let screen = "home";
let booted = false;

const msFlow = { active: false };
const elyFlow = { active: false };
const nexiFlow = { active: false, login: "", email: "" };
let accountMethod = "microsoft";

const versions = {
  loaded: false, loading: false, all: [], installed: new Set(),
  rows: [], selected: "", query: "",
  /* Releases only by default; the button under MINECRAFT VERSION widens the
     list to snapshots, old betas and old alphas. */
  showAll: false,
};
let loaderSel = "None";
let editSlug = "";
const builds = { list: [], selected: -1, loading: false, request: 0 };
/* Version & loader editor in the profile settings pane. */
const vedit = { key: "", mc: "", loader: "any", build: "", origMc: "",
                req: 0, busy: false, optionsFor: "" };

const mods = { hits: [], selected: -1, loader: "any", game: "", kind: "mod",
               source: "modrinth",
               key: "", searchedKey: "", busy: false, installed: null,
               statusSeq: 0, statusLoading: false, profile: "",
               checked: new Set(), checkedHits: new Map(), query: "", offset: 0, total: 0,
               searchActive: false, pendingSearch: null,
               loadingMore: false, searchSeq: 0 };
/* Each profile keeps its own mod browser: search text, results and selection. */
const browserStates = new Map();
const detail = { slug: "", contents: null, loading: false, pane: "mods",
                 request: 0 };
let iconsKey = "";
const lb = { label: "Fabric", builds: [], selected: -1, key: "", loading: false, busy: false,
             statusText: "", statusError: false, startedAt: 0, ticker: null };
const logs = {
  pending: "", buffer: [], timer: null, stick: true,
  el: "#log-console",
  visible: () => screen === "settings" && settingsTab === "logs"
    && logsTab === "launcher",
};
const gameLogs = {
  pending: "", buffer: [], timer: null, stick: true,
  el: "#game-log-console",
  visible: () => screen === "profiles" && detail.pane === "logs",
};
/* Screenshot previews: the grid rechecks the folder while it is visible and
   re-renders only when a new file or a size changes. */
const shots = { timer: null, key: "", open: null };

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
    const result = (await bridge[method](...args)) ?? {};
    // Bridge methods report failures as {ok: false, error}. Show them even if
    // the caller only puts the message in the status bar. Polling is exempt:
    // if the backend dies it fails continuously and one toast is enough.
    if (method !== "poll" && result && result.error) {
      showErrorToast(result.error, "Launcher error");
    }
    return result;
  } catch (err) {
    const message = String((err && err.message) || err);
    showErrorToast(message, "Launcher error");
    return { error: message };
  }
}

function elem(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

/* Played seconds, rendered like "12 h 34 min"; the i18n layer translates it. */
function formatPlaytime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours && minutes) return `${hours} h ${minutes} min`;
  if (hours) return `${hours} h`;
  if (minutes) return `${minutes} min`;
  return total > 0 ? "< 1 min" : "0 min";
}

/* Icon sprite node for markup created at runtime. */
function iconNode(id) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "icon");
  const use = document.createElementNS(ns, "use");
  use.setAttribute("href", "#" + id);
  svg.appendChild(use);
  return svg;
}

function setStatus(text, error = false) {
  const bar = $("#status");
  bar.textContent = text;
  bar.classList.toggle("error", !!error);
  if (error && text) showErrorToast(text, "Error");
}

function screenStatus(name, text, error = false) {
  const id = { create: "#create-status", mods: "#mods-status", loaders: "#loaders-status" }[name];
  const node = id && $(id);
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("error", !!error);
  if (error && text) showErrorToast(text, "Error");
}

/* ---------------------------------------------------------------- toasts */

/* Small cards in the lower-right corner for crashes and failed actions.
   They auto-dismiss, pause while the pointer is over them, and keep the last
   few messages on screen. Built with plain DOM calls so the global error
   handler can use them even very early in page load. */
const toastHistory = new Map();

function toastMessage(value) {
  const text = String(value == null ? "" : value).replace(/\r/g, "").trim();
  return text.length > 600 ? `${text.slice(0, 597)}…` : text;
}

function toastIcon(id, cls) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", cls ? `icon ${cls}` : "icon");
  const use = document.createElementNS(ns, "use");
  use.setAttribute("href", "#" + id);
  svg.appendChild(use);
  return svg;
}

function dismissToast(node) {
  if (!node || node.classList.contains("leaving") || !node.isConnected) return;
  node.classList.add("leaving");
  window.setTimeout(() => node.remove(), 180);
}

function showErrorToast(message, title = "Error") {
  const text = toastMessage(message);
  const stack = document.getElementById("toast-stack");
  if (!text || !stack) return;
  const now = Date.now();
  const seen = toastHistory.get(text);
  if (seen && now - seen < 4000) return;
  toastHistory.set(text, now);
  for (const [key, stamp] of toastHistory) {
    if (now - stamp > 60000) toastHistory.delete(key);
  }

  const node = document.createElement("div");
  node.className = "toast";
  node.setAttribute("role", "alert");
  const body = document.createElement("div");
  body.className = "toast-body";
  const heading = document.createElement("div");
  heading.className = "toast-title";
  heading.textContent = String(title || "Error");
  const line = document.createElement("div");
  line.className = "toast-text";
  line.textContent = text;
  body.append(heading, line);
  const close = document.createElement("button");
  close.className = "toast-close";
  close.type = "button";
  close.title = "Dismiss";
  close.setAttribute("aria-label", "Dismiss notification");
  close.appendChild(toastIcon("i-x"));
  close.addEventListener("click", () => dismissToast(node));
  node.append(toastIcon("i-alert", "toast-icon"), body, close);
  stack.appendChild(node);
  // The stack is intentionally small: the oldest cards go first.
  while (stack.children.length > 4) stack.firstElementChild.remove();

  let timer = window.setTimeout(() => dismissToast(node), 9000);
  node.addEventListener("pointerenter", () => window.clearTimeout(timer));
  node.addEventListener("pointerleave", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => dismissToast(node), 2500);
  });
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
  return `${mods.kind}|${mods.source}|${instanceKey()}`;
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
    const key = button.dataset.loader ?? button.dataset.kind
      ?? button.dataset.source;
    button.classList.toggle("on", key === value);
  });
  updateSegFill($(selector));
}

/* ------------------------------------------- sliding active fill for tabs */

const FILL_CONTAINERS = [
  "#tabs", "#detail-tabs", "#account-methods", "#skin-seg",
  "#kind-seg", "#source-seg", "#loader-seg", "#mods-seg", "#loaders-seg",
  "#mode-seg", "#lang-seg", "#pet-seg", "#settings-tabs", "#logs-tabs",
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

/* ----------------------------------------- custom dropdowns for <select> */

/* Every native select stays in the DOM (hidden) so all existing code that
   sets .value/.disabled, rebuilds options or listens for change keeps
   working untouched; the custom button and menu mirror it. */
function syncVsel(select) {
  const wrap = select.parentElement;
  if (!wrap || !wrap.classList.contains("vsel")) return;
  const option = select.options[select.selectedIndex];
  const label = wrap.querySelector(".vsel-label");
  if (label) label.textContent = option ? option.text : "";
  const btn = wrap.querySelector(".vsel-btn");
  if (btn) btn.disabled = select.disabled;
  for (const item of wrap.querySelectorAll(".vsel-option")) {
    item.classList.toggle("selected", item.dataset.value === select.value);
  }
}

function renderVselMenu(select) {
  const wrap = select.parentElement;
  if (!wrap || !wrap.classList.contains("vsel")) return;
  const menu = wrap.querySelector(".vsel-menu");
  menu.replaceChildren();
  for (const option of select.options) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "vsel-option";
    item.setAttribute("role", "option");
    item.dataset.value = option.value;
    item.appendChild(elem("span", "", option.text));
    item.appendChild(iconNode("i-check"));
    menu.appendChild(item);
  }
  syncVsel(select);
}

function closeVsel(wrap) {
  if (!wrap || !wrap.classList.contains("open")) return;
  wrap.classList.remove("open");
  const btn = wrap.querySelector(".vsel-btn");
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function upgradeSelect(select) {
  if (select.dataset.vsel) return;
  select.dataset.vsel = "1";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "vsel-btn";
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-expanded", "false");
  const ariaLabel = select.getAttribute("aria-label");
  if (ariaLabel) btn.setAttribute("aria-label", ariaLabel);
  btn.appendChild(elem("span", "vsel-label"));
  btn.appendChild(iconNode("i-chev"));

  const menu = document.createElement("div");
  menu.className = "vsel-menu";
  menu.setAttribute("role", "listbox");
  menu.setAttribute("data-i18n-skip", "");

  const wrap = document.createElement("div");
  wrap.className = "vsel";
  wrap.appendChild(btn);
  wrap.appendChild(menu);
  // The button must precede the hidden select inside the wrapper so a
  // wrapping <label> forwards its click to the button, not to the invisible
  // native control.
  select.parentNode.insertBefore(wrap, select);
  wrap.appendChild(select);
  select.classList.add("vsel-native");

  /* Mirror value/disabled writes so existing code keeps working while the
     custom UI stays in sync. */
  const proto = HTMLSelectElement.prototype;
  const nativeValue = Object.getOwnPropertyDescriptor(proto, "value");
  const nativeDisabled = Object.getOwnPropertyDescriptor(proto, "disabled");
  Object.defineProperty(select, "value", {
    configurable: true,
    get: () => nativeValue.get.call(select),
    set: (value) => {
      nativeValue.set.call(select, value);
      syncVsel(select);
    },
  });
  Object.defineProperty(select, "disabled", {
    configurable: true,
    get: () => nativeDisabled.get.call(select),
    set: (value) => {
      nativeDisabled.set.call(select, value);
      syncVsel(select);
    },
  });

  btn.addEventListener("click", () => {
    if (select.disabled) return;
    const open = wrap.classList.toggle("open");
    btn.setAttribute("aria-expanded", String(open));
    if (!open) return;
    const selected = menu.querySelector(".vsel-option.selected");
    if (selected) {
      menu.scrollTop = Math.max(0,
        selected.offsetTop - menu.clientHeight / 2);
    }
  });
  menu.addEventListener("click", (event) => {
    const item = event.target.closest(".vsel-option");
    closeVsel(wrap);
    if (!item || select.disabled) return;
    if (item.dataset.value !== select.value) {
      select.value = item.dataset.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
  wrap.addEventListener("keydown", (event) => {
    if (!wrap.classList.contains("open")) return;
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = [...menu.querySelectorAll(".vsel-option")];
    if (!items.length) return;
    event.preventDefault();
    const index = items.indexOf(document.activeElement);
    const step = event.key === "ArrowDown" ? 1 : -1;
    const next = index < 0
      ? items[0]
      : items[(index + step + items.length) % items.length];
    next.focus();
  });

  new MutationObserver(() => renderVselMenu(select)).observe(select, {
    childList: true, subtree: true, characterData: true,
  });
  renderVselMenu(select);
}

function upgradeSelects() {
  $$("select").forEach(upgradeSelect);
}
