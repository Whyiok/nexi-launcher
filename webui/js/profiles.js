"use strict";

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

let menuSlug = "";

/* Switching builds is optimistic: the rail highlights the clicked card right
   away and the backend catches up in the background. Only the newest click
   may apply its state, and the select calls are serialised so the backend
   always ends on the build the user picked last. */
let profileSelectSeq = 0;
let profileSelectChain = Promise.resolve();
/* The build the backend has actually selected. The rail and S.instance move
   ahead optimistically, so Play must compare against this before launching. */
let selectionConfirmed = "";

function queueProfileSelect(slug) {
  const next = profileSelectChain.then(() => call("select", slug));
  profileSelectChain = next.then(() => {}, () => {});
  return next;
}

function paintProfileSelection(slug) {
  $$("#profile-list .profile-card").forEach((card) => {
    card.classList.toggle("selected", card.dataset.slug === slug);
  });
}

function previewProfileSelection(slug) {
  const inst = S.instances.find((item) => item.slug === slug);
  if (!inst || !S.instance) return;
  S.selected = slug;
  S.instance = inst;
  S.ram = Number(inst.ram) || S.ram;
  paintProfileSelection(slug);
  // The profile pane follows at once, but its contents are only requested
  // after the backend has actually switched profiles.
  if (screen === "profiles") {
    fillDetail(inst, { load: false });
    detail.loading = true;
    renderDetailPanes();
  }
}

async function commitProfileSelection(slug) {
  if (!slug) return;
  const seq = ++profileSelectSeq;
  previewProfileSelection(slug);
  const result = await queueProfileSelect(slug);
  if (seq !== profileSelectSeq) return;
  if (result.state) applyState(result.state);
  else await refreshState();
}

function hideProfileMenu() {
  const menu = $("#profile-menu");
  menuSlug = "";
  if (!menu || !menu.classList.contains("open")) return;
  menu.classList.remove("open");
  resetDeleteConfirm();
}

function showProfileMenu(x, y, slug) {
  const menu = $("#profile-menu");
  if (!menu || !S.instance) return;
  hideProfileTip();
  resetDeleteConfirm();
  menuSlug = slug || S.selected;
  menu.classList.add("open");
  const rect = menu.getBoundingClientRect();
  const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
  const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  syncBusy();
}

async function selectProfileSilently(slug) {
  if (!slug || !S.instance) return;
  if (S.instance.slug === slug && selectionConfirmed === slug) return;
  // A select may still be in flight (or the preview may have moved ahead of
  // the backend); wait for the backend before actions such as Play.
  await commitProfileSelection(slug);
}

function runProfileMenuAction(action) {
  switch (action) {
    case "open-folder": call("open", "game"); break;
    case "mods": openBrowser("mod"); break;
    case "logs":
      setScreen("profiles");
      setDetailPane("logs");
      break;
    case "icon": setProfileIcon(); break;
    case "edit": openEditProfile(); break;
    case "duplicate": duplicateProfile(); break;
    case "backup": backupWorlds(); break;
    case "verify": verifyFiles(); break;
    case "settings":
      /* The context menu belongs to the profile card, so its “Settings”
         opens that profile's settings pane — not the launcher settings. */
      setScreen("profiles");
      setDetailPane("settings");
      break;
    default: break;
  }
}

/* The rail is only rebuilt when the builds themselves change. A selection
   change just repaints the cards, so their grow/push animation is never cut
   short by a full re-render. */
let profilesKey = "";

/* Pointer drag reorders the rail. Writes are saved once the card settles, so
   the backend receives a single final order instead of every hover slot. */
const profileDrag = { card: null, startY: 0, grab: 0, shift: 0, active: false,
                      suppressClick: false };

function profileDragStart(event) {
  if (event.button !== 0 || S.busy) return;
  const card = event.target.closest(".profile-card");
  if (!card || !card.dataset.slug) return;
  profileDrag.card = card;
  profileDrag.startY = event.clientY;
  profileDrag.grab = event.clientY - card.getBoundingClientRect().top;
  profileDrag.shift = 0;
  profileDrag.active = false;
  document.addEventListener("pointermove", profileDragMove);
  document.addEventListener("pointerup", profileDragEnd);
  document.addEventListener("pointercancel", profileDragEnd);
}

function reorderProfileCard(list, card, before) {
  const tops = new Map();
  for (const el of list.querySelectorAll(".profile-card")) {
    tops.set(el, el.getBoundingClientRect().top);
  }
  if (before) list.insertBefore(card, before);
  else list.appendChild(card);
  for (const [el, top] of tops) {
    if (el === card) continue;
    const delta = top - el.getBoundingClientRect().top;
    if (Math.abs(delta) < 0.5) continue;
    el.style.transition = "none";
    el.style.transform = `translateY(${delta}px)`;
    requestAnimationFrame(() => {
      el.style.transition = "";
      el.style.transform = "";
    });
  }
}

