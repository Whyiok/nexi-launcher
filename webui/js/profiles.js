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
  if (!slug || !S.instance || S.instance.slug === slug) return;
  const result = await call("select", slug);
  if (result.state) applyState(result.state);
  else await refreshState();
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
      showProfileMenu(event.clientX, event.clientY, inst.slug);
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
  if (name === "logs") openGameLogs();
  else stopGameLogsTimer();
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
  if (!slug) return;
  // The rail is global: a click on a build always opens its details, even
  // when another tab (Settings, Modpacks, New…) is in front.
  if (screen !== "profiles") setScreen("profiles");
  if (slug === S.selected) return;
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
