"use strict";

/* ------------------------------------------------------ settings sections */

let settingsTab = "account";
/* The Logs section keeps its own small rail for each log source. */
let logsTab = "launcher";

function setSettingsTab(name, instant = false) {
  const bar = $("#settings-tabs");
  if (!bar) return;
  const tabs = [...bar.querySelectorAll(":scope > [data-settings-tab]")];
  const names = tabs.map((tab) => tab.dataset.settingsTab);
  const target = names.includes(name) ? name : (names[0] || "account");
  settingsTab = target;
  for (const tab of tabs) {
    const on = tab.dataset.settingsTab === target;
    tab.classList.toggle("on", on);
    tab.setAttribute("aria-selected", on ? "true" : "false");
    tab.tabIndex = on ? 0 : -1;
  }
  $$(".settings-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.dataset.settingsPane === target);
  });
  updateSegFill(bar, instant);
  // Logs only tail while their own section is on screen.
  if (typeof stopLogsTimer === "function" && target !== "logs") {
    stopLogsTimer();
  }
  if (screen === "settings" && target === "logs"
      && typeof openLogs === "function") {
    openLogs();
  }
  // The skin editor lives in the Accounts pane: it only animates and loads
  // while that pane is actually visible.
  if (typeof stopSkinView === "function"
      && (screen !== "settings" || target !== "account")) {
    stopSkinView();
  }
  if (screen === "settings" && target === "account"
      && typeof loadSkin === "function") {
    loadSkin();
  }
}

function setLogsTab(name, instant = false) {
  const bar = $("#logs-tabs");
  if (!bar) return;
  const tabs = [...bar.querySelectorAll(":scope > [data-logs-tab]")];
  const names = tabs.map((tab) => tab.dataset.logsTab);
  const target = names.includes(name) ? name : (names[0] || "launcher");
  logsTab = target;
  for (const tab of tabs) {
    const on = tab.dataset.logsTab === target;
    tab.classList.toggle("on", on);
    tab.setAttribute("aria-selected", on ? "true" : "false");
    tab.tabIndex = on ? 0 : -1;
  }
  $$(".logs-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.dataset.logsPane === target);
  });
  updateSegFill(bar, instant);
  if (target === "launcher" && screen === "settings" && settingsTab === "logs"
      && typeof openLogs === "function") {
    openLogs();
  } else if (typeof stopLogsTimer === "function") {
    stopLogsTimer();
  }
  if (target === "network") {
    const netConsole = $("#net-console");
    if (netConsole) netConsole.scrollTop = netConsole.scrollHeight;
  }
}

function bindLogsTabs() {
  const bar = $("#logs-tabs");
  if (!bar || bar.dataset.ready === "1") return;
  bar.dataset.ready = "1";
  bar.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-logs-tab]");
    if (!tab || tab.parentElement !== bar) return;
    setLogsTab(tab.dataset.logsTab);
  });
  bar.addEventListener("keydown", (event) => {
    const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
    const backward = event.key === "ArrowLeft" || event.key === "ArrowUp";
    if (!forward && !backward) return;
    const tabs = [...bar.querySelectorAll(":scope > [data-logs-tab]")];
    const index = tabs.findIndex((tab) => tab.dataset.logsTab === logsTab);
    const step = forward ? 1 : -1;
    const next = tabs[(index + step + tabs.length) % tabs.length];
    if (!next) return;
    event.preventDefault();
    setLogsTab(next.dataset.logsTab);
    next.focus();
  });
}

function bindSettingsTabs() {
  const bar = $("#settings-tabs");
  if (!bar || bar.dataset.ready === "1") return;
  bar.dataset.ready = "1";
  bar.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-settings-tab]");
    if (!tab || tab.parentElement !== bar) return;
    setSettingsTab(tab.dataset.settingsTab);
  });
  bar.addEventListener("keydown", (event) => {
    const forward = event.key === "ArrowDown" || event.key === "ArrowRight";
    const backward = event.key === "ArrowUp" || event.key === "ArrowLeft";
    if (!forward && !backward) return;
    const tabs = [...bar.querySelectorAll(":scope > [data-settings-tab]")];
    const index = tabs.findIndex(
      (tab) => tab.dataset.settingsTab === settingsTab);
    const step = forward ? 1 : -1;
    const next = tabs[(index + step + tabs.length) % tabs.length];
    if (!next) return;
    event.preventDefault();
    setSettingsTab(next.dataset.settingsTab);
    next.focus();
  });
}

/* -------------------------------------------------------------- settings */

function fillSettings() {
  const javaInput = $("#java-path");
  if (document.activeElement !== javaInput) javaInput.value = S.java || "";
  $("#btn-auto-java").disabled = !S.java;
  $("#java-hint").textContent = S.java
    ? "Custom Java — Minecraft starts with this executable."
    : "Leave empty — the launcher downloads the Java runtime each " +
      "version needs (once per Java version).";

  $("#settings-shared").textContent = (S.paths && S.paths.shared) || "—";
  $("#settings-instances").textContent = (S.paths && S.paths.instances) || "—";

  fillAccount();
  fillTheme();
  fillBackground();
  fillGameDefaults();
  fillZapret();
  if (typeof fillUpdate === "function") fillUpdate();
  if (typeof renderMirrorMode === "function") renderMirrorMode();
  if (typeof renderNetworkSettings === "function") renderNetworkSettings();
}

function fillBackground() {
  const bg = S.background;
  const active = !!(bg && bg.active);
  const name = $("#background-name");
  if (name) name.textContent = active
    ? (bg.name || "Background") : "Panorama";
  const clear = $("#btn-clear-background");
  if (clear) clear.disabled = !active;
  const pick = $("#btn-pick-background");
  if (pick) pick.disabled = !!S.busy;
}