function profileDragMove(event) {
  const card = profileDrag.card;
  if (!card || !card.isConnected) return;
  if (!profileDrag.active) {
    if (Math.abs(event.clientY - profileDrag.startY) < 5) return;
    profileDrag.active = true;
    hideProfileTip();
    hideProfileMenu();
    card.classList.add("dragging");
    document.body.classList.add("profile-dragging");
  }
  event.preventDefault();
  const list = $("#profile-list");
  if (!list) return;

  // Keep the card's visual top under the pointer.
  const targetTop = event.clientY - profileDrag.grab;
  let rect = card.getBoundingClientRect();
  profileDrag.shift += targetTop - rect.top;
  card.style.transform = `translateY(${profileDrag.shift}px)`;

  const center = targetTop + rect.height / 2;
  const cards = $$(".profile-card", list).filter((item) => item !== card);
  const before = cards.find((item) => {
    const box = item.getBoundingClientRect();
    return center < box.top + box.height / 2;
  }) || null;
  if (before ? card.nextElementSibling !== before : card.nextElementSibling) {
    reorderProfileCard(list, card, before);
    // The slot changed — offset the shift so the card does not jump.
    rect = card.getBoundingClientRect();
    profileDrag.shift += targetTop - rect.top;
    card.style.transform = `translateY(${profileDrag.shift}px)`;
  }

  const box = list.getBoundingClientRect();
  if (event.clientY < box.top + 28) list.scrollTop -= 12;
  else if (event.clientY > box.bottom - 28) list.scrollTop += 12;
}

function profileDragEnd() {
  document.removeEventListener("pointermove", profileDragMove);
  document.removeEventListener("pointerup", profileDragEnd);
  document.removeEventListener("pointercancel", profileDragEnd);
  const card = profileDrag.card;
  const active = profileDrag.active;
  profileDrag.card = null;
  profileDrag.active = false;
  profileDrag.shift = 0;
  document.body.classList.remove("profile-dragging");
  if (!card) return;
  card.classList.remove("dragging");
  if (!active) return;
  // The pointerup that ends a drag is followed by a click on the card; it must
  // not also switch the selected build.
  profileDrag.suppressClick = true;
  setTimeout(() => { profileDrag.suppressClick = false; }, 0);
  const order = $$("#profile-list .profile-card")
    .map((item) => item.dataset.slug).filter(Boolean);
  card.style.transition = "transform .18s var(--ease)";
  card.style.transform = "translateY(0)";
  setTimeout(() => {
    if (card.isConnected) {
      card.style.transition = "";
      card.style.transform = "";
    }
    const current = (S.instances || []).map((inst) => inst.slug);
    if (order.join("|") !== current.join("|")) reorderProfiles(order);
  }, 180);
}

async function reorderProfiles(order) {
  const result = await call("reorder_instances", order);
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not reorder builds.", true);
    if (result && result.state) applyState(result.state);
    else await refreshState();
    return;
  }
  if (result.state) applyState(result.state);
}

function profilesSignature() {
  return S.instances.map((inst) => {
    const icon = inst.icon || "";
    return [inst.slug, inst.name, inst.base, inst.loader,
            inst.loader_version || "", inst.account || "",
            icon.length, icon.slice(-24)].join("\u0000");
  }).join("\u0001");
}

function renderProfiles() {
  hideProfileTip();
  hideProfileMenu();
  const key = profilesSignature();
  if (key !== profilesKey) {
    profilesKey = key;
    const list = $("#profile-list");
    list.replaceChildren();

    for (const inst of S.instances) {
      const card = elem("button", "profile-card");
      card.type = "button";
      card.dataset.slug = inst.slug;
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
        showProfileMenu(event.clientX, event.clientY, inst.slug);
      });
      card.addEventListener("mouseenter", () => showProfileTip(card, inst.name));
      card.addEventListener("mouseleave", hideProfileTip);
      card.addEventListener("focus", () => showProfileTip(card, inst.name));
      card.addEventListener("blur", hideProfileTip);
      list.appendChild(card);
    }
  }
  paintProfileSelection(S.selected);
  $("#profiles-count").textContent = S.instances.length
    ? `${S.instances.length} total` : "empty";

  const has = !!S.instance;
  $("#profile-empty").classList.toggle("hidden", has);
  $("#profile-detail").classList.toggle("hidden", !has);
  if (has) fillDetail(S.instance);
}

