"use strict";

/* ---------------------------------------------------------------- create */

/* The Mojang manifest lists versions newest first, so the first release in
   the list is the latest released version. */
function latestReleaseId() {
  const entry = (versions.all || []).find((item) => item.type === "release");
  return entry ? entry.id : "";
}

/* A new profile starts on the latest release. The version list can arrive
   after the create screen is already open, so every load path calls this. */
function applyDefaultVersion() {
  if (editSlug || versions.selected) return;
  versions.selected = latestReleaseId();
}

function resetCreateMode() {
  editSlug = "";
  // A new profile starts on the latest released version, so pressing Create
  // right away gives a current, stable game.
  versions.selected = latestReleaseId();
  $("#new-name").value = "";
  $("#create-title").textContent = "New profile";
  $("#create-sub").textContent = "Pick any Minecraft version — missing files are downloaded from Mojang.";
  $("#btn-create").textContent = "Create profile";
  if (createModalOpen()) renderVersions();
}

/* The create form is a modal over whichever screen is open, so the header no
   longer carries a "New" tab and closing it leaves the user where they were. */
function createModalOpen() {
  const modal = $("#screen-create");
  return !!modal && !modal.hidden;
}

let createReturnFocus = null;

function openCreateModal() {
  const modal = $("#screen-create");
  if (!modal) return;
  const wasOpen = !modal.hidden;
  if (!wasOpen) createReturnFocus = document.activeElement;
  modal.hidden = false;
  // A new profile starts on the latest release, whether it was opened from
  // the New button, the empty state or the profile editor.
  if (!editSlug && !versions.selected) versions.selected = latestReleaseId();
  if (!versions.loaded && !versions.loading) loadVersions(false);
  // The version list can already be loaded by the profile settings pane,
  // which never renders the create list itself.
  else if (versions.loaded) renderVersions();
  if (!wasOpen) {
    requestAnimationFrame(() => {
      const name = $("#new-name");
      if (name) name.focus();
    });
  }
}

function closeCreateModal(restoreFocus = true) {
  const modal = $("#screen-create");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  if (typeof closeVsel === "function") {
    $$("#screen-create .vsel.open").forEach(closeVsel);
  }
  if (editSlug) resetCreateMode();
  if (!restoreFocus) {
    createReturnFocus = null;
    return;
  }
  const back = createReturnFocus;
  createReturnFocus = null;
  if (back && back.isConnected && typeof back.focus === "function") {
    back.focus({ preventScroll: true });
  }
}

function initCreateModal() {
  const modal = $("#screen-create");
  if (!modal || modal.dataset.wired) return;
  modal.dataset.wired = "1";

  const close = $("#btn-close-create");
  if (close) close.addEventListener("click", () => closeCreateModal());
  const backdrop = modal.querySelector(".create-backdrop");
  if (backdrop) backdrop.addEventListener("click", () => closeCreateModal());

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || modal.hidden || event.defaultPrevented) return;
    event.preventDefault();
    closeCreateModal();
  });

  /* Keep Tab inside the dialog; it floats over the whole application. */
  modal.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const nodes = [...modal.querySelectorAll(
      "button, input, select, textarea, [href], [tabindex]:not([tabindex='-1'])")]
      .filter((node) => !node.disabled && !node.hidden
        && node.offsetParent !== null);
    if (!nodes.length) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
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

function fillVersionSelect(preferred) {
  const select = $("#edit-version");
  if (!select) return;
  // `preferred` wins when the profile just changed: the <select> still holds
  // the previous profile's version at that moment, so trusting select.value
  // would show another build's version.
  const current = preferred || select.value || vedit.mc
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
    fillModsVersionFilter();
    applyDefaultVersion();
    renderVersions();
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
    if (result.note) appendCreateLog(result.note);
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
  // Only this editor's own save locks it; background downloads elsewhere
  // must not freeze the profile settings.
  const busy = vedit.busy;
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
    fillVersionSelect(inst.base || "");
    loadEditBuilds();
  } else {
    fillVersionSelect();
  }
  ensureVersionOptions();
  syncVersionEditor();
}

async function applyVersionChange() {
  if (!S.instance || vedit.busy) return;
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
    // First load of a new-profile screen: preselect the latest release.
    if (!editSlug && !versions.selected) {
      versions.selected = latestReleaseId();
    }
    fillModsVersionFilter();
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

function syncVersionFilterButton() {
  const button = $("#btn-show-all-versions");
  if (!button) return;
  const mode = versions.showAll ? "all" : "release";
  if (button.dataset.mode === mode) return;
  button.dataset.mode = mode;
  button.textContent = versions.showAll ? "Releases only" : "Show all versions";
  button.classList.toggle("primary", versions.showAll);
  button.classList.toggle("ghost", !versions.showAll);
}

function renderVersions() {
  const list = $("#version-list");
  list.replaceChildren();
  syncVersionFilterButton();
  versions.query = $("#version-search").value.trim().toLowerCase();

  const rows = versions.all.filter((entry) => {
    if (versions.query) return entry.id.toLowerCase().includes(versions.query);
    if (versions.showAll) return true;
    // Keep an edited profile's base visible even when it is a snapshot, so
    // Edit never silently changes that version.
    if (editSlug && entry.id === versions.selected) return true;
    return entry.type === "release";
  }).slice(0, 600);

  versions.rows = rows;
  // A new profile starts on the latest release; if a search or the filter
  // hides it, the selection is dropped like any other hidden row.
  if (versions.selected && !rows.some((row) => row.id === versions.selected)) {
    versions.selected = "";
  }

  if (!rows.length) {
    list.appendChild(elem("div", "empty-row",
      versions.loading ? "Loading…"
        : "Nothing matches — clear the search or show all versions."));
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
    if (result.note) appendCreateLog(result.note);
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
  if (!S.instance || S.busy === "duplicate") return;
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
  if (!S.instance || S.busy === "backup") return;
  S.busy = "backup";
  syncBusy();
  setStatus("Packing the worlds…");
  const result = await call("backup_worlds");
  S.busy = "";
  syncBusy();
  setStatus(result.message || result.error || "Done.", !result.ok);
}

async function verifyFiles() {
  if (!S.instance || S.busy === "verify") return;
  S.busy = "verify";
  syncBusy();
  setStatus("Checking game files — this can take a minute…");
  const result = await call("verify_files");
  S.busy = "";
  syncBusy();
  setStatus(result.message || result.error || "Done.", !result.ok);
}

async function importModpack() {
  if (S.busy === "import") return;
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