function fillTheme() {
  const theme = THEMES.includes(S.theme) ? S.theme : "mint";
  $$("#theme-grid [data-theme-option]").forEach((button) => {
    const on = button.dataset.themeOption === theme;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
  });
  const label = $("#theme-name");
  if (label) label.textContent = THEME_NAMES[theme];

  const mode = MODES.includes(S.color_mode) ? S.color_mode : "dark";
  $$("#mode-seg [data-mode-option]").forEach((button) => {
    button.classList.toggle("on", button.dataset.modeOption === mode);
    button.setAttribute("aria-checked",
                        button.dataset.modeOption === mode ? "true" : "false");
  });
  const language = LANGUAGES.includes(S.language) ? S.language : "en";
  $$("#lang-seg [data-lang-option]").forEach((button) => {
    button.classList.toggle("on", button.dataset.langOption === language);
    button.setAttribute("aria-checked",
                        button.dataset.langOption === language ? "true" : "false");
  });
  const pet = PET_OPTIONS.includes(S.pet) ? S.pet : "axi";
  $$("#pet-seg [data-pet-option]").forEach((button) => {
    const on = button.dataset.petOption === pet;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
  });
  updateSegFill($("#mode-seg"));
  updateSegFill($("#lang-seg"));
  updateSegFill($("#pet-seg"));
}

function accountAvatar(account) {
  const avatar = document.createElement("span");
  avatar.className = "account-avatar";
  if (account.type === "microsoft"
      && /^[0-9a-f]{32}$/i.test(account.uuid || "")) {
    const img = document.createElement("img");
    img.alt = "";
    img.referrerPolicy = "no-referrer";
    img.src = `https://mc-heads.net/avatar/${account.uuid}/80`;
    img.addEventListener("error", () => {
      img.remove();
      avatar.textContent = (account.name || "?").slice(0, 1);
    });
    avatar.appendChild(img);
  } else if (account.type === "ely" && account.name) {
    const url = "https://skinsystem.ely.by/skins/"
      + encodeURIComponent(account.name) + ".png";
    avatar.textContent = account.name.slice(0, 1);
    const probe = new Image();
    probe.addEventListener("load", () => {
      if (!avatar.isConnected) return;
      const head = document.createElement("div");
      head.className = "skin-head";
      head.style.backgroundImage = `url("${url}")`;
      head.style.backgroundPosition =
        `${(64 / (7 * probe.naturalWidth)) * 100}% ` +
        `${(64 / (7 * probe.naturalHeight)) * 100}%`;
      avatar.replaceChildren(head);
    });
    probe.src = url;
  } else {
    avatar.textContent = (account.name || "?").slice(0, 1);
  }
  return avatar;
}

function siteSkinNode(type, name, uuid) {
  const holder = document.createElement("span");
  holder.className = "site-skin";
  const initial = (name || "?").slice(0, 1).toUpperCase();
  holder.textContent = initial;
  if (type === "microsoft" && /^[0-9a-f]{32}$/i.test(uuid || "")) {
    const img = document.createElement("img");
    img.alt = "";
    img.referrerPolicy = "no-referrer";
    img.src = `https://mc-heads.net/avatar/${uuid}/64`;
    img.addEventListener("error", () => {
      img.remove();
      holder.textContent = initial;
    });
    holder.replaceChildren(img);
  } else if (type === "ely" && name) {
    const url = "https://skinsystem.ely.by/skins/"
      + encodeURIComponent(name) + ".png";
    const probe = new Image();
    probe.addEventListener("load", () => {
      if (!holder.isConnected) return;
      const head = document.createElement("div");
      head.className = "skin-head";
      head.style.backgroundImage = `url("${url}")`;
      holder.replaceChildren(head);
    });
    probe.src = url;
  }
  return holder;
}

function renderSiteButton() {
  const button = $("#btn-site-profile");
  if (!button) return;
  const accounts = S.accounts || [];
  const nexi = accounts.find((account) => account.type === "nexi") || null;
  const active = accounts.find((account) => account.active)
    || accounts.find((account) => account.id === S.active_account) || null;
  const linked = (nexi && nexi.mc) || {};
  const linkedSkin = (linked.type === "microsoft"
    && /^[0-9a-f]{32}$/i.test(linked.uuid || ""))
    || (linked.type === "ely" && !!linked.name);
  const source = linkedSkin ? linked : (active || {});
  const type = source.type || "offline";
  const uuid = source.uuid || "";
  let name = source.name || "";
  if (!name && nexi) name = nexi.name;
  button.replaceChildren(siteSkinNode(type, name, uuid));
  const title = nexi
    ? "Open your profile on the Nexi site"
    : "Sign in with Nexi to open your site profile";
  button.title = title;
  button.setAttribute("aria-label", title);
}

