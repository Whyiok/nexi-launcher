"use strict";

/* ---------------------------------------------------------------- wiring */

const RIPPLE_TARGETS = "button, .profile-card, .account-item, "
  + ".theme-option, .pane-row, .tab, .detail-tab, .ctx-item";

function spawnRipple(event) {
  if (event.button !== 0) return;
  if (event.target.closest("input, textarea, select")) return;
  const target = event.target.closest(RIPPLE_TARGETS);
  if (!target || target.disabled) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const rect = target.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  if (getComputedStyle(target).position === "static") {
    target.style.position = "relative";
  }
  const layer = document.createElement("span");
  layer.className = "ripple-layer";
  const node = document.createElement("span");
  node.className = "click-ripple";
  node.style.left = `${event.clientX - rect.left}px`;
  node.style.top = `${event.clientY - rect.top}px`;
  layer.appendChild(node);
  target.appendChild(layer);
  node.addEventListener("animationend", () => layer.remove());
}

let bound = false;

function bind() {
  if (bound) return;
  bound = true;
  document.addEventListener("pointerdown", spawnRipple);
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
  $("#account-list").addEventListener("pointerdown", accountDragStart);

  $("#ram-down").addEventListener("click", () => changeRam(-1));
  $("#ram-up").addEventListener("click", () => changeRam(1));
  $("#theme-grid").addEventListener("click", (event) => {
    const option = event.target.closest("[data-theme-option]");
    if (option) changeTheme(option.dataset.themeOption);
  });
  $("#mode-seg").addEventListener("click", (event) => {
    const option = event.target.closest("[data-mode-option]");
    if (option) changeMode(option.dataset.modeOption);
  });
  $("#lang-seg").addEventListener("click", (event) => {
    const option = event.target.closest("[data-lang-option]");
    if (option) changeLanguage(option.dataset.langOption);
  });
  $("#btn-play").addEventListener("click", play);
  $("#btn-stop").addEventListener("click", stopGame);
  $("#btn-restart").addEventListener("click", restartGame);
  $("#profile-menu").addEventListener("click", async (event) => {
    const item = event.target.closest("[data-profile-action]");
    if (!item || item.disabled) return;
    const action = item.dataset.profileAction;
    const slug = menuSlug;
    if (action === "delete") {
      /* Kept open: the first click arms the confirmation, the second one
         deletes. Selecting the profile here would re-render the list and close
         the menu, so deletion addresses the slug directly. */
      onDelete(slug);
      return;
    }
    hideProfileMenu();
    await selectProfileSilently(slug);
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
  $("#btn-show-all-versions").addEventListener("click", () => {
    versions.showAll = !versions.showAll;
    renderVersions();
    const count = versions.rows.length;
    screenStatus("create", count
      ? `${count} versions — pick one`
      : "No versions match the search.", !count);
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

  $("#btn-open-logs-folder").addEventListener("click", () =>
    call("open", "launcher_logs"));
  $("#btn-open-log-file").addEventListener("click", () =>
    call("open", "launcher_log"));
  $("#btn-clear-logs").addEventListener("click", () => clearLogsView(logs));
  $("#log-console").addEventListener("scroll", () => {
    const el = $("#log-console");
    logs.stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
  });

  $("#btn-net-check").addEventListener("click", runNetworkCheck);
  $("#btn-net-copy").addEventListener("click", copyNetReport);
  $("#btn-net-clear").addEventListener("click", async () => {
    await call("network_clear");
    renderNetConsole([]);
    setStatus("Network log cleared.");
  });

  $("#btn-open-game-log-folder").addEventListener("click", () =>
    call("open_instance", "logs"));
  $("#btn-clear-game-logs").addEventListener("click", () =>
    clearLogsView(gameLogs));
  $("#game-log-console").addEventListener("scroll", () => {
    const el = $("#game-log-console");
    gameLogs.stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
  });

  $("#btn-skin-choose").addEventListener("click", chooseSkin);
  $("#btn-skin-apply").addEventListener("click", applySkin);
  $("#skin-account-select").addEventListener("change", (event) => {
    skin.account = event.target.value || "";
    loadSkin();
  });
  $("#skin-ely-link").addEventListener("click", (event) => {
    event.preventDefault();
    call("open", "ely_skins");
  });
  document.addEventListener("pointermove", trackSkinPointer);
  const resetSkinAim = () => {
    skinView.targetYaw = 0;
    skinView.targetPitch = 0;
    kickSkinView();
  };
  document.addEventListener("mouseleave", resetSkinAim);
  document.addEventListener("pointerleave", resetSkinAim);
  const skinCanvas = $("#skin-canvas");
  skinCanvas.addEventListener("pointerdown", skinDragStart);
  skinCanvas.addEventListener("pointermove", skinDragMove);
  skinCanvas.addEventListener("pointerup", skinDragEnd);
  skinCanvas.addEventListener("pointercancel", skinDragEnd);
  $("#skin-seg").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-skin-variant]");
    if (button) changeSkinVariant(button.dataset.skinVariant);
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

let orbRaf = 0;

function startOrb() {
  const canvas = document.querySelector(".orb");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  if (orbRaf) {
    cancelAnimationFrame(orbRaf);
    orbRaf = 0;
  }
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

    if (!reduce) orbRaf = requestAnimationFrame(frame);
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
