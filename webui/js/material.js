"use strict";

/* =========================================================================
   M3 Expressive glue
   Nexi keeps its own markup and event wiring, but the M3 Expressive design
   uses Google's real building blocks on top of it:
     - @material/web 2.5 (official web components, bundled locally)
     - @material/material-color-utilities (official Expressive colour engine)
     - Material Symbols Rounded (official Google SVG assets)
     - Roboto Flex (official variable typeface, bundled for offline use)
   The DOM is only adapted where that can be done without touching the
   launcher's handlers: segmented controls, progress bars, cards, ripples and
   icon glyphs. Classic mode receives no Material component at all.
   ========================================================================= */

const M3_ICON_MAP = {
  "i-profile": "person",
  "i-users": "group",
  "i-builds": "inventory_2",
  "i-home": "home",
  "i-stop": "stop_circle",
  "i-world": "public",
  "i-plus": "add",
  "i-mods": "extension",
  "i-layers": "layers",
  "i-logs": "description",
  "i-skin": "checkroom",
  "i-folder": "folder_open",
  "i-refresh": "refresh",
  "i-play": "play_arrow",
  "i-clock": "schedule",
  "i-trash": "delete",
  "i-x": "close",
  "i-min": "remove",
  "i-max": "crop_square",
  "i-restore": "filter_none",
  "i-gear": "settings",
  "i-edit": "edit",
  "i-copy": "content_copy",
  "i-archive": "archive",
  "i-check": "check",
  "i-spark": "auto_awesome",
  "i-chev": "keyboard_arrow_down",
  "i-import": "file_download",
  "i-image": "image",
  "i-palette": "palette",
  "i-network": "lan",
  "i-alert": "error",
};

function m3DesignActive() {
  return document.documentElement.dataset.design === "material";
}

/* If the bundled runtime failed to load, never create half-upgraded tags:
   an undefined custom element would render as plain inline text content. */
function m3Ready(name) {
  return Boolean(window.customElements && customElements.get(name));
}

function materialIconHref(id) {
  const name = M3_ICON_MAP[id];
  return m3DesignActive() && name ? `#m3-${name}` : `#${id}`;
}

/* For the few places that swap a glyph after construction (play/stop,
   maximize/restore): keeps the classic id for the way back. */
function setIconHref(use, id) {
  if (!use) return;
  const href = materialIconHref(id);
  use.dataset.classicHref = "#" + id;
  use.setAttribute("href", href);
  const svg = use.closest("svg");
  if (svg) svg.classList.toggle("m3-icon", href.startsWith("#m3-"));
}

/* Runtime icons are created by core.js through iconNode()/toastIcon(); those
   call materialIconHref(), so only markup that already exists has to be
   walked when the design changes. */
