"use strict";

/* --------------------------------------------------------------- friends */

const friendsState = {
  loaded: false,
  loading: false,
  waiting: false,
  counts: { friends: 0, online: 0, incoming: 0 },
};

function nexiAccountEntry() {
  return (S.accounts || []).find((account) => account.type === "nexi") || null;
}

function friendsStatus(text, error = false) {
  const node = $("#friends-signin-status");
  if (!node) return;
  node.textContent = text || "";
  node.classList.toggle("hidden", !text);
  node.classList.toggle("error", !!error);
}

function renderFriendsGate() {
  const gate = $("#friends-gate");
  if (!gate) return;
  const nexi = nexiAccountEntry();
  const signedIn = !!nexi;
  gate.classList.toggle("hidden", signedIn);
  $("#friends-body").classList.toggle("hidden", !signedIn);
  $("#btn-friends-profile").classList.toggle("hidden", !signedIn);
  $("#btn-friends-refresh").classList.toggle("hidden", !signedIn);
  const signIn = $("#btn-friends-signin");
  const cancel = $("#btn-friends-signin-cancel");
  if (signIn) signIn.disabled = friendsState.waiting;
  if (cancel) cancel.classList.toggle("hidden", !friendsState.waiting);
  if (signedIn) {
    const online = friendsState.counts.online || 0;
    $("#friends-status").textContent = `${online} online · ${nexi.name}`;
  } else {
    $("#friends-status").textContent = "not signed in";
  }
}

function friendRow(person, kind) {
  const row = document.createElement("div");
  row.className = "friend-row";
  const mc = person.mc || {};
  const avatar = siteSkinNode(mc.type || "offline",
    mc.name || person.display_name, mc.uuid || "");
  avatar.classList.add("friend-avatar");
  row.appendChild(avatar);

  const text = document.createElement("div");
  text.className = "friend-text";
  const name = document.createElement("span");
  name.className = "friend-name";
  name.textContent = person.display_name || person.account_name
    || person.nexi_id || "Nexi user";
  if (person.online) {
    const dot = document.createElement("span");
    dot.className = "friend-online";
    dot.textContent = "Online";
    name.appendChild(dot);
  }
  text.appendChild(name);

  const details = [person.handle || "", mc.name
    ? `Minecraft: ${mc.name}` : "Minecraft not linked"];
  const hint = document.createElement("span");
  hint.className = "hint";
  hint.textContent = details.filter(Boolean).join(" · ");
  text.appendChild(hint);
  row.appendChild(text);

  if (kind === "incoming") {
    row.classList.add("has-actions");
    const actions = document.createElement("div");
    actions.className = "pane-actions";
    const accept = document.createElement("button");
    accept.className = "btn primary";
    accept.type = "button";
    accept.dataset.friendAccept = person.id;
    accept.textContent = "Accept";
    const decline = document.createElement("button");
    decline.className = "btn ghost";
    decline.type = "button";
    decline.dataset.friendDecline = person.id;
    decline.textContent = "Decline";
    actions.append(accept, decline);
    row.appendChild(actions);
  } else if (kind === "outgoing") {
    const tag = document.createElement("span");
    tag.className = "friend-tag";
    tag.textContent = "Request sent";
    row.appendChild(tag);
  }
  return row;
}

function renderFriends(data) {
  friendsState.loaded = true;
  friendsState.counts = data.counts || friendsState.counts;
  renderFriendsGate();
  if (!data.signed_in) {
    friendsState.loaded = false;
    return;
  }

  const incoming = data.incoming || [];
  const outgoing = data.outgoing || [];
  const friends = data.friends || [];
  const requests = $("#friends-requests");
  const list = $("#friends-list");
  requests.replaceChildren();
  list.replaceChildren();
  for (const person of incoming) requests.appendChild(friendRow(person, "incoming"));
  for (const person of outgoing) requests.appendChild(friendRow(person, "outgoing"));
  for (const person of friends) list.appendChild(friendRow(person, "friend"));

  const requestCount = incoming.length + outgoing.length;
  $("#friends-requests-card").classList.toggle("hidden", !requestCount);
  $("#friends-requests-count").textContent = String(requestCount);
  $("#friends-count").textContent = String(friends.length);
  $("#friends-empty").classList.toggle("hidden", !!friends.length);
  const error = $("#friends-error");
  error.textContent = data.error || "";
  error.classList.toggle("hidden", !data.error);
  if (data.error) friendStatusError(data.error);
}

function friendStatusError(message) {
  setStatus(message, true);
}

async function loadFriends() {
  if (friendsState.loading) return;
  if (!nexiAccountEntry()) {
    friendsState.loaded = false;
    renderFriendsGate();
    return;
  }
  friendsState.loading = true;
  const result = await call("nexi_friends");
  friendsState.loading = false;
  if (!result) {
    setStatus("Could not load friends.", true);
    return;
  }
  renderFriends(result);
}

async function friendsSignIn() {
  if (friendsState.waiting) return;
  friendsState.waiting = true;
  friendsStatus("Waiting for you to sign in in the browser…");
  renderFriendsGate();
  setStatus("Waiting for Nexi sign-in in the browser…");
  const result = await call("nexi_browser_login");
  if (!result || !result.ok) {
    friendsState.waiting = false;
    renderFriendsGate();
    friendsStatus((result && result.error)
      || "Could not start browser sign-in.", true);
    setStatus((result && result.error)
      || "Could not start browser sign-in.", true);
  }
}

async function friendsCancelSignIn() {
  await call("nexi_browser_login_cancel");
  friendsState.waiting = false;
  friendsStatus("");
  renderFriendsGate();
  setStatus("Nexi sign-in cancelled.");
}

async function friendsRequestAction(action, id) {
  const result = await call(
    action === "accept" ? "nexi_friend_accept" : "nexi_friend_decline", id);
  if (!result || !result.ok) {
    setStatus((result && result.error)
      || "Could not update the friend request.", true);
    return;
  }
  renderFriends(result);
  setStatus(action === "accept"
    ? "Friend request accepted." : "Friend request declined.");
}

function bindFriends() {
  const signIn = $("#btn-friends-signin");
  if (!signIn) return;
  signIn.addEventListener("click", friendsSignIn);
  signIn.addEventListener("pointermove", (event) => {
    const rect = signIn.getBoundingClientRect();
    signIn.style.setProperty("--mx", `${event.clientX - rect.left}px`);
    signIn.style.setProperty("--my", `${event.clientY - rect.top}px`);
  });
  signIn.addEventListener("pointerleave", () => {
    signIn.style.removeProperty("--mx");
    signIn.style.removeProperty("--my");
  });
  $("#btn-friends-signin-cancel").addEventListener(
    "click", friendsCancelSignIn);
  $("#btn-friends-refresh").addEventListener("click", loadFriends);
  $("#btn-friends-profile").addEventListener("click", openSiteProfile);
  $("#friends-requests").addEventListener("click", (event) => {
    const accept = event.target.closest("[data-friend-accept]");
    const decline = event.target.closest("[data-friend-decline]");
    if (accept) friendsRequestAction("accept", accept.dataset.friendAccept);
    else if (decline) {
      friendsRequestAction("decline", decline.dataset.friendDecline);
    }
  });
}