function renderAccountList(accounts) {
  const list = $("#account-list");
  if (!list) return;
  list.replaceChildren();
  const gameAccounts = accounts.filter((account) => account.type !== "nexi");
  if (!gameAccounts.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "No accounts yet — add one below.";
    list.appendChild(empty);
    return;
  }
  for (const account of gameAccounts) {
    const row = document.createElement("div");
    row.className = "account-item" + (account.active ? " on" : "");
    row.dataset.accountId = account.id;
    const grip = document.createElement("span");
    grip.className = "account-grip";
    grip.setAttribute("aria-hidden", "true");
    row.appendChild(grip);
    row.appendChild(accountAvatar(account));
    const text = document.createElement("div");
    text.className = "setting-text";
    const name = document.createElement("span");
    name.className = "account-name";
    name.textContent = account.name;
    const hint = document.createElement("span");
    hint.className = "hint";
    if (account.type === "nexi") {
      const mcName = account.mc && account.mc.name;
      hint.textContent = "Nexi account"
        + (account.handle ? ` · ${account.handle}` : "")
        + (mcName ? ` · MC: ${mcName}` : "");
    } else {
      hint.textContent = account.type === "microsoft"
        ? "Microsoft account"
        : account.type === "ely" ? "Ely.by account" : "Offline account";
    }
    text.append(name, hint);
    row.appendChild(text);
    if (account.active) {
      const badge = document.createElement("span");
      badge.className = "account-badge";
      badge.textContent = "Active";
      row.appendChild(badge);
    } else {
      const use = document.createElement("button");
      use.type = "button";
      use.className = "btn sm ghost";
      use.dataset.accountUse = account.id;
      use.textContent = "Use";
      row.appendChild(use);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn sm ghost";
    remove.dataset.accountRemove = account.id;
    remove.title = `Remove ${account.name}`;
    remove.textContent = "Remove";
    row.appendChild(remove);
    list.appendChild(row);
  }
}

function fillAccount() {
  const ms = S.ms || {};
  const ely = S.ely || {};
  const accounts = S.accounts || [];
  const gameAccounts = accounts.filter((account) => account.type !== "nexi");
  const activeAccount = gameAccounts.find((account) => account.active) || null;
  const provider = activeAccount ? activeAccount.type : "offline";

  const input = $("#ms-client-id");
  if (input && document.activeElement !== input) {
    input.value = ms.client_id || "";
    input.placeholder = ms.built_in
      ? "Built-in Client ID is used" : "Application (client) ID";
  }

  $("#account-status").textContent =
    provider === "microsoft" ? "microsoft"
      : provider === "ely" ? "ely.by" : "offline";

  renderAccountList(accounts);

  const nexiAccount = accounts.find((account) => account.type === "nexi")
    || null;
  const nexiStatus = $("#nexi-status");
  if (nexiStatus) {
    nexiStatus.textContent = nexiAccount ? "signed in" : "not signed in";
  }
  const showNexiProfile = !!nexiAccount && !nexiFlow.active;
  $("#nexi-signed-out").classList.toggle(
    "hidden", !!nexiAccount || nexiFlow.active);
  $("#nexi-signin").classList.toggle(
    "hidden", !!nexiAccount || nexiFlow.active);
  $("#nexi-code-box").classList.toggle("hidden", !nexiFlow.active);
  $("#nexi-profile").classList.toggle("hidden", !showNexiProfile);
  if (showNexiProfile) fillNexiProfile(nexiAccount);
  const baseUrl = $("#nexi-base-url");
  if (baseUrl && document.activeElement !== baseUrl) {
    baseUrl.value = (S.nexi && S.nexi.base_url) || "";
  }

  $("#account-signed-out").classList.toggle("hidden", msFlow.active);
  $("#ms-code").classList.toggle("hidden", !msFlow.active);
  $("#ely-wait").classList.toggle("hidden", !elyFlow.active);
  $("#btn-ely-browser").disabled = elyFlow.active;
  for (const method of ["microsoft", "ely", "offline"]) {
    $("#panel-" + method).classList.toggle(
      "hidden", method !== accountMethod);
    $("#btn-method-" + method).classList.toggle(
      "on", accountMethod === method);
  }

  const oauth = ely.oauth || {};
  const oauthId = $("#ely-oauth-client-id");
  if (oauthId && document.activeElement !== oauthId) {
    oauthId.value = oauth.client_id || "";
    oauthId.placeholder = oauth.built_in
      ? "Built-in Client ID is used" : "Client ID from account.ely.by";
  }
  const oauthRedirect = $("#ely-oauth-redirect");
  if (oauthRedirect && document.activeElement !== oauthRedirect) {
    oauthRedirect.value = oauth.redirect_uri
      || "http://localhost:26206/ely-callback";
  }
  const oauthSecret = $("#ely-oauth-client-secret");
  if (oauthSecret) {
    if (document.activeElement !== oauthSecret) oauthSecret.value = "";
    oauthSecret.placeholder = oauth.pkce
      ? "Leave blank to use PKCE (no secret)"
      : "Saved — leave blank to keep";
  }
  $("#ely-browser-hint").textContent = oauth.configured
    ? "A browser page opens on ely.by — sign in there and the launcher "
      + "adds that account automatically. No password to type here."
    : "Browser sign-in is not configured yet. Open “Advanced: browser "
      + "sign-in (OAuth) setup” below and add an Ely.by Client ID — a "
      + "“Desktop application” app (PKCE) needs no secret — or use the "
      + "password form.";
  $("#ely-oauth-status").textContent = oauth.configured
    ? (oauth.built_in && !oauth.client_id
      ? "Browser sign-in is ready — a built-in Ely.by Client ID is used "
        + "(PKCE, no secret). You can override it below."
      : "Browser sign-in is configured. You can change the credentials below "
        + "at any time.")
    : "Browser sign-in only needs an Ely.by Client ID for a “Desktop "
      + "application” (PKCE, no secret). A “Website” app also works — then "
      + "paste its Client Secret too. Enter them here once; everyone using "
      + "this copy of the launcher can then sign in with the button above.";
  renderSiteButton();
  if (typeof renderFriendsGate === "function") renderFriendsGate();
  updateSegFill($("#account-methods"));
}

function fillNexiProfile(account) {
  const mc = account.mc || {};
  $("#nexi-avatar").textContent =
    (account.name || "?").slice(0, 1).toUpperCase();
  $("#nexi-name").textContent = account.name || "Nexi account";
  const handle = [];
  if (account.handle) handle.push(account.handle);
  if (account.nexi_id) handle.push(`Nexi ID: ${account.nexi_id}`);
  $("#nexi-handle").textContent = handle.join(" · ") || "—";

  $("#nexi-mc-name").textContent = mc.name || "—";
  const mcHint = [mc.label || "Offline", mc.custom ? "linked" : "default"];
  if (mc.uuid) mcHint.push(mc.uuid);
  $("#nexi-mc-hint").textContent = mcHint.join(" · ");

  const linkBtn = $("#btn-nexi-link-mc");
  const unlinkBtn = $("#btn-nexi-unlink-mc");
  const linked = !!mc.custom;
  linkBtn.textContent = linked ? "Change linked account" : "Link account";
  unlinkBtn.classList.toggle("hidden", !linked);
}

function setAccountMethod(method) {
  if (!["microsoft", "ely", "offline"].includes(method)) return;
  accountMethod = method;
  fillAccount();
  if (method === "ely") $("#ely-username").focus();
}

async function nexiLogin() {
  const login = $("#nexi-login").value.trim();
  const password = $("#nexi-password").value;
  if (!login || !password) {
    setStatus("Enter your Nexi ID and password.", true);
    return;
  }
  const button = $("#btn-nexi-login");
  button.disabled = true;
  setStatus("Sending the sign-in code…");
  const result = await call("nexi_login", login, password);
  button.disabled = false;
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Nexi sign-in failed.", true);
    return;
  }
  nexiFlow.active = true;
  nexiFlow.login = login;
  nexiFlow.email = result.email || "";
  $("#nexi-password").value = "";
  $("#nexi-code").value = "";
  $("#nexi-code-hint").textContent = nexiFlow.email
    ? `We sent a 6-digit code to ${nexiFlow.email}. It is valid for 15 minutes.`
    : "We sent a 6-digit code to the e-mail on the account.";
  fillAccount();
  $("#nexi-code").focus();
  setStatus("Enter the code from the e-mail.");
}

