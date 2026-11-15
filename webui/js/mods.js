"use strict";

/* ------------------------------------------------------------------ mods */

function syncKindUi() {
  const meta = CONTENT_KINDS[mods.kind] || CONTENT_KINDS.mod;
  $("#mods-title").textContent = meta.title;
  $("#mods-query").placeholder = meta.placeholder;
  $("#kind-seg").classList.toggle("hidden", screen === "modpacks");
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
  if (mods.kind === "modpack") mods.checked.clear();
  mods.offset = Number(saved.offset) || 0;
  mods.total = Number(saved.total) || mods.hits.length;
  mods.query = saved.query || "";
  $("#mods-query").value = saved.query || "";
  renderHits();
  showModInfo(mods.hits[mods.selected] || null);
  if (mods.selected >= 0) refreshModStatus();
}

function initMods(forceKind) {
  const detected = S.instance
    && ["fabric", "forge", "neoforge"].includes(S.instance.loader)
    ? S.instance.loader : "any";
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
      if (saved && saved.kind === mods.kind) {
        restoreBrowserState(saved, detected);
      } else {
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
  if (kind === "modpack") {
    setScreen("modpacks");
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
      ? "Searching…" : meta.empty));
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