function fillDetailBanner(inst) {
  const banner = $("#detail-banner");
  const video = $("#detail-banner-video");
  const head = $("#detail-head");
  const showVideo = !!inst.banner && inst.banner_kind === "video";
  const showImage = !!inst.banner && !showVideo;
  if (banner) {
    if (showImage) {
      if (banner.getAttribute("src") !== inst.banner) banner.src = inst.banner;
      banner.classList.remove("hidden");
    } else {
      banner.classList.add("hidden");
      banner.removeAttribute("src");
    }
  }
  if (video) {
    if (showVideo) {
      if (video.getAttribute("src") !== inst.banner) video.src = inst.banner;
      video.classList.remove("hidden");
      if (video.paused) video.play().catch(() => {});
    } else {
      video.classList.add("hidden");
      video.pause();
      video.removeAttribute("src");
    }
  }
  if (head) head.classList.toggle("has-banner", !!inst.banner);
  const clear = $("#btn-pane-clear-banner");
  if (clear) clear.disabled = !!S.busy || !inst.banner;
}

function fillDetail(inst, options = {}) {
  $("#detail-name").textContent = inst.name;
  const loader = inst.loader === "any"
    ? "vanilla" : (LOADER_LABELS[inst.loader] || inst.loader);
  const loaderText = inst.loader_version
    ? `${loader} ${inst.loader_version}` : loader;
  $("#detail-meta").textContent = `Minecraft ${inst.base} · ${loaderText}`;
  $("#detail-path").textContent = inst.path;
  $("#detail-path").title = inst.path;
  $("#detail-badge").textContent = loader;
  fillDetailBanner(inst);
  $("#detail-playtime-text").textContent = formatPlaytime(inst.playtime);

  renderPaneAccount(inst);
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
    shots.key = "";
  }
  syncDetailTabs();
  fillVersionEditor();
  if (options.load !== false) {
    loadProfileContents();
    if (detail.pane === "screenshots") pollShots();
  }
  syncPlay();
}

const ACCOUNT_KINDS = {
  microsoft: "Microsoft", ely: "Ely.by", offline: "Offline", nexi: "Nexi",
};

/* The account select in Profile settings: one entry per account plus the
   launcher-wide active account as the default. */