async function nexiBrowserLogin() {
  const button = $("#btn-nexi-browser");
  if (button) button.disabled = true;
  setStatus("Waiting for Nexi sign-in in the browser…");
  const result = await call("nexi_browser_login");
  if (!result || !result.ok) {
    if (button) button.disabled = false;
    setStatus((result && result.error) || "Could not start browser sign-in.",
      true);
  }
}

async function nexiVerify() {
  const code = $("#nexi-code").value.trim();  if (!code) {
    setStatus("Enter the 6-digit code from the e-mail.", true);
    return;
  }
  const button = $("#btn-nexi-verify");
  button.disabled = true;
  const result = await call("nexi_verify", code, nexiFlow.login || "");
  button.disabled = false;
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not confirm the code.", true);
    return;
  }
  nexiFlow.active = false;
  nexiFlow.login = "";
  nexiFlow.email = "";
  $("#nexi-code").value = "";
  if (result.state) applyState(result.state);
  else fillAccount();
  setStatus(`Signed in as ${result.name || "your Nexi account"}.`);
}

async function nexiCancel() {
  await call("nexi_cancel_login");
  nexiFlow.active = false;
  nexiFlow.login = "";
  nexiFlow.email = "";
  $("#nexi-code").value = "";
  fillAccount();
  setStatus("Nexi sign-in cancelled.");
}

async function nexiLogout() {
  const result = await call("nexi_logout");
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not sign out of Nexi.", true);
    return;
  }
  nexiFlow.active = false;
  nexiFlow.login = "";
  nexiFlow.email = "";
  if (result.state) applyState(result.state);
  setStatus("Signed out of Nexi.");
}

async function nexiRefresh() {
  const result = await call("nexi_profile");
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not refresh the Nexi profile.", true);
    if (result && result.state) applyState(result.state);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus("Nexi profile refreshed.");
}

async function nexiLinkMc() {
  const result = await call("nexi_link_start");
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not start linking the Minecraft account.", true);
    if (result && result.state) applyState(result.state);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus("Choose an account in the launcher window.");
}

/* The site opened nexi://link?token=... or the launcher asked the site for a
   link: offer the accounts that are actually signed in here. */
const nexiLink = { token: "", busy: false, selected: "" };

function nexiLinkStatus(text, error = false) {
  const node = $("#nexi-link-status");
  if (!node) return;
  node.textContent = text || "";
  node.classList.toggle("hidden", !text);
  node.classList.toggle("error", !!error);
}

function nexiLinkAccountType(account) {
  return account.type === "microsoft" ? "Microsoft" : "Ely.by";
}

function syncNexiLinkButtons() {
  const confirm = $("#btn-nexi-link-confirm");
  if (!confirm) return;
  const rows = $$("#nexi-link-accounts .nexi-link-account").length;
  confirm.disabled = nexiLink.busy || !rows || !nexiLink.selected;
}

function renderNexiLinkAccounts(accounts) {
  const box = $("#nexi-link-accounts");
  if (!box) return;
  box.replaceChildren();
  if (!accounts.length) {
    const empty = document.createElement("p");
    empty.className = "nexi-link-empty";
    empty.textContent = "No Microsoft or Ely.by account is signed in here. "
      + "Sign in under Settings → Accounts, then start the link again.";
    box.appendChild(empty);
    return;
  }
  for (const account of accounts) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "nexi-link-account"
      + (account.id === nexiLink.selected ? " on" : "");
    row.dataset.accountId = account.id;
    row.appendChild(accountAvatar(account));
    const main = document.createElement("span");
    main.className = "nexi-link-account-main";
    const name = document.createElement("span");
    name.className = "nexi-link-account-name";
    name.textContent = account.name || "Player";
    const type = document.createElement("span");
    type.className = "nexi-link-account-type";
    type.textContent = nexiLinkAccountType(account);
    main.append(name, type);
    row.appendChild(main);
    row.addEventListener("click", () => {
      nexiLink.selected = account.id;
      renderNexiLinkAccounts(accounts);
      nexiLinkStatus("");
      syncNexiLinkButtons();
    });
    box.appendChild(row);
  }
}

