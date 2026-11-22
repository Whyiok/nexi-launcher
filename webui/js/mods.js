"use strict";

/* ------------------------------------------------------------------ mods */

function browserSourceLabel() {
  return SOURCE_LABELS[mods.source] || "Modrinth";
}

function browserEmptyText() {
  const meta = CONTENT_KINDS[mods.kind] || CONTENT_KINDS.mod;
  if (mods.source === "curseforge" && !S.curseforge_key_set) {
    return "Paste a CurseForge project link or exact slug, or add an API "
      + "key in Settings → Network.";
  }
  const where = mods.kind === "modpack"
    ? " — it installs as a new profile" : " for this profile";
  return `Search ${browserSourceLabel()} to find ${meta.plural}${where}.`;
}

function syncKindUi() {
  const meta = CONTENT_KINDS[mods.kind] || CONTENT_KINDS.mod;
  $("#mods-title").textContent = meta.title;
  if (mods.source === "curseforge" && !S.curseforge_key_set) {
    $("#mods-query").placeholder =
      "Paste a CurseForge link, ID or exact slug";
  } else if (mods.source === "curseforge") {
    $("#mods-query").placeholder = `Search CurseForge ${meta.plural} by name`;
  } else {
    $("#mods-query").placeholder = meta.placeholder;
  }
  $("#kind-seg").classList.toggle("hidden", screen === "modpacks");
  const modButton = $('#kind-seg button[data-kind="mod"]');
  if (modButton) {
    modButton.disabled = !modsAllowed();
    modButton.title = modsAllowed() ? ""
      : "This profile is vanilla — install a mod loader first";
  }
  $("#mods-seg").classList.toggle("hidden",
    !["mod", "modpack"].includes(mods.kind));
  $("#btn-open-mods-folder").classList.toggle("hidden",
    mods.kind === "modpack");
  $("#btn-open-folder-label").textContent = mods.kind === "resourcepack"
    ? "Open resource packs"
    : mods.kind === "shader" ? "Open shaders" : "Open mods folder";
  $("#btn-mod-install").textContent = meta.install;
  syncBatch();
}

function resetBrowser() {
  // The browser state is being replaced, so any search still in flight no
  // longer owns the busy flag — otherwise its stale response would leave
  // Search and Install disabled forever after a profile/tab switch.
  mods.busy = false;
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
  syncMods();
}