function syncMaterialIcons() {
  const on = m3DesignActive();
  for (const use of document.querySelectorAll("svg.icon use")) {
    const href = use.getAttribute("href") || "";
    let classic = use.dataset.classicHref;
    if (!classic && !href.startsWith("#m3-")) classic = href;
    if (!classic) continue;
    use.dataset.classicHref = classic;
    const base = classic.replace(/^#/, "");
    const name = M3_ICON_MAP[base];
    if (!name) continue;
    use.setAttribute("href", on ? `#m3-${name}` : classic);
    const svg = use.closest("svg");
    if (svg) svg.classList.toggle("m3-icon", on);
  }
}

/* ---------------------------------------------------- M3 Expressive colours */

const M3_ROLES = [
  "primary", "onPrimary", "primaryContainer", "onPrimaryContainer",
  "secondary", "onSecondary", "secondaryContainer", "onSecondaryContainer",
  "tertiary", "onTertiary", "tertiaryContainer", "onTertiaryContainer",
  "error", "onError", "errorContainer", "onErrorContainer",
  "background", "onBackground", "surface", "onSurface",
  "surfaceVariant", "onSurfaceVariant", "surfaceDim", "surfaceBright",
  "surfaceContainerLowest", "surfaceContainerLow", "surfaceContainer",
  "surfaceContainerHigh", "surfaceContainerHighest", "outline",
  "outlineVariant", "inverseSurface", "inverseOnSurface", "inversePrimary",
  "shadow", "scrim", "surfaceTint",
];

function m3TokenName(role) {
  return `--md-sys-color-${role.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`;
}

function m3HexToRgbTriplet(hex) {
  const value = String(hex || "").replace("#", "");
  if (value.length !== 6) return null;
  const int = Number.parseInt(value, 16);
  if (!Number.isFinite(int)) return null;
  return `${(int >> 16) & 255}, ${(int >> 8) & 255}, ${int & 255}`;
}

function clearMaterialTokens() {
  const root = document.documentElement;
  for (const role of M3_ROLES) root.style.removeProperty(m3TokenName(role));
  root.style.removeProperty("--accent-rgb");
  root.style.removeProperty("--danger-rgb");
}

/* Colour roles come from Google's Material Color Utilities: the seed is the
   accent picked in Appearance, run through the Vibrant scheme (the expressive
   palette that keeps the chosen hue and enriches its containers), once for
   dark and once for light. */
function applyMaterialTokens() {
  const api = window.NexiMaterial;
  if (!api || !m3DesignActive()) return;
  const root = document.documentElement;
  const seed = getComputedStyle(root).getPropertyValue("--seed").trim()
    || "#5cd6a4";
  let argb;
  try {
    argb = api.argbFromHex(seed);
  } catch {
    return;
  }
  if (!Number.isFinite(argb)) return;
  const dark = root.dataset.mode === "light" ? false : true;
  const scheme = new api.SchemeVibrant(api.Hct.fromInt(argb), dark, 0);
  for (const role of M3_ROLES) {
    const color = api.MaterialDynamicColors[role];
    if (!color || typeof color.getArgb !== "function") continue;
    root.style.setProperty(
      m3TokenName(role), api.hexFromArgb(color.getArgb(scheme)));
  }
  const primary = api.hexFromArgb(
    api.MaterialDynamicColors.primary.getArgb(scheme));
  const error = api.hexFromArgb(
    api.MaterialDynamicColors.error.getArgb(scheme));
  const primaryRgb = m3HexToRgbTriplet(primary);
  const errorRgb = m3HexToRgbTriplet(error);
  if (primaryRgb) root.style.setProperty("--accent-rgb", primaryRgb);
  if (errorRgb) root.style.setProperty("--danger-rgb", errorRgb);
}

function refreshMaterialTokens() {
  if (m3DesignActive()) applyMaterialTokens();
  else clearMaterialTokens();
}

/* ------------------------------------------------- official segmented buttons */

const M3_SEG_EXCLUDED = new Set(["settings-tabs", "logs-tabs", "detail-tabs"]);
const m3SegObservers = new WeakMap();
const m3SegSyncQueue = new Set();
let m3SegSyncScheduled = false;

function m3SegmentEligible(seg) {
  if (!(seg instanceof HTMLElement) || seg.classList.contains("m3-seg")) {
    return false;
  }
  if (seg.id && M3_SEG_EXCLUDED.has(seg.id)) return false;
  if (seg.classList.contains("settings-tabs")
      || seg.classList.contains("detail-tabs")) return false;
  return Boolean(seg.querySelector(":scope > button"));
}

function m3SegmentButton(button) {
  const node = document.createElement("md-outlined-segmented-button");
  node.label = (button.textContent || "").trim();
  node.selected = button.classList.contains("on")
    || button.classList.contains("active");
  node.disabled = button.disabled;
  const icon = button.querySelector("img, svg");
  if (icon) {
    const clone = icon.cloneNode(true);
    clone.setAttribute("slot", "icon");
    clone.classList.add("m3-seg-icon");
    node.appendChild(clone);
    node.hasIcon = true;
  }
  return node;
}

function syncMaterialSegment(seg) {
  const set = seg.querySelector(
    ":scope > md-outlined-segmented-button-set");
  if (!set) return;
  const buttons = [...seg.querySelectorAll(":scope > button")];
  const nodes = [...set.querySelectorAll(
    ":scope > md-outlined-segmented-button")];
  if (buttons.length !== nodes.length) {
    refreshMaterialSegment(seg);
    return;
  }
  buttons.forEach((button, index) => {
    const node = nodes[index];
    const label = (button.textContent || "").trim();
    if (node.label !== label) node.label = label;
    node.selected = button.classList.contains("on")
      || button.classList.contains("active");
    node.disabled = button.disabled;
  });
}

function scheduleMaterialSegmentSync(seg) {
  m3SegSyncQueue.add(seg);
  if (m3SegSyncScheduled) return;
  m3SegSyncScheduled = true;
  requestAnimationFrame(() => {
    m3SegSyncScheduled = false;
    const queue = [...m3SegSyncQueue];
    m3SegSyncQueue.clear();
    for (const item of queue) {
      if (item.isConnected && item.classList.contains("m3-seg")) {
        syncMaterialSegment(item);
      }
    }
  });
}

function upgradeMaterialSegment(seg) {
  const buttons = [...seg.querySelectorAll(":scope > button")];
  if (!buttons.length) return;
  const set = document.createElement("md-outlined-segmented-button-set");
  set.className = "m3-segmented";
  const label = seg.getAttribute("aria-label");
  if (label) set.setAttribute("aria-label", label);
  for (const button of buttons) set.appendChild(m3SegmentButton(button));
  seg.classList.add("m3-seg");
  seg.appendChild(set);
  set.addEventListener("segmented-button-set-selection", (event) => {
    const index = event.detail && event.detail.index;
    const button = Number.isInteger(index) ? buttons[index] : null;
    if (!button || button.disabled) return;
    // The launcher's delegated click handler stays the source of truth.
    button.click();
    scheduleMaterialSegmentSync(seg);
  });
  // Only the launcher's own buttons matter; the component updates its own
  // attributes (label/selected) inside the set and must not re-trigger this.
  const observer = new MutationObserver((records) => {
    const external = records.some((record) => {
      const node = record.target;
      return !(node instanceof Element
        && node.closest("md-outlined-segmented-button-set"));
    });
    if (external) scheduleMaterialSegmentSync(seg);
  });
  observer.observe(seg, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["class", "disabled"],
  });
  m3SegObservers.set(seg, observer);
  syncMaterialSegment(seg);
}

