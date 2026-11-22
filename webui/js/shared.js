"use strict";

/* -------------------------------------------------------- shared builds */

const sharedState = {
  cardSeq: 0,
  availableSeq: 0,
  autoBusy: false,
  timer: 0,
  confirmStop: false,
  stopTimer: 0,
  formSlug: "",
};

const SHARED_HINT = $("#shared-hint")
  ? $("#shared-hint").textContent.trim() : "";

function sharedLoaderText(loader) {
  return {
    any: "vanilla", fabric: "Fabric", forge: "Forge",
    neoforge: "NeoForge", quilt: "Quilt",
  }[loader] || loader || "vanilla";
}

function sharedCount(value) {
  return Array.isArray(value) ? value.length : 0;
}

function sharedBuildMeta(definition, build) {
  const def = definition && typeof definition === "object" ? definition : {};
  const loader = sharedLoaderText(def.loader);
  const loaderPart = def.loader_version
    ? `${loader} ${def.loader_version}` : loader;
  const packs = def.packs && typeof def.packs === "object"
    ? Object.values(def.packs).reduce(
      (total, list) => total + sharedCount(list), 0) : 0;
  const parts = [`Minecraft ${def.mc_version || "?"}`, loaderPart,
    `${sharedCount(def.mods)} mods`];
  if (packs) parts.push(`${packs} packs`);
  if (build && build.revision) parts.push(`rev ${build.revision}`);
  return parts.join(" · ");
}

function renderSharedCard(info) {
  const block = $("#shared-settings");
  if (!block) return;
  info = info && typeof info === "object" ? info : {};
  sharedState.lastInfo = info;
  const linked = !!info.linked;
  const owner = !!info.owner;
  const hint = $("#shared-hint");
  const publish = $("#shared-publish");
  const card = $("#shared-linked");
  const error = $("#shared-error");
  publish.classList.toggle("hidden", linked || !info.signed_in);
  card.classList.toggle("hidden", !linked);
  card.classList.toggle("owner", owner);
  if (hint) {
    hint.textContent = !info.signed_in
      ? "Sign in to Nexi from the Friends panel on the main menu to share this build."
      : (linked
        ? (owner
          ? "Friends you add receive the same version, loader and exact mods. Worlds and screenshots stay personal."
          : "This build follows your friend — new mods and versions arrive automatically. Your worlds and screenshots are kept.")
        : SHARED_HINT);
  }
  const missing = !!info.missing;
  if (linked) {
    const build = info.build && typeof info.build === "object"
      ? info.build : {};
    const def = build.definition && typeof build.definition === "object"
      ? build.definition : {};
    const link = info.link && typeof info.link === "object" ? info.link : {};
    const name = build.name || link.name || S.instance && S.instance.name
      || "Shared build";
    $("#shared-name").textContent = name;
    $("#shared-meta").textContent = missing
      ? "The owner deleted this shared build."
      : (build.definition
        ? sharedBuildMeta(def, build)
        : `Shared by ${link.owner_name || "a friend"}`);
    const badge = $("#shared-badge");
    badge.textContent = missing ? "Deleted" : (owner ? "Owner"
      : `By ${(build.owner && (build.owner.nick
        || build.owner.account_name)) || link.owner_name || "friend"}`);
    badge.classList.toggle("owner", owner);
    $("#btn-shared-save").classList.toggle("hidden", !owner || missing);
    $("#btn-shared-sync").classList.toggle("hidden", missing);
    const stop = $("#btn-shared-unpublish");
    stop.textContent = sharedState.confirmStop
      ? "Click again to confirm"
      : (owner ? "Stop sharing" : "Stop following");
    stop.classList.toggle("danger", !!sharedState.confirmStop);
    renderSharedMembers(info, owner && !missing);
  } else {
    sharedState.confirmStop = false;
    if (S.instance && sharedState.formSlug !== S.instance.slug) {
      sharedState.formSlug = S.instance.slug;
      $("#shared-name-input").value = S.instance.name || "";
      $("#shared-desc-input").value = "";
    }
  }
  const message = info.error
    || (missing ? "The owner deleted this build. You can keep the files or stop following it." : "");
  error.textContent = message;
  error.classList.toggle("hidden", !message);
  error.classList.toggle("error", !!info.error);
}

