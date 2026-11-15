"use strict";

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