function refreshMaterialSegment(seg) {
  const observer = m3SegObservers.get(seg);
  if (observer) {
    observer.disconnect();
    m3SegObservers.delete(seg);
  }
  seg.querySelector(":scope > md-outlined-segmented-button-set")?.remove();
  seg.classList.remove("m3-seg");
  upgradeMaterialSegment(seg);
}

function upgradeMaterialSegments() {
  if (!m3Ready("md-outlined-segmented-button-set")) return;
  for (const seg of document.querySelectorAll(".seg")) {
    if (m3SegmentEligible(seg)) upgradeMaterialSegment(seg);
  }
}

function downgradeMaterialSegments() {
  for (const seg of document.querySelectorAll(".seg.m3-seg")) {
    const observer = m3SegObservers.get(seg);
    if (observer) {
      observer.disconnect();
      m3SegObservers.delete(seg);
    }
    seg.querySelector(":scope > md-outlined-segmented-button-set")?.remove();
    seg.classList.remove("m3-seg");
  }
  m3SegSyncQueue.clear();
}

/* ------------------------------------------------------ official progress bars */

const m3ProgressObservers = new WeakMap();
let m3LinearSheet = null;

/* @material/web 2.5 predates the 2024 M3 spec, which gives the active
   indicator rounded ends. The track shape is already a token; apply the same
   corner to the indicator inside Google's own shadow root instead of painting
   a bar of our own. */
function m3LinearStyleSheet() {
  if (!m3LinearSheet) {
    m3LinearSheet = new CSSStyleSheet();
    m3LinearSheet.replaceSync(
      ".bar-inner, .inactive-track {"
      + " border-radius: var(--_track-shape, 9999px); }");
  }
  return m3LinearSheet;
}

function m3StyleLinearProgress(progress) {
  const root = progress.shadowRoot;
  if (!root || root.__m3Styled) return;
  try {
    root.adoptedStyleSheets = [...root.adoptedStyleSheets, m3LinearStyleSheet()];
    root.__m3Styled = true;
  } catch (_) {
    /* Leave Google's default corners if the engine rejects the sheet. */
  }
}

function syncMaterialProgress(bar, progress) {
  const indeterminate = bar.classList.contains("indeterminate");
  progress.indeterminate = indeterminate;
  progress.classList.toggle("m3-indeterminate", indeterminate);
  if (indeterminate) {
    progress.removeAttribute("value");
    return;
  }
  const width = Number.parseFloat(bar.style.width);
  progress.value = Number.isFinite(width)
    ? Math.max(0, Math.min(1, width / 100)) : 0;
}

function upgradeMaterialProgress() {
  if (!m3Ready("md-linear-progress")) return;
  for (const wrap of document.querySelectorAll(".progress")) {
    if (wrap.classList.contains("m3-progress")) continue;
    const bar = wrap.querySelector(":scope > .bar");
    if (!bar) continue;
    const progress = document.createElement("md-linear-progress");
    progress.className = "m3-linear-progress";
    const stop = document.createElement("span");
    stop.className = "m3-progress-stop";
    stop.setAttribute("aria-hidden", "true");
    wrap.classList.add("m3-progress");
    wrap.append(progress, stop);
    m3StyleLinearProgress(progress);
    const observer = new MutationObserver(
      () => syncMaterialProgress(bar, progress));
    observer.observe(bar, { attributes: true, attributeFilter: ["style", "class"] });
    m3ProgressObservers.set(wrap, observer);
    syncMaterialProgress(bar, progress);
  }
}

function downgradeMaterialProgress() {
  for (const wrap of document.querySelectorAll(".progress.m3-progress")) {
    m3ProgressObservers.get(wrap)?.disconnect();
    m3ProgressObservers.delete(wrap);
    wrap.querySelector(":scope > md-linear-progress")?.remove();
    wrap.querySelector(":scope > .m3-progress-stop")?.remove();
    wrap.classList.remove("m3-progress");
  }
}

/* ------------------------------------------------------- official cards */

function upgradeMaterialCards() {
  if (!m3Ready("md-elevated-card")) return;
  for (const el of document.querySelectorAll(".card:not(md-elevated-card)")) {
    if (el.closest("md-elevated-card")) continue;
    const card = document.createElement("md-elevated-card");
    for (const attr of [...el.attributes]) {
      card.setAttribute(attr.name, attr.value);
    }
    card.dataset.m3CardTag = el.tagName.toLowerCase();
    while (el.firstChild) card.appendChild(el.firstChild);
    el.replaceWith(card);
  }
}

function downgradeMaterialCards() {
  for (const card of document.querySelectorAll("md-elevated-card")) {
    const tag = card.dataset.m3CardTag || "section";
    const el = document.createElement(tag);
    for (const attr of [...card.attributes]) {
      if (attr.name === "data-m3-card-tag") continue;
      el.setAttribute(attr.name, attr.value);
    }
    while (card.firstChild) el.appendChild(card.firstChild);
    card.replaceWith(el);
  }
}

/* ------------------------------------------------- official ripple / state layers */