function renderSharedMembers(info, visible) {
  const box = $("#shared-members");
  if (!box) return;
  box.classList.toggle("hidden", !visible);
  box.replaceChildren();
  if (!visible) return;
  const friends = Array.isArray(info.friends) ? info.friends : [];
  if (!friends.length) {
    box.appendChild(elem("p", "hint",
      "Add friends on the Nexi site — then you can include them here."));
    return;
  }
  box.appendChild(elem("span", "field-label", "FRIENDS IN THIS BUILD"));
  for (const friend of friends) {
    const row = elem("div", "shared-member-row");
    const text = elem("div", "shared-member-text");
    const name = elem("span", "shared-member-name", friend.name || "Friend");
    if (friend.online) {
      const dot = elem("span", "friend-online", "Online");
      name.appendChild(dot);
    }
    text.appendChild(name);
    if (friend.handle) text.appendChild(elem("span", "hint", friend.handle));
    row.appendChild(text);
    if (friend.added) {
      row.appendChild(elem("span", "friend-tag", "In build"));
      const remove = elem("button", "btn ghost sm", "Remove");
      remove.type = "button";
      remove.dataset.sharedMember = friend.id;
      remove.dataset.sharedAction = "remove";
      row.appendChild(remove);
    } else {
      const add = elem("button", "btn ghost sm", "Add");
      add.type = "button";
      add.dataset.sharedMember = friend.id;
      add.dataset.sharedAction = "add";
      row.appendChild(add);
    }
    box.appendChild(row);
  }
}

async function loadSharedCard() {
  if (!S.instance) return;
  const slug = S.instance.slug;
  const seq = ++sharedState.cardSeq;
  const result = await call("shared_info");
  if (seq !== sharedState.cardSeq) return;
  if (screen !== "profiles" || !S.instance || S.instance.slug !== slug) return;
  renderSharedCard(result);
}

function renderSharedAvailable(data) {
  const section = $("#shared-home");
  if (!section) return;
  data = data && typeof data === "object" ? data : {};
  const builds = Array.isArray(data.builds) ? data.builds : [];
  section.classList.toggle("hidden", !data.signed_in || !builds.length);
  $("#shared-home-count").textContent = String(builds.length);
  const list = $("#shared-home-list");
  list.replaceChildren();
  for (const build of builds) {
    const row = elem("div", "friend-row shared-build-row");
    const avatar = elem("div", "shared-avatar",
      (build.owner_name || "?").slice(0, 1).toUpperCase());
    row.appendChild(avatar);
    const text = elem("div", "friend-text");
    const name = elem("span", "friend-name", build.name || "Shared build");
    if (build.is_owner) name.appendChild(elem("span", "friend-tag", "Owner"));
    text.appendChild(name);
    const parts = [`${build.owner_name}`, `MC ${build.mc_version || "?"}`,
      sharedLoaderText(build.loader), `${build.mods} mods`];
    if (build.packs) parts.push(`${build.packs} packs`);
    text.appendChild(elem("span", "hint", parts.join(" · ")));
    if (build.description) {
      text.appendChild(elem("span", "hint shared-build-desc",
        build.description));
    }
    row.appendChild(text);
    if (build.local_slug) {
      const open = elem("button", "btn ghost sm", "Open");
      open.type = "button";
      open.dataset.sharedOpen = build.local_slug;
      row.appendChild(open);
    } else {
      const join = elem("button", "btn primary sm", "Add");
      join.type = "button";
      join.dataset.sharedJoin = build.id;
      row.appendChild(join);
    }
    list.appendChild(row);
  }
}

async function loadSharedAvailable() {
  if (typeof nexiAccountEntry === "function" && !nexiAccountEntry()) {
    renderSharedAvailable({ signed_in: false, builds: [] });
    return;
  }
  const seq = ++sharedState.availableSeq;
  const result = await call("shared_available");
  if (seq !== sharedState.availableSeq) return;
  if (!result || result.ok === false) {
    renderSharedAvailable({ signed_in: true, builds: [] });
    return;
  }
  renderSharedAvailable(result);
}

async function sharedPublish() {
  const button = $("#btn-shared-publish");
  const name = $("#shared-name-input").value.trim();
  const description = $("#shared-desc-input").value.trim();
  if (button) button.disabled = true;
  try {
    const result = await call("shared_publish", name, description);
    if (result && result.state) applyState(result.state);
    if (result && result.message) setStatus(result.message);
    if (result && result.ok) {
      await loadSharedCard();
      loadSharedAvailable();
    }
  } finally {
    if (button) button.disabled = false;
  }
}

async function sharedSave() {
  const button = $("#btn-shared-save");
  if (button) button.disabled = true;
  try {
    const info = sharedState.lastInfo || {};
    const build = info.build || {};
    const result = await call("shared_publish", build.name || "",
                              build.description || "");
    if (result && result.state) applyState(result.state);
    if (result && result.message) setStatus(result.message);
    if (result && result.ok) await loadSharedCard();
  } finally {
    if (button) button.disabled = false;
  }
}

async function sharedSyncNow() {
  const button = $("#btn-shared-sync");
  if (button) button.disabled = true;
  try {
    const result = await call("shared_sync");
    if (result && result.state) applyState(result.state);
    if (result && (result.message || result.error)) {
      setStatus(result.message || result.error, false);
    }
    if (result && result.ok) sharedRefreshProfile();
    await loadSharedCard();
    loadSharedAvailable();
  } finally {
    if (button) button.disabled = false;
  }
}

/* Sync writes files straight into the profile folder, so the cached
   contents pane and the mods browser have to re-read them at once. */