function renderPaneAccount(inst) {
  const select = $("#pane-account");
  if (!select) return;
  const accounts = S.accounts || [];
  const active = accounts.find((account) => account.active)
    || accounts.find((account) => account.id === S.active_account) || null;
  select.replaceChildren();
  const fallback = document.createElement("option");
  fallback.value = "";
  fallback.textContent = active
    ? `Launcher default · ${active.name}` : "Launcher default";
  select.appendChild(fallback);
  for (const account of accounts) {
    const option = document.createElement("option");
    option.value = account.id;
    option.textContent =
      `${account.name} · ${ACCOUNT_KINDS[account.type] || account.type}`;
    select.appendChild(option);
  }
  const chosen = accounts.find((account) => account.id === inst.account);
  select.value = chosen ? chosen.id : "";
  select.disabled = !accounts.length;
  select.title = chosen
    ? `${chosen.name} · ${ACCOUNT_KINDS[chosen.type] || chosen.type}`
    : (active ? `Uses the active account: ${active.name}` : "");
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
  if (name === "logs") openGameLogs();
  else stopGameLogsTimer();
  if (name === "screenshots") {
    startShotsTimer();
    pollShots();
  } else {
    stopShotsTimer();
  }
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

/* --------------------------------------------------------- screenshots */

function shotsSignature(items) {
  return (items || []).map((shot) =>
    `${shot.name}|${shot.size}|${shot.modified}|${shot.url}`).join("\n");
}

function renderShots() {
  const data = detail.contents;
  const loading = detail.loading && !data;
  const items = (data && data.screenshots) || [];
  const key = `${detail.slug}|${loading}|${shotsSignature(items)}`;
  if (key === shots.key) return;
  shots.key = key;
  const list = $("#pane-shots-list");
  $("#pane-shots-sub").textContent = data
    ? paneSub(items.length, "screenshot") : (loading ? "Loading…" : "—");
  list.replaceChildren();
  if (loading) {
    list.appendChild(paneEmpty("Reading the profile folder…"));
    return;
  }
  if (!items.length) {
    list.appendChild(paneEmpty(
      "No screenshots yet. Press F2 in game to take one."));
    return;
  }
  for (const shot of items) list.appendChild(shotCard(shot));
}

function shotCard(shot) {
  const card = elem("div", "shot");
  const open = elem("button", "shot-open");
  open.type = "button";
  open.title = `${shot.name}\n${fmtSize(shot.size)} · ${shot.modified}`;
  if (shot.url) {
    const img = new Image();
    img.className = "shot-thumb";
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    img.src = shot.url;
    img.addEventListener("error", () => {
      const placeholder = elem("div", "shot-thumb");
      img.replaceWith(placeholder);
    });
    open.appendChild(img);
  } else {
    open.appendChild(elem("div", "shot-thumb"));
  }
  open.appendChild(elem("span", "shot-name", shot.name));
  open.addEventListener("click", () => showShotViewer(shot));
  card.appendChild(open);
  const copy = elem("button", "shot-copy");
  copy.type = "button";
  copy.title = "Copy screenshot";
  copy.setAttribute("aria-label", "Copy screenshot");
  copy.appendChild(iconNode("i-copy"));
  copy.addEventListener("click", (event) => {
    event.stopPropagation();
    copyShot(shot);
  });
  card.appendChild(copy);
  return card;
}

function showShotViewer(shot) {
  shots.open = shot;
  const img = $("#shot-viewer-img");
  img.src = shot.url || "";
  img.alt = shot.name;
  $("#shot-viewer-name").textContent =
    `${shot.name} · ${fmtSize(shot.size)} · ${shot.modified}`;
  $("#btn-shot-open").disabled = !shot.url;
  $("#shot-viewer").classList.remove("hidden");
}

function hideShotViewer() {
  shots.open = null;
  $("#shot-viewer").classList.add("hidden");
  $("#shot-viewer-img").removeAttribute("src");
}

async function copyShot(shot) {
  if (!shot) return;
  const result = await call("screenshot_copy", shot.name);
  setStatus(result && result.ok
    ? (result.message || "Screenshot copied to the clipboard.")
    : ((result && result.error) || "Could not copy the screenshot."),
  !(result && result.ok));
}

/* New screenshots must appear right away, so the pane rechecks the folder
   while it is open. Only a changed list re-renders the grid, which keeps
   hovering, copying and scrolling untouched. */
function startShotsTimer() {
  stopShotsTimer();
  shots.timer = setInterval(pollShots, 1500);
}

function stopShotsTimer() {
  if (shots.timer) {
    clearInterval(shots.timer);
    shots.timer = null;
  }
}

async function pollShots() {
  if (screen !== "profiles" || detail.pane !== "screenshots" || !S.instance) {
    stopShotsTimer();
    return;
  }
  const slug = S.instance.slug;
  const result = await call("screenshot_list");
  if (!result || !result.ok) return;
  if (slug !== detail.slug || !detail.contents) return;
  const items = result.screenshots || [];
  const key = `${detail.slug}|false|${shotsSignature(items)}`;
  if (key === shots.key) return;
  detail.contents.screenshots = items;
  detail.contents.counts = Object.assign({}, detail.contents.counts, {
    screenshots: items.length,
  });
  renderShots();
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
      const button = elem("button", "btn danger sm", "Uninstall");
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

  renderShots();

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

async function changePaneAccount(accountId) {
  if (!S.instance) return;
  const result = await call("instance_set_account", accountId || "");
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not change the account.",
              true);
    if (S.instance) renderPaneAccount(S.instance);
    return;
  }
  setStatus(result.message || "Account changed.");
  if (result.state) applyState(result.state);
  else await refreshState();
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

async function setProfileBanner() {
  if (!S.instance || S.busy) return;
  const result = await call("set_profile_banner");
  if (result.cancelled) return;
  if (result.error) {
    setStatus(result.error, true);
    return;
  }
  setStatus("Build banner updated.");
  if (result.state) applyState(result.state);
  else await refreshState();
}

async function clearProfileBanner() {
  if (!S.instance || !S.instance.banner) return;
  const result = await call("clear_profile_banner");
  if (result.error) {
    setStatus(result.error, true);
    return;
  }
  setStatus("Build banner removed.");
  if (result.state) applyState(result.state);
  else await refreshState();
}

async function selectInstance(slug) {
  if (!slug || profileDrag.suppressClick) return;
  // On Home a rail click chooses the build the Play button starts, exactly
  // like clicking one of the build rows there; it must not leave Home.
  if (screen === "home") {
    await selectHomeBuild(slug);
    return;
  }
  // The rail is global: a click on a build always opens its details, even
  // when another tab (Settings, Modpacks, New…) is in front.
  if (screen !== "profiles") setScreen("profiles");
  if (slug === S.selected) return;
  resetDeleteConfirm();
  await commitProfileSelection(slug);
}