const M3_RIPPLE_TARGETS = "button, .profile-card, .account-item, "
  + ".theme-option, .pane-row, .tab, .detail-tab, .ctx-item, "
  + ".home-build, .home-world";

function upgradeMaterialRipples() {
  if (!m3Ready("md-ripple")) return;
  for (const el of document.querySelectorAll(M3_RIPPLE_TARGETS)) {
    if (el.hasAttribute("data-m3-upgraded")) continue;
    if (el.closest("md-outlined-segmented-button-set")) continue;
    if (el.closest(".seg.m3-seg")) continue;
    if (el.classList.contains("m3-seg")) continue;
    if (el.classList.contains("seg-fill") || el.classList.contains("seg-hover")) {
      continue;
    }
    if (el.querySelector(":scope > md-ripple")) continue;
    const ripple = document.createElement("md-ripple");
    ripple.className = "m3-ripple";
    if ("disabled" in el && el.disabled) ripple.disabled = true;
    el.classList.add("m3-ripple-host");
    el.appendChild(ripple);
  }
}

function downgradeMaterialRipples() {
  for (const ripple of document.querySelectorAll(".m3-ripple")) {
    ripple.parentElement?.classList.remove("m3-ripple-host");
    ripple.remove();
  }
}

/* ------------------------------------------------ official buttons & FABs */

const m3ButtonObservers = new WeakMap();

function m3SyncButtonIcon(native, host) {
  const source = native.querySelector("svg, img");
  const clone = host.querySelector(".m3-control-icon");
  if (!source || !clone) return;
  const sourceUse = source.querySelector("use");
  const cloneUse = clone.querySelector("use");
  if (sourceUse && cloneUse) {
    const href = sourceUse.getAttribute("href") || "";
    if (cloneUse.getAttribute("href") !== href) cloneUse.setAttribute("href", href);
  } else if (source.tagName === "IMG" && clone.tagName === "IMG") {
    if (clone.getAttribute("src") !== source.getAttribute("src")) {
      clone.setAttribute("src", source.getAttribute("src") || "");
    }
  }
}

function m3IsIconOnly(native) {
  return !(native.textContent || "").trim()
    && Boolean(native.querySelector("svg, img"));
}

function m3ButtonTag(native) {
  if (native.matches(".side > .btn")) return "md-fab";
  if (native.classList.contains("link")) return "md-text-button";
  if (m3IsIconOnly(native)) {
    if (native.classList.contains("primary")) return "md-filled-icon-button";
    if (native.classList.contains("ghost")) {
      return "md-filled-tonal-icon-button";
    }
    if (native.classList.contains("danger")) {
      return "md-outlined-icon-button";
    }
    return "md-icon-button";
  }
  if (native.classList.contains("primary")) return "md-filled-button";
  if (native.classList.contains("ghost")) return "md-filled-tonal-button";
  return "md-outlined-button";
}

function m3TagHasLabel(tag) {
  return tag === "md-filled-button" || tag === "md-filled-tonal-button"
    || tag === "md-outlined-button" || tag === "md-text-button";
}

function m3TagUsesIconSlot(tag) {
  return !tag.endsWith("-icon-button");
}

const M3_BUTTON_CLASS_SKIP = new Set([
  "btn", "primary", "ghost", "danger", "sm", "hidden", "on", "confirm",
  "m3-button", "m3-fab", "is-sm",
]);

function m3SyncButtonClasses(native, host) {
  const wanted = [...native.classList].filter(
    (name) => !M3_BUTTON_CLASS_SKIP.has(name));
  if (native.classList.contains("sm")) wanted.push("is-sm");
  for (const name of [...host.classList]) {
    if (name === "m3-button" || name === "m3-fab") continue;
    if (!wanted.includes(name)) host.classList.remove(name);
  }
  for (const name of wanted) host.classList.add(name);
  host.classList.toggle("on", native.classList.contains("on"));
  host.classList.toggle("confirm", native.classList.contains("confirm"));
}

function m3BuildButton(native) {
  const tag = m3ButtonTag(native);
  const isFab = tag === "md-fab";
  const iconButton = tag.endsWith("-icon-button");
  const host = document.createElement(tag);
  host.className = "m3-button";
  if (isFab) host.classList.add("m3-fab");
  if (iconButton) host.classList.add("m3-icon-button");
  const icon = native.querySelector("svg, img");
  if (icon) {
    const clone = icon.cloneNode(true);
    if (m3TagUsesIconSlot(tag)) clone.setAttribute("slot", "icon");
    clone.classList.add("m3-control-icon");
    host.appendChild(clone);
  }
  if (m3TagHasLabel(tag)) {
    const label = document.createElement("span");
    label.className = "m3-label";
    host.appendChild(label);
  }
  host.__m3Native = native;
  native.__m3Host = host;
  host.addEventListener("click", (event) => {
    if (event.target === native || native.disabled) return;
    native.click();
  });
  return host;
}