function showNexiLinkPrompt(ev) {
  const modal = $("#nexi-link-modal");
  if (!modal) return;
  const accounts = Array.isArray(ev.accounts) ? ev.accounts : [];
  nexiLink.token = String(ev.token || "");
  nexiLink.busy = false;
  nexiLink.selected = (accounts.find((account) => account.active)
    || accounts[0] || {}).id || "";
  const text = $("#nexi-link-text");
  if (text) {
    const who = String(ev.display_name || "Nexi ID");
    const handle = ev.handle ? ` (${ev.handle})` : "";
    text.textContent = `Link a Minecraft account to Nexi ID ${who}${handle}? `
      + "Choose the account you are signed in with — it will be saved on "
      + "the site.";
  }
  renderNexiLinkAccounts(accounts);
  nexiLinkStatus("");
  syncNexiLinkButtons();
  document.body.classList.add("mirror-open");
  modal.classList.remove("hidden");
  const confirm = $("#btn-nexi-link-confirm");
  if (confirm && !confirm.disabled) confirm.focus();
}

function closeNexiLinkPrompt() {
  const modal = $("#nexi-link-modal");
  if (modal) modal.classList.add("hidden");
  document.body.classList.remove("mirror-open");
  nexiLink.token = "";
  nexiLink.selected = "";
  nexiLink.busy = false;
  nexiLinkStatus("");
}

async function nexiLinkConfirm() {
  if (nexiLink.busy || !nexiLink.token || !nexiLink.selected) return;
  nexiLink.busy = true;
  syncNexiLinkButtons();
  nexiLinkStatus("Linking…");
  const result = await call("nexi_link_account", nexiLink.token,
    nexiLink.selected);
  nexiLink.busy = false;
  if (!result || !result.ok) {
    nexiLinkStatus((result && result.error)
      || "Could not link the Minecraft account.", true);
    syncNexiLinkButtons();
    if (result && result.state) applyState(result.state);
    return;
  }
  if (result.state) applyState(result.state);
  closeNexiLinkPrompt();
  setStatus(result.message || "Minecraft account linked.");
}

async function nexiUnlinkMc() {
  const result = await call("nexi_unlink_minecraft");
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not unlink the Minecraft account.", true);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus(result.message || "Minecraft link removed.");
}

async function saveNexiBaseUrl() {
  const value = $("#nexi-base-url").value.trim();
  const result = await call("set_nexi_base_url", value);
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not save the Nexi site address.", true);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus("Nexi site address saved.");
}

async function elyLogin() {
  const username = $("#ely-username").value.trim();
  const password = $("#ely-password").value;
  const totp = $("#ely-totp").value.trim();
  if (!username || !password) {
    setStatus("Enter your Ely.by e-mail/username and password.", true);
    return;
  }
  const button = $("#btn-ely-login");
  button.disabled = true;
  setStatus("Signing in to Ely.by…");
  const result = await call("ely_login", username, password, totp);
  button.disabled = false;
  if (!result || !result.ok) {
    if (result && result.two_factor) {
      $("#ely-totp-field").classList.remove("hidden");
      $("#ely-totp").focus();
    }
    setStatus((result && result.error) || "Ely.by sign-in failed.", true);
    return;
  }
  $("#ely-password").value = "";
  $("#ely-totp").value = "";
  $("#ely-totp-field").classList.add("hidden");
  if (result.state) applyState(result.state);
  setStatus(`Signed in to Ely.by as ${result.name}.`);
}

async function elyBrowserLogin() {
  if (elyFlow.active) return;
  const result = await call("ely_browser_login");
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not start Ely.by browser sign-in.", true);
    if (result && result.setup) {
      const box = $("#ely-oauth-help");
      if (box) box.open = true;
      const field = $("#ely-oauth-client-id");
      if (field) field.focus();
    }
    return;
  }
  elyFlow.active = true;
  fillAccount();
  setStatus("Waiting for Ely.by sign-in in the browser…");
}

async function elyCancel() {
  await call("ely_cancel_login");
  elyFlow.active = false;
  fillAccount();
  setStatus("Ely.by browser sign-in cancelled.");
}

async function saveElyOauth() {
  const clientId = $("#ely-oauth-client-id").value.trim();
  const clientSecret = $("#ely-oauth-client-secret").value.trim();
  const redirect = $("#ely-oauth-redirect").value.trim();
  if (!clientId) {
    setStatus("Enter the Ely.by OAuth Client ID.", true);
    return;
  }
  const button = $("#btn-save-ely-oauth");
  button.disabled = true;
  const result = await call("set_ely_oauth", clientId, clientSecret, redirect);
  button.disabled = false;
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not save the OAuth settings.", true);
    return;
  }
  $("#ely-oauth-client-secret").value = "";
  if (result.state) applyState(result.state);
  const configured = !!(S.ely && S.ely.oauth && S.ely.oauth.configured);
  setStatus(configured
    ? "Browser sign-in is ready. Press “Sign in with browser”."
    : "Saved. Add the Ely.by Client ID before browser sign-in works.");
}

async function selectAccount(accountId) {
  const result = await call("account_select", accountId);
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not switch accounts.", true);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus("Active account switched.");
}

const accountDrag = { row: null, startY: 0, grab: 0, shift: 0, active: false };

function accountDragStart(event) {
  if (event.button !== 0) return;
  if (event.target.closest("button")) return;
  const row = event.target.closest(".account-item");
  if (!row || !row.dataset.accountId) return;
  accountDrag.row = row;
  accountDrag.startY = event.clientY;
  accountDrag.grab = event.clientY - row.getBoundingClientRect().top;
  accountDrag.shift = 0;
  accountDrag.active = false;
  document.addEventListener("pointermove", accountDragMove);
  document.addEventListener("pointerup", accountDragEnd);
  document.addEventListener("pointercancel", accountDragEnd);
}