function saveBrowserState() {
  if (!mods.profile) return;
  browserStates.delete(mods.profile);
  browserStates.set(mods.profile, {
    kind: mods.kind,
    source: mods.source,
    loader: mods.loader,
    game: mods.game,
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

function restoreBrowserState(saved) {
  mods.kind = CONTENT_KINDS[saved.kind] ? saved.kind : "mod";
  mods.source = SOURCE_LABELS[saved.source] ? saved.source : mods.source;
  mods.loader = MOD_LOADERS.includes(saved.loader) ? saved.loader : "any";
  mods.game = saved.game || "";
  mods.hits = saved.hits || [];
  mods.selected = Number.isInteger(saved.selected) ? saved.selected : -1;
  mods.installed = saved.installed || null;
  mods.searchedKey = saved.searchedKey || "";
  mods.checked = saved.checked instanceof Set ? saved.checked : new Set();
  if (mods.kind === "modpack") mods.checked.clear();
  mods.offset = Number(saved.offset) || 0;
  mods.total = Number(saved.total) || mods.hits.length;
  mods.query = saved.query || "";
  $("#mods-query").value = saved.query || "";
  renderHits();
  showModInfo(mods.hits[mods.selected] || null);
  if (mods.selected >= 0) refreshModStatus();
  else syncMods();
}

function initMods(forceKind) {
  if (forceKind && CONTENT_KINDS[forceKind] && mods.kind !== forceKind) {
    mods.kind = forceKind;
    mods.key = "";
  }
  const profile = instanceKey();
  if (mods.profile !== profile) {
    saveBrowserState();
    mods.profile = profile;
    if (profile) {
      const saved = browserStates.get(profile);
      if (saved && saved.kind === mods.kind && mods.kind !== "modpack") {
        restoreBrowserState(saved);
      } else if (mods.kind === "modpack") {
        // The Modpacks page is global, not tied to a profile, so it never
        // inherits a profile's version or loader.
        mods.loader = "any";
        mods.game = "";
        resetBrowser();
      } else {
        // A browser opened for a profile starts on that profile's version and
        // loader so the results are compatible; both stay user-editable.
        mods.loader = defaultModsLoader();
        mods.game = defaultModsGame();
        resetBrowser();
      }
    } else {
      // The Modpacks tab has no profile of its own, so it never keeps the
      // filters of the profile the user visited before it.
      mods.loader = "any";
      mods.game = "";
      resetBrowser();
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
  ensureVersionOptions();
  fillModsVersionFilter();
  setSeg("#kind-seg", mods.kind);
  setSeg("#source-seg", mods.source);
  setSeg("#mods-seg", mods.loader);
  syncKindUi();
  updateScreenHeads();
  syncMods();
}

function setBrowserSource(source) {
  if (!SOURCE_LABELS[source] || mods.source === source || mods.busy) return;
  mods.source = source;
  mods.key = browserKey();
  mods.searchedKey = "";
  mods.hits = [];
  mods.selected = -1;
  mods.installed = null;
  mods.checked.clear();
  mods.offset = 0;
  mods.total = 0;
  mods.loadingMore = false;
  mods.statusLoading = false;
  mods.statusSeq += 1;
  mods.searchSeq += 1;
  setSeg("#source-seg", source);
  syncKindUi();
  updateScreenHeads();
  renderHits();
  showModInfo(null);
  syncMods();
  if (S.instance || mods.kind === "modpack") searchMods();
}

function defaultModsLoader() {
  return S.instance
    && ["fabric", "forge", "neoforge"].includes(S.instance.loader)
    ? S.instance.loader : "any";
}

function defaultModsGame() {
  return S.instance ? String(S.instance.base || "") : "";
}

function fillModsVersionFilter() {
  const select = $("#mods-version");
  if (!select) return;
  const installed = versions.installed || new Set();
  // Modpacks search globally, so their picker lists releases only; the
  // profile mods browser also keeps installed non-releases selectable.
  const rows = (versions.all || []).filter(
    (entry) => mods.kind === "modpack"
      ? entry.type === "release"
      : entry.type === "release" || installed.has(entry.id));
  // Keep the current pick (for example a snapshot profile) selectable even if
  // the Mojang list has not loaded yet or does not list it as a release.
  if (mods.game && !rows.some((entry) => entry.id === mods.game)) {
    rows.unshift({ id: mods.game, type: "installed" });
  }
  const signature = `${rows.length}|${rows[0] ? rows[0].id : ""}`;
  if (select.dataset.signature !== signature) {
    select.dataset.signature = signature;
    select.replaceChildren();
    const any = elem("option", "", "Any version");
    any.value = "";
    select.appendChild(any);
    for (const entry of rows) {
      const option = elem("option", "", entry.id);
      option.value = entry.id;
      select.appendChild(option);
    }
  }
  select.value = mods.game;
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
  if (kind === "modpack") {
    setScreen("modpacks");
    return;
  }
  if (CONTENT_KINDS[kind]) {
    // Browse mods / resource packs / shaders in the profile pane always opens
    // on that profile's version and loader so the results are compatible with
    // it. A remembered browser state must not override that choice.
    if (mods.profile !== instanceKey()) {
      saveBrowserState();
      mods.profile = instanceKey();
    }
    browserStates.delete(instanceKey());
    mods.kind = kind;
    mods.key = "";
    mods.loader = defaultModsLoader();
    mods.game = defaultModsGame();
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
  screenStatus("mods", more
    ? "Loading more…" : `Searching ${browserSourceLabel()}…`);
  renderHits();
  syncMods();
  const result = await call("content_search", mods.kind, mods.query || "",
                            mods.loader, mods.offset, mods.game,
                            mods.source);
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
  applyHitSelection();
  const meta = CONTENT_KINDS[mods.kind] || CONTENT_KINDS.mod;
  if (!mods.hits.length) {
    screenStatus("mods", "Nothing found — try another name"
      + (mods.kind === "mod" ? " or loader" : ""));
  } else {
    screenStatus("mods",
      `${mods.hits.length} of ${mods.total} ${meta.plural}`
      + (mods.hits.length < mods.total ? " — scroll for more" : "")
      + (mods.kind === "modpack" ? "" : " · double-click to pick several"));
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
  // Modpacks install as separate profiles, so they are never batched.
  const count = mods.kind === "modpack" ? 0 : mods.checked.size;
  button.classList.toggle("hidden", count === 0);
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
      ? "Searching…" : browserEmptyText()));
    syncBatch();
    return;
  }
  mods.hits.forEach((hit, index) => {
    const row = elem("div", "row mod-row has-icon");
    row.tabIndex = 0;
    const batchable = mods.kind !== "modpack";
    if (index === mods.selected) row.classList.add("selected");
    if (batchable) {
      const box = elem("input", "mod-check");
      box.type = "checkbox";
      box.checked = mods.checked.has(hit.project_id);
      box.title = "Add to the batch (or double-click the row)";
      box.addEventListener("click", (event) => event.stopPropagation());
      box.addEventListener("dblclick", (event) => event.stopPropagation());
      box.addEventListener("change", () => {
        if (box.checked) mods.checked.add(hit.project_id);
        else mods.checked.delete(hit.project_id);
        syncBatch();
      });
      row.appendChild(box);
    }
    row.appendChild(avatarNode(hit.icon_url || "", hit.title));
    row.appendChild(elem("span", "row-title", hit.title));
    row.appendChild(elem("span", "row-side",
      `${fmtCount(hit.downloads)} downloads`));
    // One click only picks the item for the details pane; batching several
    // items is deliberate, so it takes a double click (modpacks never batch).
    row.addEventListener("click", () => {
      mods.selected = index;
      applyHitSelection();
    });
    if (batchable) {
      row.addEventListener("dblclick", () => {
        mods.selected = index;
        if (mods.checked.has(hit.project_id)) mods.checked.delete(hit.project_id);
        else mods.checked.add(hit.project_id);
        applyHitSelection();
      });
    }
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
    // Drop the previous item's installed state and ignore any status call
    // that is still in flight, so Uninstall/Update cannot reappear while
    // nothing is selected.
    mods.installed = null;
    mods.statusSeq += 1;
    mods.statusLoading = false;
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
  const installed = hasHit && !!mods.installed && mods.kind !== "modpack";
  const needsProfile = mods.kind !== "modpack";
  $("#btn-mod-search").disabled = busy || (needsProfile && !S.instance);
  $("#btn-mod-install").classList.toggle("hidden", installed);
  // Nothing selected means nothing to manage: no Uninstall row.
  $("#mod-manage").classList.toggle("hidden",
    mods.kind === "modpack" || !installed);
  $("#btn-mod-install").disabled = busy || !hasHit;
  $("#btn-mod-uninstall").disabled = busy || !installed;
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
                            mods.loader, hit.slug || "", mods.game,
                            hit.source || mods.source);
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
                              mods.loader, hit.slug || "", mods.game,
                              hit.source || mods.source);
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