function m3SyncButton(native) {
  let host = native.__m3Host;
  if (!host) return;
  const tag = m3ButtonTag(native);
  if (host.tagName.toLowerCase() !== tag) {
    const replacement = m3BuildButton(native);
    if (host.parentNode) host.replaceWith(replacement);
    else native.parentNode?.insertBefore(replacement, native);
    host = replacement;
  }
  const isFab = tag === "md-fab";
  const label = (native.textContent || "").trim();
  const labelNode = host.querySelector(".m3-label");
  if (labelNode && labelNode.textContent !== label) labelNode.textContent = label;
  const hidden = native.classList.contains("hidden") || native.hidden;
  host.classList.toggle("hidden", hidden);
  host.toggleAttribute("disabled", native.disabled);
  if ("disabled" in host) host.disabled = native.disabled;
  const aria = native.getAttribute("aria-label");
  if (aria) host.setAttribute("aria-label", aria);
  else host.removeAttribute("aria-label");
  if (native.title) host.title = native.title;
  else host.removeAttribute("title");
  m3SyncButtonClasses(native, host);
  m3SyncButtonIcon(native, host);
  if (native.id === "btn-play") {
    const starting = native.classList.contains("starting");
    const icon = host.querySelector(":scope > .m3-control-icon");
    let spinner = host.querySelector(":scope > md-circular-progress");
    if (starting && m3Ready("md-circular-progress")) {
      if (!spinner) {
        spinner = document.createElement("md-circular-progress");
        spinner.className = "m3-button-spinner";
        spinner.setAttribute("slot", "icon");
        spinner.indeterminate = true;
        host.appendChild(spinner);
      }
      spinner.indeterminate = true;
      if (icon) icon.style.display = "none";
    } else if (spinner) {
      spinner.remove();
      if (icon) icon.style.display = "";
    }
  }
  if (isFab) {
    const variant = native.classList.contains("primary") ? "primary" : "secondary";
    if (host.variant !== variant) host.variant = variant;
  }
}

function upgradeMaterialButton(native) {
  if (native.dataset.m3Upgraded) return;
  if (native.closest(".seg, md-outlined-segmented-button-set, md-tabs")) return;
  // Multi-line content (mirror options) and styled <small> hints keep the
  // launcher's own button so their layout and typography stay intact.
  const children = [...native.children].filter(
    (el) => !el.matches("svg, img"));
  if (children.some((el) => el.tagName !== "SPAN" || el.children.length)
      || children.length > 1) {
    return;
  }
  const tag = m3ButtonTag(native);
  if (!m3Ready(tag)) return;
  const host = m3BuildButton(native);
  native.parentNode.insertBefore(host, native);
  native.style.display = "none";
  native.dataset.m3Upgraded = "button";
  const observer = new MutationObserver(() => m3SyncButton(native));
  observer.observe(native, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["class", "disabled", "hidden", "href", "src", "title",
                      "aria-label"],
  });
  m3ButtonObservers.set(native, observer);
  m3SyncButton(native);
}

function upgradeMaterialButtons() {
  for (const button of document.querySelectorAll("button.btn, button.link")) {
    if (!button.dataset.m3Upgraded) upgradeMaterialButton(button);
  }
}

function downgradeMaterialButtons() {
  for (const host of document.querySelectorAll(".m3-button")) {
    const native = host.__m3Native;
    if (!native) continue;
    m3ButtonObservers.get(native)?.disconnect();
    m3ButtonObservers.delete(native);
    delete native.dataset.m3Upgraded;
    native.style.display = "";
    host.remove();
  }
}

/* ------------------------------------------------- official text fields */

const m3FieldObservers = new WeakMap();
const M3_FIELD_TYPES = new Set([
  "text", "email", "number", "password", "search", "tel", "url", "textarea",
]);

/* True while the user is typing in `input`, whether Classic renders the input
   itself or Material renders the official field in front of it. */
function m3FieldActive(input) {
  if (!input) return false;
  if (document.activeElement === input) return true;
  if (input.dataset && input.dataset.m3Focused === "1") return true;
  return Boolean(document.activeElement
    && document.activeElement.__m3Native === input);
}

function m3SyncField(native, host) {
  const disabled = native.disabled;
  if (host.disabled !== disabled) host.disabled = disabled;
  if (host.readOnly !== native.readOnly) host.readOnly = native.readOnly;
  if (host.required !== native.required) host.required = native.required;
  const groupLabel = host.__m3Group?.querySelector(".field-label");
  const label = (groupLabel ? groupLabel.textContent : native.placeholder) || "";
  if (host.label !== label.trim()) host.label = label.trim();
  const placeholder = native.placeholder || "";
  if (host.placeholder !== placeholder) host.placeholder = placeholder;
  const type = M3_FIELD_TYPES.has(native.type) ? native.type : "text";
  if (host.type !== type) host.type = type;
  if (host.inputMode !== native.inputMode) host.inputMode = native.inputMode;
  if (native.maxLength >= 0 && host.maxLength !== native.maxLength) {
    host.maxLength = native.maxLength;
  }
  const autocomplete = native.getAttribute("autocomplete");
  if (autocomplete && host.autocomplete !== autocomplete) {
    host.autocomplete = autocomplete;
  }
  if (native.value !== host.value) host.value = native.value;
}

/* Keyboard handlers were bound to the launcher's input (Enter = save, etc.).
   The M3 field types on its own internal input, so the event is replayed on
   the native element. It does not bubble, to avoid running document-level
   shortcuts twice. */