function reorderAccountRow(list, row, before) {
  const tops = new Map();
  for (const el of list.querySelectorAll(".account-item")) {
    tops.set(el, el.getBoundingClientRect().top);
  }
  if (before) list.insertBefore(row, before);
  else list.appendChild(row);
  for (const [el, top] of tops) {
    if (el === row) continue;
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

function accountDragMove(event) {
  const row = accountDrag.row;
  if (!row || !row.isConnected) return;
  if (!accountDrag.active) {
    if (Math.abs(event.clientY - accountDrag.startY) < 4) return;
    accountDrag.active = true;
    row.classList.add("dragging");
    document.body.classList.add("account-dragging");
  }
  event.preventDefault();
  const list = $("#account-list");
  if (!list) return;

  // Keep the row's visual top under the pointer.
  const targetTop = event.clientY - accountDrag.grab;
  let rect = row.getBoundingClientRect();
  accountDrag.shift += targetTop - rect.top;
  row.style.transform = `translateY(${accountDrag.shift}px)`;

  const center = targetTop + rect.height / 2;
  const rows = $$(".account-item", list).filter((item) => item !== row);
  const before = rows.find((item) => {
    const box = item.getBoundingClientRect();
    return center < box.top + box.height / 2;
  }) || null;
  if (before ? row.nextElementSibling !== before : row.nextElementSibling) {
    reorderAccountRow(list, row, before);
    // The slot changed — offset the shift so the row does not jump.
    rect = row.getBoundingClientRect();
    accountDrag.shift += targetTop - rect.top;
    row.style.transform = `translateY(${accountDrag.shift}px)`;
  }

  const box = list.getBoundingClientRect();
  if (event.clientY < box.top + 28) list.scrollTop -= 12;
  else if (event.clientY > box.bottom - 28) list.scrollTop += 12;
}

function accountDragEnd() {
  document.removeEventListener("pointermove", accountDragMove);
  document.removeEventListener("pointerup", accountDragEnd);
  document.removeEventListener("pointercancel", accountDragEnd);
  const row = accountDrag.row;
  const active = accountDrag.active;
  accountDrag.row = null;
  accountDrag.active = false;
  accountDrag.shift = 0;
  document.body.classList.remove("account-dragging");
  if (!row) return;
  row.classList.remove("dragging");
  if (!active) return;
  const list = $("#account-list");
  if (!list) return;
  const ids = $$(".account-item", list).map((item) => item.dataset.accountId);
  // The Nexi site account is not shown in the game list; keep it at the
  // position it had so the backend receives the full account order.
  const all = S.accounts || [];
  for (const account of all) {
    if (account.type !== "nexi") continue;
    const pos = Math.min(all.indexOf(account), ids.length);
    ids.splice(pos, 0, account.id);
  }
  row.style.transition = "transform .18s var(--ease)";
  row.style.transform = "translateY(0)";
  setTimeout(() => {
    if (row.isConnected) {
      row.style.transition = "";
      row.style.transform = "";
    }
    const current = (S.accounts || []).map((account) => account.id);
    if (ids.join("|") !== current.join("|")) reorderAccounts(ids);
  }, 180);
}

async function reorderAccounts(ids) {
  const result = await call("account_reorder", ids);
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not reorder accounts.",
      true);
    if (result && result.state) applyState(result.state);
    return;
  }
  if (result.state) applyState(result.state);
}

async function changeTheme(theme) {
  applyTheme(theme);
  const result = await call("set_theme", theme);
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not save the theme.", true);
    if (result && result.state) applyState(result.state);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus(`Theme: ${THEME_NAMES[theme] || theme}.`);
}

async function changeMode(mode) {
  if (!MODES.includes(mode)) return;
  applyMode(mode);
  const result = await call("set_color_mode", mode);
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not save the colour mode.", true);
    if (result && result.state) applyState(result.state);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus(`Colour mode: ${mode === "light" ? "Light" : "Dark"}.`);
}

async function changeLanguage(language) {
  if (!LANGUAGES.includes(language)) return;
  applyLanguage(language);
  const result = await call("set_language", language);
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not save the language.", true);
    if (result && result.state) applyState(result.state);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus(`Language: ${language === "ru" ? "Русский" : "English"}.`);
}

async function changePet(kind) {
  if (!PET_OPTIONS.includes(kind)) return;
  applyPet(kind);
  const result = await call("set_pet", kind);
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not save the companion.", true);
    if (result && result.state) applyState(result.state);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus(`Companion: ${(PETS[kind] && PETS[kind].label) || kind}.`);
}

async function pickBackground() {
  if (S.busy) return;
  const result = await call("background_pick");
  if (!result || !result.ok) {
    if (result && result.cancelled) return;
    setStatus((result && result.error)
      || "Could not set the background.", true);
    return;
  }
  if (result.state) applyState(result.state);
  fillBackground();
  setStatus("Home background saved.");
}

async function clearBackground() {
  const result = await call("background_clear");
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not clear the background.", true);
    if (result && result.state) applyState(result.state);
    return;
  }
  if (result.state) applyState(result.state);
  fillBackground();
  setStatus("Home background cleared.");
}

async function removeAccount(accountId) {
  const account = (S.accounts || []).find((item) => item.id === accountId);
  const result = await call("account_remove", accountId);
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not remove the account.",
      true);
    return;
  }
  msFlow.active = false;
  elyFlow.active = false;
  if (account && account.type === "nexi") {
    nexiFlow.active = false;
    nexiFlow.login = "";
    nexiFlow.email = "";
  }
  if (nexiLink.token && nexiLink.selected === accountId) {
    closeNexiLinkPrompt();
  }
  if (result.state) applyState(result.state);
  setStatus(account ? `Removed ${account.name}.` : "Account removed.");
}