function sharedRefreshProfile() {
  if (typeof detail !== "undefined" && detail.contents
      && typeof loadProfileContents === "function") {
    loadProfileContents(true);
  }
  if (typeof instanceKey !== "function") return;
  const profile = instanceKey();
  if (typeof browserStates !== "undefined") browserStates.delete(profile);
  if (typeof mods !== "undefined" && mods.profile === profile) {
    mods.installed = null;
    if (mods.selected >= 0) refreshModStatus();
    else syncMods();
  }
}

function sharedResetStop() {
  sharedState.confirmStop = false;
  if (sharedState.stopTimer) clearTimeout(sharedState.stopTimer);
  sharedState.stopTimer = 0;
  const stop = $("#btn-shared-unpublish");
  if (stop) {
    stop.textContent = sharedState.lastInfo && sharedState.lastInfo.owner
      ? "Stop sharing" : "Stop following";
    stop.classList.remove("danger");
  }
}

async function sharedUnpublish() {
  if (!sharedState.confirmStop) {
    sharedState.confirmStop = true;
    const stop = $("#btn-shared-unpublish");
    stop.textContent = "Click again to confirm";
    stop.classList.add("danger");
    sharedState.stopTimer = setTimeout(sharedResetStop, 4000);
    return;
  }
  sharedResetStop();
  const result = await call("shared_unpublish");
  if (result && result.state) applyState(result.state);
  if (result && result.message) setStatus(result.message);
  if (result && result.ok) {
    sharedState.cardSeq += 1;
    await loadSharedCard();
    loadSharedAvailable();
  }
}

async function sharedMemberAction(button) {
  const id = button.dataset.sharedMember;
  const action = button.dataset.sharedAction;
  button.disabled = true;
  try {
    const result = await call(action === "add"
      ? "shared_add_member" : "shared_remove_member", id);
    if (result && result.info) renderSharedCard(result.info);
    else if (result && result.ok) await loadSharedCard();
    if (result && result.message) setStatus(result.message);
  } finally {
    button.disabled = false;
  }
}

async function sharedJoin(button) {
  const id = button.dataset.sharedJoin;
  button.disabled = true;
  try {
    const result = await call("shared_join", id);
    if (result && result.state) applyState(result.state);
    if (result && result.message) setStatus(result.message);
    if (result && result.ok) sharedRefreshProfile();
    loadSharedAvailable();
    if (result && result.ok) setScreen("profiles");
    else button.disabled = false;
  } catch (err) {
    button.disabled = false;
  }
}

function sharedCardVisible() {
  return screen === "profiles" && typeof detail !== "undefined"
    && detail.pane === "settings" && !!S.instance;
}

function syncSharedAccount() {
  const signed = typeof nexiAccountEntry === "function"
    && !!nexiAccountEntry();
  if (signed) return;
  sharedState.cardSeq += 1;
  sharedState.availableSeq += 1;
  sharedState.autoBusy = false;
  renderSharedCard({ signed_in: false, linked: false });
  renderSharedAvailable({ signed_in: false, builds: [] });
}

async function sharedAutoTick() {
  if (document.hidden || sharedState.autoBusy) return;
  if (typeof nexiAccountEntry === "function" && !nexiAccountEntry()) return;
  const linked = (S.instances || []).some(
    (inst) => inst.shared && inst.shared.build_id);
  if (!linked) return;
  sharedState.autoBusy = true;
  try {
    const result = await call("shared_auto_sync");
    if (result && result.changed) {
      sharedRefreshProfile();
      if (screen === "home") loadSharedAvailable();
      if (sharedCardVisible()) loadSharedCard();
    }
  } finally {
    sharedState.autoBusy = false;
  }
}

function bindShared() {
  const block = $("#shared-settings");
  if (!block) return;
  $("#btn-shared-publish").addEventListener("click", sharedPublish);
  $("#btn-shared-save").addEventListener("click", sharedSave);
  $("#btn-shared-sync").addEventListener("click", sharedSyncNow);
  $("#btn-shared-unpublish").addEventListener("click", sharedUnpublish);
  $("#shared-name-input").addEventListener("input", sharedResetStop);
  $("#shared-desc-input").addEventListener("input", sharedResetStop);
  $("#shared-members").addEventListener("click", (event) => {
    const button = event.target.closest("[data-shared-member]");
    if (button) sharedMemberAction(button);
  });
  $("#shared-home-list").addEventListener("click", (event) => {
    const open = event.target.closest("[data-shared-open]");
    if (open) {
      selectInstance(open.dataset.sharedOpen);
      setScreen("profiles");
      return;
    }
    const join = event.target.closest("[data-shared-join]");
    if (join) sharedJoin(join);
  });
  if (sharedState.timer) clearInterval(sharedState.timer);
  sharedState.timer = setInterval(sharedAutoTick, 60000);
  setTimeout(sharedAutoTick, 12000);
}