function m3ForwardKey(native, event) {
  if (event.isComposing) return;
  const clone = new KeyboardEvent(event.type, {
    key: event.key,
    code: event.code,
    location: event.location,
    repeat: event.repeat,
    ctrlKey: event.ctrlKey,
    shiftKey: event.shiftKey,
    altKey: event.altKey,
    metaKey: event.metaKey,
    bubbles: false,
    cancelable: true,
  });
  for (const legacy of ["keyCode", "which"]) {
    try {
      Object.defineProperty(clone, legacy, { value: event[legacy] });
    } catch {
      /* a read-only legacy field is not worth failing the keystroke over */
    }
  }
  if (!native.dispatchEvent(clone)) event.preventDefault();
}

function upgradeMaterialField(native) {
  if (native.dataset.m3Upgraded) return;
  if (!m3Ready("md-outlined-text-field")) return;
  const host = document.createElement("md-outlined-text-field");
  host.className = "m3-field";
  if (native.classList.contains("grow")) host.classList.add("grow");
  const group = native.closest(".field");
  if (group) {
    group.classList.add("m3-field-group");
    host.__m3Group = group;
  }
  native.parentNode.insertBefore(host, native);
  native.style.display = "none";
  native.dataset.m3Upgraded = "field";
  host.__m3Native = native;

  // Programmatic `input.value = ...` must keep the visible field in sync.
  const descriptor = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype, "value");
  Object.defineProperty(native, "value", {
    configurable: true,
    get() { return descriptor.get.call(native); },
    set(value) {
      descriptor.set.call(native, value);
      host.value = value == null ? "" : String(value);
    },
  });
  // `$("#java-path").focus()` should focus the real M3 field.
  native.focus = (options) => host.focus(options);

  host.addEventListener("input", () => {
    const value = host.value;
    if (descriptor.get.call(native) !== value) {
      descriptor.set.call(native, value);
    }
    native.dispatchEvent(new Event("input", { bubbles: true }));
  });
  host.addEventListener("change", () => {
    native.dispatchEvent(new Event("change", { bubbles: true }));
  });
  host.addEventListener("focusin", () => {
    native.dataset.m3Focused = "1";
  });
  host.addEventListener("focusout", () => {
    delete native.dataset.m3Focused;
  });
  native.addEventListener("input", () => {
    if (host.value !== native.value) host.value = native.value;
  });
  host.addEventListener("keydown", (event) => m3ForwardKey(native, event));
  host.addEventListener("keyup", (event) => m3ForwardKey(native, event));
  const observer = new MutationObserver(() => m3SyncField(native, host));
  observer.observe(native, {
    attributes: true,
    attributeFilter: ["disabled", "placeholder", "readonly", "required",
                      "maxlength", "type", "inputmode", "autocomplete"],
  });
  m3FieldObservers.set(native, observer);
  m3SyncField(native, host);
}

function upgradeMaterialFields() {
  for (const input of document.querySelectorAll("input.input")) {
    if (input.type === "range" || input.type === "checkbox") continue;
    if (!input.dataset.m3Upgraded) upgradeMaterialField(input);
  }
}

function downgradeMaterialFields() {
  for (const host of document.querySelectorAll(".m3-field")) {
    const native = host.__m3Native;
    if (!native) continue;
    m3FieldObservers.get(native)?.disconnect();
    m3FieldObservers.delete(native);
    delete native.dataset.m3Upgraded;
    delete native.dataset.m3Focused;
    delete native.value;
    delete native.focus;
    host.__m3Group?.classList.remove("m3-field-group");
    native.style.display = "";
    host.remove();
  }
}

/* --------------------------------------------------- official sliders */

const m3SliderObservers = new WeakMap();

function m3SyncSlider(native, host) {
  const step = Number(native.step) || 1;
  const min = Number(native.min) || 0;
  const max = native.max === "" ? 100 : Number(native.max);
  if (host.min !== min) host.min = min;
  if (host.max !== max) host.max = max;
  if (host.step !== step) host.step = step;
  if (host.disabled !== native.disabled) host.disabled = native.disabled;
  const value = Number(native.value);
  if (host.value !== value) host.value = value;
}

function upgradeMaterialSlider(native) {
  if (native.dataset.m3Upgraded) return;
  if (!m3Ready("md-slider")) return;
  const host = document.createElement("md-slider");
  host.className = "m3-slider";
  native.parentNode.insertBefore(host, native);
  native.style.display = "none";
  native.dataset.m3Upgraded = "slider";
  host.__m3Native = native;

  const descriptor = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype, "value");
  Object.defineProperty(native, "value", {
    configurable: true,
    get() { return descriptor.get.call(native); },
    set(value) {
      descriptor.set.call(native, value);
      const number = Number(value);
      host.value = Number.isFinite(number) ? number : 0;
    },
  });
  host.addEventListener("input", () => {
    descriptor.set.call(native, String(host.value));
    native.dispatchEvent(new Event("input", { bubbles: true }));
  });
  host.addEventListener("change", () => {
    native.dispatchEvent(new Event("change", { bubbles: true }));
  });
  host.addEventListener("focusin", () => {
    native.dataset.m3Focused = "1";
  });
  host.addEventListener("focusout", () => {
    delete native.dataset.m3Focused;
  });
  const observer = new MutationObserver(() => m3SyncSlider(native, host));
  observer.observe(native, {
    attributes: true,
    attributeFilter: ["min", "max", "step", "disabled"],
  });
  m3SliderObservers.set(native, observer);
  m3SyncSlider(native, host);
}