async function addOfflineAccount() {
  const input = $("#player-name");
  const name = input.value.trim();
  if (!name) {
    setStatus("Type an offline player name first.", true);
    input.focus();
    return;
  }
  const result = await call("account_add_offline", name);
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not add the account.",
      true);
    return;
  }
  input.value = "";
  if (result.state) applyState(result.state);
  setStatus(`Offline account “${result.name}” is active.`);
}

async function saveMsClientId(verbose = true) {
  const value = $("#ms-client-id").value.trim();
  const result = await call("set_ms_client_id", value);
  if (!result.ok) {
    setStatus(result.error || "Could not save the Client ID.", true);
    return false;
  }
  if (result.state) applyState(result.state);
  if (verbose) {
    setStatus(value ? "Client ID saved." : "Client ID cleared.");
  }
  return true;
}

function showMsCode(code, uri) {
  msFlow.active = true;
  accountMethod = "microsoft";
  $("#ms-code-value").textContent = code || "…";
  $("#ms-code-hint").textContent =
    `Enter this code at ${uri || "microsoft.com/link"} — the browser ` +
    "should open by itself; you can also open the page on any device.";
  fillAccount();
  if (code && navigator.clipboard) {
    navigator.clipboard.writeText(code).catch(() => {});
  }
}

async function msLogin() {
  const typed = $("#ms-client-id").value.trim();
  if (typed !== ((S.ms && S.ms.client_id) || "")) {
    if (!(await saveMsClientId(false))) return;
  }
  const result = await call("ms_login");
  if (!result.ok) {
    setStatus(result.error || "Could not start Microsoft sign-in.", true);
    return;
  }
  showMsCode(result.user_code, result.verification_uri);
  setStatus("Waiting for Microsoft sign-in…");
}

async function msCancel() {
  await call("ms_cancel_login");
  msFlow.active = false;
  fillAccount();
  setStatus("Microsoft sign-in cancelled.");
}

/* ---------------------------------------------- per-profile game defaults */

const GAME_DEFAULTS = {
  gui_scale: 0, fov: 70, render_distance: 12,
  brightness: 50, particles: 0, fps_limit: 260,
};

function normalizeGameDefaults(values) {
  const data = { ...GAME_DEFAULTS };
  if (values && typeof values === "object") {
    for (const key of Object.keys(GAME_DEFAULTS)) {
      const value = Number(values[key]);
      if (Number.isFinite(value)) data[key] = Math.round(value);
    }
  }
  return data;
}

function updateRangeFill(input) {
  if (!input) return;
  const min = Number(input.min) || 0;
  const max = Number(input.max);
  const value = Number(input.value);
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;
  input.style.setProperty("--fill", `${Math.max(0, Math.min(100, pct))}%`);
}

function renderDefaultsValues() {
  const fov = $("#default-fov");
  const distance = $("#default-distance");
  const brightness = $("#default-brightness");
  for (const input of [fov, distance, brightness]) updateRangeFill(input);
  if (fov) $("#default-fov-value").textContent = `${fov.value}°`;
  if (distance) $("#default-distance-value").textContent = distance.value;
  if (brightness) {
    $("#default-brightness-value").textContent = `${brightness.value}%`;
  }
}

function fillGameDefaults() {
  const hasProfile = !!S.instance;
  const values = normalizeGameDefaults(S.instance && S.instance.defaults);
  const fields = {
    "#default-gui-scale": values.gui_scale,
    "#default-particles": values.particles,
    "#default-fps": values.fps_limit,
    "#default-fov": values.fov,
    "#default-distance": values.render_distance,
    "#default-brightness": values.brightness,
  };
  for (const [selector, value] of Object.entries(fields)) {
    const input = $(selector);
    if (!input) continue;
    // Never fight the pointer while a slider is being dragged.
    if (document.activeElement !== input) input.value = String(value);
    input.disabled = !hasProfile;
  }
  const label = $("#defaults-profile");
  if (label) {
    label.textContent = hasProfile ? S.instance.name : "No profile selected";
  }
  const apply = $("#btn-apply-defaults");
  if (apply) apply.disabled = !hasProfile;
  renderDefaultsValues();
}

function readGameDefaults() {
  const value = (selector, fallback) => {
    const input = $(selector);
    return input ? input.value : fallback;
  };
  return normalizeGameDefaults({
    gui_scale: value("#default-gui-scale", 0),
    particles: value("#default-particles", 0),
    fps_limit: value("#default-fps", 260),
    fov: value("#default-fov", 70),
    render_distance: value("#default-distance", 12),
    brightness: value("#default-brightness", 50),
  });
}

let defaultsSaveTimer = 0;

function queueGameDefaultsSave() {
  if (!S.instance) return;
  clearTimeout(defaultsSaveTimer);
  defaultsSaveTimer = setTimeout(saveGameDefaults, 250);
}

async function saveGameDefaults() {
  clearTimeout(defaultsSaveTimer);
  if (!S.instance) return;
  const slug = S.instance.slug;
  const result = await call("set_game_defaults", readGameDefaults());
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not save game defaults.",
              true);
    return;
  }
  // Adopt the saved state only while the same profile is still selected.
  if (result.state && S.instance && S.instance.slug === slug) {
    applyState(result.state);
  }
}

async function applyGameDefaults() {
  if (!S.instance) return;
  const result = await call("apply_game_defaults", readGameDefaults());
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not write options.txt.", true);
    return;
  }
  if (result.state) applyState(result.state);
  setStatus(result.message || "Game defaults written to options.txt.");
}

