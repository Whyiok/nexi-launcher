/* Nexi Launcher setup / uninstaller — page logic.
   Talks to Python through window.pywebview.api (see SetupApi in installer.py). */
(function () {
  "use strict";

  const I18N = {
    ru: {
      brand: "установка",
      setup_title: "Установка Nexi Launcher",
      uninstall_title: "Удаление Nexi Launcher",
      eyebrow_install: "Nexi Launcher · установка",
      eyebrow_uninstall: "Nexi Launcher · удаление",
      install_title: "Установка Nexi Launcher",
      install_sub: "Лаунчер Minecraft с изолированными сборками, модами и несколькими аккаунтами.",
      folder_label: "Папка установки",
      browse: "Обзор…",
      desktop: "Создать ярлык на рабочем столе",
      launch: "Запустить Nexi Launcher после установки",
      install: "Установить",
      installing: "Установка…",
      cancel: "Отмена",
      step_copy: "Копирование файлов…",
      step_shortcuts: "Создание ярлыков…",
      step_registry: "Регистрация в Windows…",
      step_finish: "Завершение…",
      done_title: "Готово",
      done_sub: "Nexi Launcher установлен и добавлен в список программ Windows.",
      run: "Запустить",
      close: "Закрыть",
      warn_webview: "Не найден Microsoft Edge WebView2 Runtime — без него интерфейс лаунчера не запустится.",
      webview_link: "Скачать",
      running_title: "Nexi Launcher запущен",
      running_text: "Чтобы продолжить, лаунчер нужно закрыть. Закрыть его сейчас?",
      running_ok: "Закрыть и продолжить",
      bad_dir: "Укажите папку установки.",
      err_busy: "Другой процесс уже выполняется.",
      err_bridge: "Нет связи с установщиком.",
      unknown_error: "Неизвестная ошибка.",
      error_title: "Не удалось установить",
      uninstall_error_title: "Не удалось удалить",
      uninstall_sub: "Лаунчер и его ярлыки будут удалены с этого компьютера.",
      installed_in: "Установлен в",
      remove_data: "Также удалить аккаунты, настройки и сборки",
      remove_data_hint: "Аккаунты и токены, настройки, журналы и все сборки в %APPDATA%\\NexiLauncher будут удалены безвозвратно.",
      uninstall: "Удалить",
      uninstalling: "Удаление…",
      uninstall_done: "Nexi Launcher удалён",
      uninstall_kept: "Аккаунты, настройки и сборки сохранены.",
      uninstall_removed_data: "Аккаунты, настройки и сборки также удалены.",
      not_installed: "Nexi Launcher не установлен",
      not_installed_sub: "На этом компьютере не найдена установленная копия лаунчера.",
      footer: "Установка для текущего пользователя · права администратора не нужны",
      footer_uninstall: "Удаление для текущего пользователя",
      minimize: "Свернуть",
      close_window: "Закрыть",
    },
    en: {
      brand: "launcher setup",
      setup_title: "Nexi Launcher Setup",
      uninstall_title: "Uninstall Nexi Launcher",
      eyebrow_install: "Nexi Launcher · setup",
      eyebrow_uninstall: "Nexi Launcher · remove",
      install_title: "Nexi Launcher Setup",
      install_sub: "A Minecraft launcher with isolated builds, mods and several accounts.",
      folder_label: "Install folder",
      browse: "Browse…",
      desktop: "Create a desktop shortcut",
      launch: "Start Nexi Launcher after installing",
      install: "Install",
      installing: "Installing…",
      cancel: "Cancel",
      step_copy: "Copying files…",
      step_shortcuts: "Creating shortcuts…",
      step_registry: "Registering with Windows…",
      step_finish: "Finishing…",
      done_title: "Done",
      done_sub: "Nexi Launcher is installed and listed in Windows Settings → Apps.",
      run: "Start",
      close: "Close",
      warn_webview: "Microsoft Edge WebView2 Runtime was not found. The launcher interface needs it.",
      webview_link: "Download",
      running_title: "Nexi Launcher is running",
      running_text: "It has to be closed to continue. Close it now?",
      running_ok: "Close and continue",
      bad_dir: "Choose an install folder.",
      err_busy: "Another task is already running.",
      err_bridge: "Lost the connection to the installer.",
      unknown_error: "Unknown error.",
      error_title: "Installation failed",
      uninstall_error_title: "Uninstall failed",
      uninstall_sub: "The launcher and its shortcuts will be removed from this computer.",
      installed_in: "Installed in",
      remove_data: "Also delete accounts, settings and builds",
      remove_data_hint: "Accounts and tokens, settings, logs and every build in %APPDATA%\\NexiLauncher will be deleted permanently.",
      uninstall: "Uninstall",
      uninstalling: "Uninstalling…",
      uninstall_done: "Nexi Launcher has been removed",
      uninstall_kept: "Accounts, settings and builds were kept.",
      uninstall_removed_data: "Accounts, settings and builds were deleted too.",
      not_installed: "Nexi Launcher is not installed",
      not_installed_sub: "No installed copy of the launcher was found on this computer.",
      footer: "Per-user install · no administrator rights needed",
      footer_uninstall: "Per-user uninstall",
      minimize: "Minimize",
      close_window: "Close",
    },
  };

  const hash = location.hash || "";
  let LANG = /(?:^|[#&])lang=ru(?:&|$)/.test(hash) ? "ru" : "en";
  const MODE = /(?:^|[#&])mode=uninstall(?:&|$)/.test(hash) ? "uninstall" : "install";
  let t = I18N[LANG];

  const S = {
    state: null,
    busy: false,
    action: null,
    timer: null,
    donePath: "",
    booted: false,
    bound: false,
  };

  const $ = (selector) => document.querySelector(selector);
  const show = (element) => { if (element) element.classList.remove("hidden"); };
  const hide = (element) => { if (element) element.classList.add("hidden"); };
  const setDisabled = (selector, value) => {
    const element = $(selector);
    if (element) element.disabled = value;
  };

  /* ---------------------------------------------------------------- bridge */

  function api() {
    return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
  }

  async function call(method) {
    const bridge = api();
    if (!bridge || typeof bridge[method] !== "function") {
      throw new Error("the bridge is not ready");
    }
    return bridge[method].apply(bridge, Array.prototype.slice.call(arguments, 1));
  }

  /* ------------------------------------------------------------------ text */

  function paintLang() {
    document.querySelectorAll(".lang-btn").forEach((btn) => {
      const active = btn.getAttribute("data-lang") === LANG;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function setLanguage(lang) {
    if (!Object.prototype.hasOwnProperty.call(I18N, lang)) return;
    if (lang === LANG) {
      paintLang();
      return;
    }
    LANG = lang;
    t = I18N[LANG];
    applyText();
    const done = $("#view-done");
    const onDone = done && !done.classList.contains("hidden");
    if (S.state && !onDone) {
      render(S.state);
    }
    // The native window title (taskbar / Alt+Tab) follows the page.
    call("set_title", document.title).catch(() => {});
  }

  function applyText() {
    document.documentElement.lang = LANG;
    document.title = MODE === "install" ? t.setup_title : t.uninstall_title;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.getAttribute("data-i18n");
      if (Object.prototype.hasOwnProperty.call(t, key)) {
        element.textContent = t[key];
      }
    });
    $("#btn-min").title = t.minimize;
    $("#btn-close").title = t.close_window;
    $("#foot-note").textContent = MODE === "install" ? t.footer : t.footer_uninstall;
    const version = S.state && S.state.version ? S.state.version : "1.3.0";
    $("#foot-version").textContent = "v" + version;
    paintLang();
  }

  /* ----------------------------------------------------------------- views */

  function showView(name) {
    document.querySelectorAll(".view").forEach(hide);
    const view = $("#view-" + name);
    if (!view) return;
    view.classList.remove("enter");
    void view.offsetWidth;
    view.classList.add("enter");
    show(view);
  }

  function render(state) {
    S.state = state;
    applyText();
    if (MODE === "uninstall") {
      if (!state.installed) {
        showDone({
          title: t.not_installed,
          sub: t.not_installed_sub,
          path: "",
          info: true,
          run: false,
        });
        return;
      }
      $("#uninstall-path").textContent = state.path || "";
      showView("uninstall");
      return;
    }
    $("#install-path").value = state.path || "";
    if (state.webview2) hide($("#webview-warning"));
    else show($("#webview-warning"));
    showView("install");
  }

  /* -------------------------------------------------------------- bindings */

  function bind() {
    document.querySelectorAll(".lang-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        setLanguage(btn.getAttribute("data-lang"));
      });
    });
    $("#btn-min").addEventListener("click", () => {
      call("minimize").catch(() => {});
    });
    $("#btn-close").addEventListener("click", requestClose);
    $("#btn-cancel").addEventListener("click", requestClose);
    $("#btn-uninstall-cancel").addEventListener("click", requestClose);
    $("#btn-done-close").addEventListener("click", requestClose);
    $("#btn-browse").addEventListener("click", browse);
    $("#btn-webview").addEventListener("click", () => {
      call("open_webview2").catch(() => {});
    });
    $("#btn-install").addEventListener("click", () => startInstall(false));
    $("#btn-uninstall").addEventListener("click", () => startUninstall(false));
    $("#btn-done-run").addEventListener("click", runLauncher);
    $("#overlay-cancel").addEventListener("click", () => closeOverlay(false));
    $("#overlay-ok").addEventListener("click", () => closeOverlay(true));
    $("#install-path").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        startInstall(false);
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!$("#overlay").classList.contains("hidden")) {
        closeOverlay(false);
      } else if (!S.busy) {
        requestClose();
      }
    });
    // The bridge may appear after the page has loaded.
    window.addEventListener("pywebviewready", boot);
  }

  async function requestClose() {
    if (S.busy) return;
    try {
      await call("close_window");
    } catch (_) {
      window.close();
    }
  }

  async function browse() {
    if (S.busy) return;
    let result;
    try {
      result = await call("pick_folder", $("#install-path").value.trim());
    } catch (_) {
      return;
    }
    if (result && result.path) $("#install-path").value = result.path;
  }

  /* ---------------------------------------------------------------- busy UI */

  function setFormDisabled(disabled) {
    const targets = MODE === "install"
      ? ["#install-path", "#btn-browse", "#opt-desktop", "#opt-launch",
         "#btn-cancel", "#btn-install"]
      : ["#opt-remove-data", "#btn-uninstall-cancel", "#btn-uninstall"];
    targets.forEach((selector) => setDisabled(selector, disabled));
    setDisabled("#btn-close", disabled);
  }

  function beginBusy(action) {
    S.busy = true;
    S.action = action;
    setFormDisabled(true);
    const bar = action === "install" ? $("#install-bar") : $("#uninstall-bar");
    const status = action === "install" ? $("#install-status") : $("#uninstall-status");
    const block = action === "install" ? $("#install-progress") : $("#uninstall-progress");
    hide(action === "install" ? $("#install-error") : $("#uninstall-error"));
    bar.classList.add("indeterminate");
    bar.style.width = "";
    status.textContent = action === "install" ? t.step_copy : t.uninstalling;
    if (action === "install") $("#btn-install span").textContent = t.installing;
    else $("#btn-uninstall span").textContent = t.uninstalling;
    show(block);
    startPolling();
  }

  function endBusy() {
    S.busy = false;
    S.action = null;
    setFormDisabled(false);
    $("#btn-install span").textContent = t.install;
    $("#btn-uninstall span").textContent = t.uninstall;
  }

  function hideProgress() {
    hide($("#install-progress"));
    hide($("#uninstall-progress"));
    [$("#install-bar"), $("#uninstall-bar")].forEach((bar) => {
      bar.classList.remove("indeterminate");
      bar.style.width = "";
    });
  }

  function stepLabel(percent) {
    if (percent <= 45) return t.step_copy;
    if (percent <= 75) return t.step_shortcuts;
    if (percent < 100) return t.step_registry;
    return t.step_finish;
  }

  function applyProgress(percent) {
    const install = S.action === "install";
    const bar = install ? $("#install-bar") : $("#uninstall-bar");
    bar.classList.remove("indeterminate");
    bar.style.width = Math.max(0, Math.min(100, percent)) + "%";
    if (install) $("#install-status").textContent = stepLabel(percent);
  }

  function showError(message) {
    const install = MODE === "install";
    const banner = install ? $("#install-error") : $("#uninstall-error");
    banner.querySelector(".error-title").textContent =
      install ? t.error_title : t.uninstall_error_title;
    banner.querySelector(".error-text").textContent = message || t.unknown_error;
    show(banner);
  }

  function errorText(code) {
    if (code === "invalid_dir") return t.bad_dir;
    if (code === "busy") return t.err_busy;
    if (code === "not_installed") return t.not_installed_sub;
    return code || t.err_bridge;
  }

  /* --------------------------------------------------------------- polling */

  function startPolling() {
    if (S.timer) return;
    S.timer = setInterval(poll, 140);
  }

  function stopPolling() {
    if (S.timer) {
      clearInterval(S.timer);
      S.timer = null;
    }
  }

  async function poll() {
    let result;
    try {
      result = await call("poll");
    } catch (_) {
      return;
    }
    (result.events || []).forEach(handleEvent);
  }

  function handleEvent(event) {
    if (!event || !event.t) return;
    if (event.t === "progress") {
      if (S.busy) applyProgress(event.value);
      return;
    }
    if (event.t === "running") {
      stopPolling();
      endBusy();
      openOverlay();
      return;
    }
    if (event.t === "error") {
      stopPolling();
      endBusy();
      hideProgress();
      showError(event.error);
      return;
    }
    if (event.t === "done") {
      stopPolling();
      const action = S.action;
      endBusy();
      if (action === "install") showInstallDone(event);
      else showUninstallDone(event);
    }
  }

  /* ---------------------------------------------------------------- actions */

  async function startInstall(force) {
    if (S.busy) return;
    hide($("#install-error"));
    const path = $("#install-path").value.trim();
    if (!path) {
      showError(t.bad_dir);
      return;
    }
    let result;
    try {
      result = await call(
        "start_install",
        path,
        $("#opt-desktop").checked,
        $("#opt-launch").checked,
        !!force
      );
    } catch (_) {
      showError(t.err_bridge);
      return;
    }
    if (!result || result.ok === false) {
      showError(errorText(result && result.error));
      return;
    }
    beginBusy("install");
  }

  async function startUninstall(force) {
    if (S.busy) return;
    hide($("#uninstall-error"));
    let result;
    try {
      result = await call(
        "start_uninstall",
        $("#opt-remove-data").checked,
        !!force
      );
    } catch (_) {
      showError(t.err_bridge);
      return;
    }
    if (!result || result.ok === false) {
      showError(errorText(result && result.error));
      return;
    }
    beginBusy("uninstall");
  }

  async function runLauncher() {
    const button = $("#btn-done-run");
    button.disabled = true;
    try {
      await call("launch", S.donePath);
    } catch (_) {
      // The launcher may still start; closing the setup is harmless.
    }
    requestClose();
  }

  /* -------------------------------------------------------------- dialogs */

  function openOverlay() {
    $("#overlay-title").textContent = t.running_title;
    $("#overlay-text").textContent = t.running_text;
    $("#overlay-ok").textContent = t.running_ok;
    show($("#overlay"));
    $("#overlay-ok").focus();
  }

  function closeOverlay(confirmed) {
    hide($("#overlay"));
    if (!confirmed) return;
    if (MODE === "install") startInstall(true);
    else startUninstall(true);
  }

  /* ------------------------------------------------------------------ done */

  function showDone(options) {
    S.donePath = options.path || "";
    const mark = $("#done-mark");
    mark.classList.toggle("info", !!options.info);
    mark.querySelector("use").setAttribute(
      "href", options.info ? "#i-info" : "#i-check");
    $("#done-title").textContent = options.title;
    $("#done-sub").textContent = options.sub || "";
    const pathBox = $("#done-path");
    if (options.path) {
      pathBox.textContent = options.path;
      show(pathBox);
    } else {
      pathBox.textContent = "";
      hide(pathBox);
    }
    const warn = $("#done-warnings");
    if (options.warnings && options.warnings.length) {
      warn.textContent = options.warnings.join("\n");
      show(warn);
    } else {
      warn.textContent = "";
      hide(warn);
    }
    if (options.run) show($("#btn-done-run"));
    else hide($("#btn-done-run"));
    $("#btn-done-close").textContent = t.close;
    showView("done");
  }

  function showInstallDone(event) {
    showDone({
      title: t.done_title,
      sub: t.done_sub,
      path: event.path || (S.state && S.state.path) || "",
      run: !event.launched,
      warnings: event.warnings || [],
    });
  }

  function showUninstallDone(event) {
    if (event.relaunched) {
      // A detached copy deletes the folder; this process has to exit first.
      requestClose();
      return;
    }
    showDone({
      title: t.uninstall_done,
      sub: event.kept_data ? t.uninstall_kept : t.uninstall_removed_data,
      path: "",
      run: false,
    });
  }

  /* ------------------------------------------------------------------ boot */

  async function init(attempt) {
    applyText();
    if (!S.bound) {
      bind();
      S.bound = true;
    }
    try {
      const state = await call("state");
      render(state);
    } catch (_) {
      // The bridge can appear a moment before it is able to serve calls
      // (more noticeable in the frozen build). Give it a few tries before
      // telling the user it is broken.
      if ((attempt || 0) < 25) {
        setTimeout(function () { init((attempt || 0) + 1); }, 120);
        return;
      }
      failBridge();
    }
  }

  function failBridge() {
    showView(MODE === "install" ? "install" : "uninstall");
    showError(t.err_bridge);
    setDisabled("#btn-install", true);
    setDisabled("#btn-uninstall", true);
  }

  function boot() {
    // Text and buttons work without Python: the language switch and the
    // window controls must not depend on the bridge.
    applyText();
    if (!S.bound) {
      bind();
      S.bound = true;
    }
    if (S.booted) return;
    const bridge = api();
    // pywebview defines `window.pywebview` before it adds the API methods,
    // and an empty object is truthy — wait for the method we actually need.
    if (!bridge || typeof bridge.state !== "function") {
      S.bootTries = (S.bootTries || 0) + 1;
      if (S.bootTries > 240) {
        S.booted = true;
        failBridge();
        return;
      }
      setTimeout(boot, 50);
      return;
    }
    S.booted = true;
    init(0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