function upgradeMaterialSliders() {
  for (const input of document.querySelectorAll("input[type=range]")) {
    if (!input.dataset.m3Upgraded) upgradeMaterialSlider(input);
  }
}

function downgradeMaterialSliders() {
  for (const host of document.querySelectorAll(".m3-slider")) {
    const native = host.__m3Native;
    if (!native) continue;
    m3SliderObservers.get(native)?.disconnect();
    m3SliderObservers.delete(native);
    delete native.dataset.m3Upgraded;
    delete native.dataset.m3Focused;
    delete native.value;
    native.style.display = "";
    host.remove();
  }
}

/* -------------------------------------------------- official checkboxes */

const m3CheckObservers = new WeakMap();

function m3CheckboxTag(native) {
  if (native.closest(".zapret-check, .setting-row")) return "md-switch";
  return "md-checkbox";
}

function m3CheckboxValue(host) {
  return host.__m3Tag === "md-switch" ? host.selected : host.checked;
}

function m3SyncCheckbox(native, host) {
  if (host.__m3Tag === "md-switch") {
    if (host.selected !== native.checked) host.selected = native.checked;
  } else {
    if (host.checked !== native.checked) host.checked = native.checked;
    if (host.indeterminate !== native.indeterminate) {
      host.indeterminate = native.indeterminate;
    }
  }
  if (host.disabled !== native.disabled) host.disabled = native.disabled;
}

function upgradeMaterialCheckbox(native) {
  if (native.dataset.m3Upgraded) return;
  const tag = m3CheckboxTag(native);
  if (!m3Ready(tag)) return;
  const host = document.createElement(tag);
  host.__m3Tag = tag;
  host.className = tag === "md-switch" ? "m3-check m3-switch" : "m3-check";
  native.parentNode.insertBefore(host, native);
  native.style.display = "none";
  native.dataset.m3Upgraded = "checkbox";
  host.__m3Native = native;

  const checked = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype, "checked");
  Object.defineProperty(native, "checked", {
    configurable: true,
    get() { return checked.get.call(native); },
    set(value) {
      checked.set.call(native, value);
      if (host.__m3Tag === "md-switch") host.selected = Boolean(value);
      else host.checked = Boolean(value);
    },
  });
  const indeterminate = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype, "indeterminate");
  Object.defineProperty(native, "indeterminate", {
    configurable: true,
    get() { return indeterminate.get.call(native); },
    set(value) {
      indeterminate.set.call(native, value);
      if (host.__m3Tag !== "md-switch") host.indeterminate = Boolean(value);
    },
  });

  host.addEventListener("click", (event) => event.stopPropagation());
  host.addEventListener("dblclick", (event) => event.stopPropagation());
  host.addEventListener("change", () => {
    checked.set.call(native, m3CheckboxValue(host));
    native.dispatchEvent(new Event("change", { bubbles: true }));
  });
  native.addEventListener("change", () => {
    m3SyncCheckbox(native, host);
  });
  const observer = new MutationObserver(() => m3SyncCheckbox(native, host));
  observer.observe(native, {
    attributes: true,
    attributeFilter: ["disabled", "checked"],
  });
  m3CheckObservers.set(native, observer);
  m3SyncCheckbox(native, host);
}

function upgradeMaterialCheckboxes() {
  for (const input of document.querySelectorAll("input[type=checkbox]")) {
    if (!input.dataset.m3Upgraded) upgradeMaterialCheckbox(input);
  }
}

function downgradeMaterialCheckboxes() {
  for (const host of document.querySelectorAll(".m3-check")) {
    const native = host.__m3Native;
    if (!native) continue;
    m3CheckObservers.get(native)?.disconnect();
    m3CheckObservers.delete(native);
    delete native.dataset.m3Upgraded;
    delete native.checked;
    delete native.indeterminate;
    native.style.display = "";
    host.remove();
  }
}

/* ---------------------------------------------------- official radio marks */

const m3RadioObservers = new WeakMap();

function m3SyncOptionRadio(option) {
  const radio = option.querySelector(":scope > md-radio.m3-option-radio");
  if (!radio) return;
  const checked = option.classList.contains("on")
    || option.getAttribute("aria-checked") === "true";
  if (radio.checked !== checked) radio.checked = checked;
  if (radio.disabled !== option.disabled) radio.disabled = option.disabled;
}