async function applyJavaPath() {
  const value = $("#java-path").value.trim();
  const result = await call("set_java", value);
  if (result.state) applyState(result.state);
  if (result.ok) {
    setStatus(result.state && result.state.java
      ? `Java set: ${result.state.java}`
      : "Java set to automatic.");
  } else {
    setStatus(result.error || "That Java path is not valid.", true);
  }
}

async function pickJava() {
  const result = await call("pick_java");
  if (result.cancelled) return;
  if (result.state) applyState(result.state);
  if (result.ok) setStatus(`Java set: ${result.state.java}`);
  else setStatus(result.error || "Could not set Java.", true);
}

async function useAutoJava() {
  const result = await call("set_java", "");
  if (result.state) applyState(result.state);
  setStatus("Java set to automatic.");
}

let playBusy = false;

function runningSlugs() {
  if (Array.isArray(S.running)) return S.running;
  return S.game_running && S.game_instance ? [S.game_instance] : [];
}

function startingSlugs() {
  return Array.isArray(S.launching_slugs) ? S.launching_slugs : [];
}

function isInstanceRunning(slug) {
  return !!slug && runningSlugs().includes(slug);
}

function isInstanceStarting(slug) {
  return !!slug && startingSlugs().includes(slug);
}

function withoutSlug(list, slug) {
  return (list || []).filter((item) => item !== slug);
}

function markStarting(slug) {
  if (!slug) return;
  S.launching_slugs = withoutSlug(startingSlugs(), slug).concat(slug);
  S.launching = true;
}

function clearStarting(slug) {
  S.launching_slugs = withoutSlug(startingSlugs(), slug);
  S.launching = S.launching_slugs.length > 0;
}

function markRunning(slug) {
  if (!slug) return;
  S.running = withoutSlug(runningSlugs(), slug).concat(slug);
  S.game_running = true;
  if (S.selected === slug) S.game_instance = slug;
}

function clearRunning(slug) {
  S.running = withoutSlug(runningSlugs(), slug);
  S.game_running = S.running.length > 0;
  if (S.game_instance === slug) S.game_instance = S.running[0] || "";
}

function syncPlay() {
  const slug = S.instance ? S.instance.slug : "";
  const starting = isInstanceStarting(slug);
  const showRunning = isInstanceRunning(slug);
  const play = $("#btn-play");
  const row = $("#play-running");
  play.classList.toggle("hidden", showRunning);
  row.classList.toggle("hidden", !showRunning);
  play.classList.toggle("starting", starting);
  play.disabled = starting || playBusy || showRunning;
  play.title = showRunning ? "This profile is already running." : "";
  $("#play-label").textContent = starting ? "Starting…" : "Play";
  $("#btn-stop").disabled = playBusy || !showRunning;
  $("#btn-restart").disabled = playBusy || !showRunning;
  if (typeof syncHome === "function") syncHome();
}

async function play() {
  const slug = S.instance ? S.instance.slug : "";
  if (!slug || playBusy || isInstanceRunning(slug)
      || isInstanceStarting(slug)) return;
  markStarting(slug);
  syncPlay();
  setStatus(`Starting "${S.instance.name}"…`);
  const result = await call("play");
  if (!result.ok) {
    clearStarting(slug);
    syncPlay();
    setStatus(result.error || "Could not start the game.", true);
  } else {
    // Pick up the launch time so Home can list this build first.
    refreshState();
  }
}

async function stopGame() {
  if (playBusy || !S.instance) return;
  const slug = S.instance.slug;
  playBusy = true;
  syncPlay();
  setStatus("Stopping the game…");
  const result = await call("game_stop");
  playBusy = false;
  if (!result.ok) {
    syncPlay();
    setStatus(result.error || "Could not stop the game.", true);
    return;
  }
  clearRunning(slug);
  clearStarting(slug);
  syncPlay();
  setStatus(result.message || "Game stopped.");
}

async function restartGame() {
  if (playBusy || !S.instance) return;
  const slug = S.instance.slug;
  playBusy = true;
  clearRunning(slug);
  markStarting(slug);
  syncPlay();
  setStatus("Restarting the game…");
  const result = await call("game_restart");
  playBusy = false;
  if (!result.ok) {
    clearStarting(slug);
    syncPlay();
    setStatus(result.error || "Could not restart the game.", true);
  }
}

/* delete: two clicks, the second one really removes the profile. The menu stays
   open between them, so the target slug is kept here rather than read from the
   selection (the menu can point at a profile that is not selected yet). */
let confirmTimer = null;
let deleteSlug = "";

function resetDeleteConfirm() {
  clearTimeout(confirmTimer);
  confirmTimer = null;
  deleteSlug = "";
  const button = $('#profile-menu [data-profile-action="delete"]');
  if (!button) return;
  button.classList.remove("confirm");
  button.querySelector(".ctx-label").textContent = "Delete";
}

function onDelete(slug) {
  const target = slug || (S.instance ? S.instance.slug : "");
  if (!target) return;
  const button = $('#profile-menu [data-profile-action="delete"]');
  if (!button) return;
  if (deleteSlug !== target || !button.classList.contains("confirm")) {
    resetDeleteConfirm();
    deleteSlug = target;
    button.classList.add("confirm");
    button.querySelector(".ctx-label").textContent = "Confirm delete";
    const item = S.instances.find((inst) => inst.slug === target);
    const name = item ? item.name : target;
    setStatus(`Press Delete again to permanently remove "${name}" — its worlds, mods and configs are deleted, shared versions stay.`);
    confirmTimer = setTimeout(resetDeleteConfirm, 5000);
    return;
  }
  resetDeleteConfirm();
  hideProfileMenu();
  call("delete", target).then(async (result) => {
    resetDeleteConfirm();
    if (result.state) applyState(result.state);
    else await refreshState();
    if (result.message) setStatus(result.message);
  });
}
