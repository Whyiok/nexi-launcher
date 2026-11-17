"use strict";

/* --------------------------------------------------------------- events */

function handleEvent(ev) {
  switch (ev.t) {
    case "status":
      if (ev.screen === "create") screenStatus("create", ev.text, ev.error);
      else if (ev.screen === "loaders") setLoaderStatus(ev.text, ev.error);
      else if (ev.screen === "mods") screenStatus("mods", ev.text, ev.error);
      else if (ev.screen === "zapret") setZapretStatus(ev.text, ev.error);
      else setStatus(ev.text, ev.error);
      break;
    case "log":
      if (ev.channel === "create") appendCreateLog(ev.line);
      else if (ev.channel === "loaders") appendLoaderLog(ev.line);
      else if (ev.channel === "zapret") appendZapretLog(ev.line);
      break;
    case "progress":
      if (S.busy === "zapret") setZapretProgress(ev.value, ev.total);
      else setProgress(ev.value, ev.total);
      break;
    case "busy":
      S.busy = ev.on ? ev.task : "";
      movingProgress("#loader-progress", S.busy === "loaders");
      movingProgress("#create-progress",
        !!S.busy && S.busy !== "loaders" && S.busy !== "zapret");
      movingProgress("#zapret-progress", S.busy === "zapret");
      syncBusy();
      syncMods();
      syncLoaders();
      break;
    case "refresh":
      refreshState();
      if (typeof maybeReloadHome === "function") maybeReloadHome();
      break;
    case "mirror":
      if (typeof showMirrorPrompt === "function") {
        showMirrorPrompt(ev.host || "", ev.mirror || "");
      }
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
    case "play": {
      const slug = ev.slug || (S.instance ? S.instance.slug : "");
      clearStarting(slug);
      if (ev.ok) {
        if (ev.starting) {
          markStarting(slug);
        } else {
          markRunning(slug);
        }
        setStatus(ev.message || "Game started.");
      } else {
        clearRunning(slug);
        setStatus(ev.message || "Could not start the game.", true);
      }
      syncPlay();
      break;
    }
    case "gameproc": {
      const slug = ev.slug || (S.instance ? S.instance.slug : "");
      if (!ev.running) {
        clearRunning(slug);
        clearStarting(slug);
        syncPlay();
        // The save was written while playing, so the world order changes.
        if (typeof maybeReloadHome === "function") maybeReloadHome();
        if (ev.crashed) {
          showErrorToast(ev.message || "Minecraft closed unexpectedly.",
                         "Game crash");
        }
        if (ev.message) setStatus(ev.message, !!ev.crashed);
      }
      break;
    }
    default:
      break;
  }
}

function setProgress(done, total) {
  const loader = S.busy === "loaders" || lb.busy;
  if (!total) {
    movingProgress("#create-progress", false);
    movingProgress("#loader-progress", false);
    // A phase without a byte count (or a finished download) falls back to the
    // moving stripe while the task is still running.
    if (S.busy === "loaders" || lb.busy) movingProgress("#loader-progress", true);
    else if (S.busy) movingProgress("#create-progress", true);
    return;
  }
  const bar = loader ? $("#loader-progress") : $("#create-progress");
  bar.classList.remove("indeterminate");
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
                    "btn-pane-backup", "btn-pane-icon", "btn-pane-edit",
                    "btn-pick-background"]) {
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
  syncZapret();
}