function upgradeMaterialRadios() {
  if (!m3Ready("md-radio")) return;
  for (const option of document.querySelectorAll(
    ".theme-option, .design-option")) {
    if (option.querySelector(":scope > md-radio.m3-option-radio")) continue;
    const radio = document.createElement("md-radio");
    radio.className = "m3-option-radio";
    radio.setAttribute("aria-hidden", "true");
    radio.checked = option.classList.contains("on");
    option.appendChild(radio);
    // The mark is decorative: the surrounding card is the real radio target.
    radio.inert = true;
    radio.tabIndex = -1;
    const observer = new MutationObserver(() => m3SyncOptionRadio(option));
    observer.observe(option, {
      attributes: true,
      attributeFilter: ["class", "disabled", "aria-checked"],
    });
    m3RadioObservers.set(option, observer);
    m3SyncOptionRadio(option);
  }
}

function downgradeMaterialRadios() {
  for (const radio of document.querySelectorAll("md-radio.m3-option-radio")) {
    const option = radio.parentElement;
    if (option) m3RadioObservers.get(option)?.disconnect();
    if (option) m3RadioObservers.delete(option);
    radio.remove();
  }
}

/* ------------------------------------------- official circular progress */

const m3SpinnerObservers = new Map();

function m3SyncNetworkSpinner() {
  const sub = document.getElementById("net-sub");
  if (!sub) return;
  const busy = sub.classList.contains("busy");
  let spinner = sub.querySelector(":scope > md-circular-progress.m3-spinner");
  if (busy) {
    if (!m3Ready("md-circular-progress")) return;
    if (!spinner) {
      spinner = document.createElement("md-circular-progress");
      spinner.className = "m3-spinner";
      spinner.indeterminate = true;
      sub.prepend(spinner);
    }
    spinner.indeterminate = true;
  } else if (spinner) {
    spinner.remove();
  }
}

function upgradeMaterialSpinners() {
  const sub = document.getElementById("net-sub");
  if (sub && !m3SpinnerObservers.has(sub)) {
    const observer = new MutationObserver(m3SyncNetworkSpinner);
    observer.observe(sub, { attributes: true, attributeFilter: ["class"] });
    m3SpinnerObservers.set(sub, observer);
  }
  m3SyncNetworkSpinner();
}

function downgradeMaterialSpinners() {
  for (const [node, observer] of m3SpinnerObservers) {
    observer.disconnect();
    node.querySelectorAll(":scope > md-circular-progress.m3-spinner")
      .forEach((spinner) => spinner.remove());
  }
  m3SpinnerObservers.clear();
  document.querySelectorAll("md-circular-progress.m3-spinner")
    .forEach((spinner) => spinner.remove());
}

/* ---------------------------------------------------- official divider */

function upgradeMaterialDividers() {
  if (!m3Ready("md-divider")) return;
  for (const rule of document.querySelectorAll(".rule:not(md-divider)")) {
    const divider = document.createElement("md-divider");
    for (const attr of [...rule.attributes]) {
      divider.setAttribute(attr.name, attr.value);
    }
    rule.replaceWith(divider);
  }
}

function downgradeMaterialDividers() {
  for (const divider of document.querySelectorAll("md-divider.rule")) {
    const rule = document.createElement("div");
    for (const attr of [...divider.attributes]) {
      rule.setAttribute(attr.name, attr.value);
    }
    divider.replaceWith(rule);
  }
}

/* --------------------------------------------- upgrades for dynamic content */

let m3DomObserver = null;
let m3UpgradeScheduled = false;

function upgradeMaterialControls() {
  upgradeMaterialButtons();
  upgradeMaterialFields();
  upgradeMaterialSliders();
  upgradeMaterialCheckboxes();
  upgradeMaterialRadios();
}

function scheduleMaterialUpgrades() {
  if (m3UpgradeScheduled || !m3DesignActive()) return;
  m3UpgradeScheduled = true;
  setTimeout(() => {
    m3UpgradeScheduled = false;
    if (!m3DesignActive()) return;
    upgradeMaterialProgress();
    upgradeMaterialCards();
    upgradeMaterialDividers();
    upgradeMaterialControls();
    upgradeMaterialSpinners();
  }, 0);
}

function startMaterialObserver() {
  if (m3DomObserver || !document.body) return;
  m3DomObserver = new MutationObserver(scheduleMaterialUpgrades);
  m3DomObserver.observe(document.body, { childList: true, subtree: true });
}

function stopMaterialObserver() {
  m3DomObserver?.disconnect();
  m3DomObserver = null;
}

/* ------------------------------------------------------------------ lifecycle */

function refreshMaterialDesign() {
  if (m3DesignActive()) {
    applyMaterialTokens();
    upgradeMaterialSegments();
    upgradeMaterialProgress();
    upgradeMaterialCards();
    upgradeMaterialDividers();
    upgradeMaterialControls();
    upgradeMaterialSpinners();
    upgradeMaterialRipples();
    syncMaterialIcons();
    startMaterialObserver();
  } else {
    stopMaterialObserver();
    clearMaterialTokens();
    downgradeMaterialSegments();
    downgradeMaterialProgress();
    downgradeMaterialCards();
    downgradeMaterialDividers();
    downgradeMaterialButtons();
    downgradeMaterialFields();
    downgradeMaterialSliders();
    downgradeMaterialCheckboxes();
    downgradeMaterialRadios();
    downgradeMaterialSpinners();
    downgradeMaterialRipples();
    syncMaterialIcons();
  }
}
