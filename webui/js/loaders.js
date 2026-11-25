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
  startLoaderActivity(`Looking up ${lb.label} builds for ${S.instance.base}…`);
  syncLoaders();
  call("builds", LOADER_KEYS[lb.label], S.instance.base).then((result) => {
    lb.loading = false;
    lb.builds = result.builds || [];
    lb.selected = lb.builds.length ? 0 : -1;
    renderLoaderBuilds();
    stopLoaderActivity();
    if (result.note) appendLoaderLog(result.note);
    if (result.error) {
      lb.key = "";
      setLoaderStatus(`Could not list builds: ${result.error}`, true);
    } else if (!lb.builds.length) {
      setLoaderStatus(`No ${lb.label} builds for ${S.instance.base} — try another loader or Refresh.`);
    } else {
      setLoaderStatus(`${lb.builds.length} builds found — press Install loader`);
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
  const install = $("#btn-install-loader");
  install.disabled = busy || lb.loading;
  gateControl(install, lb.selected < 0 ? "Choose a loader build first." : "");
  $("#btn-cancel-loader").classList.toggle("hidden", !busy);
  $("#btn-refresh-loader-builds").disabled = busy || lb.loading;
}

/* ------------------------------------------------- loader activity feedback
   Long installs (an installer JAR, then its background library downloads)
   print nothing for minutes at a time. A moving progress stripe plus a
   running clock show that the launcher is still working, not hung. */

function loaderActive() {
  return lb.busy || lb.loading;
}

function loaderElapsed() {
  const seconds = Math.max(0, Math.floor((Date.now() - lb.startedAt) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function loaderStatusText() {
  if (!lb.statusText) return "";
  if (!loaderActive() || !lb.startedAt) return lb.statusText;
  return `${lb.statusText} (${loaderElapsed()})`;
}

function setLoaderStatus(text, error = false) {
  lb.statusText = String(text == null ? "" : text);
  lb.statusError = !!error;
  screenStatus("loaders", loaderStatusText(), lb.statusError);
}

function loaderProgress(on) {
  movingProgress("#loader-progress", on);
}

/* One shared helper for both long-task bars: a determinate width when a size
   is known, a moving stripe when it is not. */
function movingProgress(selector, on) {
  const bar = $(selector);
  if (!bar) return;
  if (on) {
    bar.style.width = "";
    bar.classList.add("indeterminate");
  } else {
    bar.classList.remove("indeterminate");
    bar.style.width = "0";
  }
}

function startLoaderActivity(text) {
  setLoaderStatus(text);
  lb.startedAt = Date.now();
  if (lb.ticker) window.clearInterval(lb.ticker);
  lb.ticker = window.setInterval(() => {
    if (!loaderActive()) return;
    screenStatus("loaders", loaderStatusText());
  }, 1000);
  loaderProgress(true);
}

function stopLoaderActivity() {
  if (lb.ticker) window.clearInterval(lb.ticker);
  lb.ticker = null;
  lb.startedAt = 0;
  loaderProgress(false);
  screenStatus("loaders", lb.statusText);
}

async function installLoader() {
  if (!S.instance || lb.busy || lb.selected < 0) return;
  const build = lb.builds[lb.selected];
  if (!build) return;
  lb.busy = true;
  clearLoaderLog();
  startLoaderActivity(`Installing ${lb.label} ${build.version} for ${S.instance.base}…`);
  syncLoaders();
  let result;
  try {
    result = await call("loader_install", LOADER_KEYS[lb.label], build.version);
  } finally {
    lb.busy = false;
    stopLoaderActivity();
    syncLoaders();
  }
  if (result.ok && result.state) {
    lb.key = stateInstanceKey(result.state);
    applyState(result.state);
    if (result.message) setStatus(result.message);
    setLoaderStatus(result.message || lb.statusText);
  } else if (result.cancelled) {
    setLoaderStatus("Cancelled.");
  } else {
    setLoaderStatus(result.error || "Install failed.", true);
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
