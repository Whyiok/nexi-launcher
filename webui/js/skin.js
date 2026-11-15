"use strict";

/* ------------------------------------------------------------------ skin */

const skin = {
  data: "", variant: "classic", type: "", account: "", busy: false, seq: 0,
};

function setSkinVariantButtons(variant) {
  $$("#skin-seg button").forEach((button) => {
    button.classList.toggle("on", button.dataset.skinVariant === variant);
  });
  updateSegFill($("#skin-seg"));
}

function setSkinVariantEnabled(enabled) {
  $$("#skin-seg button").forEach((button) => {
    button.disabled = !enabled;
  });
}

const skinView = {
  tex: null,
  src: "",
  token: 0,
  variant: "classic",
  ready: false,
  yaw: 0,
  pitch: 0,
  targetYaw: 0,
  targetPitch: 0,
  bodyYaw: 0.16,
  bodyPitch: 0,
  targetBodyYaw: 0.16,
  targetBodyPitch: 0,
  dragging: false,
  lastX: 0,
  lastY: 0,
  raf: 0,
};

function skinRotateY(x, z, angle) {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  return [x * c + z * s, -x * s + z * c];
}

function skinRotateX(y, z, angle) {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  return [y * c - z * s, y * s + z * c];
}

function skinPlaceVertex(point, group) {
  let [x, y, z] = point;
  if (group === "head") {
    const pitch = skinRotateX(y - 24, z, skinView.pitch);
    const yaw = skinRotateY(x, pitch[1], skinView.yaw);
    x = yaw[0];
    z = yaw[1];
    y = pitch[0] + 24;
  }
  const tilt = skinRotateX(y - 16, z, skinView.bodyPitch);
  y = tilt[0] + 16;
  z = tilt[1];
  const body = skinRotateY(x, z, skinView.bodyYaw);
  return { x: body[0], y, z: body[1] };
}

function skinRotateNormal(normal, group) {
  let [x, y, z] = normal;
  if (group === "head") {
    const pitch = skinRotateX(y, z, skinView.pitch);
    const yaw = skinRotateY(x, pitch[1], skinView.yaw);
    x = yaw[0];
    z = yaw[1];
    y = pitch[0];
  }
  const tilt = skinRotateX(y, z, skinView.bodyPitch);
  y = tilt[0];
  z = tilt[1];
  const body = skinRotateY(x, z, skinView.bodyYaw);
  return [body[0], y, body[1]];
}

/* Boxes in skin pixels: head 8³, torso 8×12×4, limbs 4 (or slim 3) wide. */
function skinBoxes(variant) {
  const armW = variant === "slim" ? 3 : 4;
  const boxes = [];
  const add = (group, x0, x1, y0, y1, z0, z1,
               u, v, w, h, d, inflate = 0) => {
    boxes.push({
      group,
      x0: x0 - inflate, x1: x1 + inflate,
      y0: y0 - inflate, y1: y1 + inflate,
      z0: z0 - inflate, z1: z1 + inflate,
      u, v, w, h, d,
    });
  };
  add("head", -4, 4, 24, 32, -4, 4, 0, 0, 8, 8, 8);
  add("head", -4, 4, 24, 32, -4, 4, 32, 0, 8, 8, 8, 0.5);
  add("body", -4, 4, 12, 24, -2, 2, 16, 16, 8, 12, 4);
  add("body", -4, 4, 12, 24, -2, 2, 16, 32, 8, 12, 4, 0.5);
  add("body", -4 - armW, -4, 12, 24, -2, 2, 40, 16, armW, 12, 4);
  add("body", -4 - armW, -4, 12, 24, -2, 2, 40, 32, armW, 12, 4, 0.5);
  add("body", 4, 4 + armW, 12, 24, -2, 2, 32, 48, armW, 12, 4);
  add("body", 4, 4 + armW, 12, 24, -2, 2, 48, 48, armW, 12, 4, 0.5);
  add("body", -4, 0, 0, 12, -2, 2, 0, 16, 4, 12, 4);
  add("body", -4, 0, 0, 12, -2, 2, 0, 32, 4, 12, 4, 0.5);
  add("body", 0, 4, 0, 12, -2, 2, 16, 48, 4, 12, 4);
  add("body", 0, 4, 0, 12, -2, 2, 0, 48, 4, 12, 4, 0.5);
  return boxes;
}

/* Six faces of a box; corners follow the skin's unwrapped texture net. */
function skinBoxFaces(box) {
  const { x0, x1, y0, y1, z0, z1, u, v, w, h, d } = box;
  const faces = [];
  const add = (src, pts, normal) => faces.push({
    src, pts, normal, group: box.group,
  });
  add([u + d, v + d, w, h], [
    [x0, y1, z1], [x1, y1, z1], [x1, y0, z1], [x0, y0, z1]], [0, 0, 1]);
  add([u + 2 * d + w, v + d, w, h], [
    [x1, y1, z0], [x0, y1, z0], [x0, y0, z0], [x1, y0, z0]], [0, 0, -1]);
  add([u, v + d, d, h], [
    [x0, y1, z0], [x0, y1, z1], [x0, y0, z1], [x0, y0, z0]], [-1, 0, 0]);
  add([u + d + w, v + d, d, h], [
    [x1, y1, z1], [x1, y1, z0], [x1, y0, z0], [x1, y0, z1]], [1, 0, 0]);
  add([u + d, v, w, d], [
    [x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]], [0, 1, 0]);
  add([u + d + w, v, w, d], [
    [x1, y0, z0], [x0, y0, z0], [x0, y0, z1], [x1, y0, z1]], [0, -1, 0]);
  return faces;
}

/* Legacy 64×32 skins get the left limbs mirrored into the modern slots. */
function prepareSkinTexture(img) {
  const tex = document.createElement("canvas");
  tex.width = 64;
  tex.height = 64;
  const ctx = tex.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  const legacy = img.naturalHeight <= 32;
  ctx.drawImage(img, 0, 0, 64, legacy ? 32 : 64);
  if (!legacy) return tex;
  const mirror = (sx, sy, w, h, dx, dy) => {
    ctx.save();
    ctx.translate(dx + w, dy);
    ctx.scale(-1, 1);
    ctx.drawImage(img, sx, sy, w, h, 0, 0, w, h);
    ctx.restore();
  };
  /* Left leg from the right leg. */
  mirror(4, 16, 4, 4, 20, 48);
  mirror(8, 16, 4, 4, 24, 48);
  mirror(8, 20, 4, 12, 16, 52);
  mirror(4, 20, 4, 12, 20, 52);
  mirror(0, 20, 4, 12, 24, 52);
  mirror(12, 20, 4, 12, 28, 52);
  /* Left arm from the right arm. */
  mirror(44, 16, 4, 4, 36, 48);
  mirror(48, 16, 4, 4, 40, 48);
  mirror(48, 20, 4, 12, 32, 52);
  mirror(44, 20, 4, 12, 36, 52);
  mirror(40, 20, 4, 12, 40, 52);
  mirror(52, 20, 4, 12, 44, 52);
  return tex;
}

function renderSkinView() {
  const canvas = $("#skin-canvas");
  if (!canvas || !skinView.ready || !skinView.tex) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width * dpr));
  const height = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.imageSmoothingEnabled = false;

  const scale = Math.min(width / 19, height / 35);
  const cx = width / 2;
  const cy = height / 2;
  const project = (p) => [cx + p.x * scale, cy - (p.y - 16) * scale];

  ctx.fillStyle = "rgba(0, 0, 0, .3)";
  ctx.beginPath();
  ctx.ellipse(cx, cy + 16 * scale, 6.4 * scale, 1.3 * scale, 0, 0, Math.PI * 2);
  ctx.fill();

  const queue = [];
  for (const box of skinBoxes(skinView.variant)) {
    for (const face of skinBoxFaces(box)) {
      const normal = skinRotateNormal(face.normal, face.group);
      if (normal[2] <= 0.02) continue;
      const placed = face.pts.map((pt) => skinPlaceVertex(pt, face.group));
      let depth = 0;
      for (const p of placed) depth += p.z;
      queue.push({
        src: face.src,
        pts: placed.map(project),
        depth: depth / 4,
      });
    }
  }
  queue.sort((a, b) => a.depth - b.depth);

  for (const face of queue) {
    const pts = face.pts;
    let mx = 0;
    let my = 0;
    for (const p of pts) {
      mx += p[0];
      my += p[1];
    }
    mx /= 4;
    my /= 4;
    /* Grow each quad by ~0.7px so neighbouring faces never leave seams. */
    const grown = pts.map(([x, y]) => {
      const dx = x - mx;
      const dy = y - my;
      const len = Math.hypot(dx, dy) || 1;
      return [x + (dx / len) * 0.7, y + (dy / len) * 0.7];
    });
    const [sx, sy, sw, sh] = face.src;
    const p0 = grown[0];
    const p1 = grown[1];
    const p3 = grown[3];
    ctx.setTransform(
      p1[0] - p0[0], p1[1] - p0[1],
      p3[0] - p0[0], p3[1] - p0[1],
      p0[0], p0[1]);
    ctx.drawImage(skinView.tex, sx, sy, sw, sh, 0, 0, 1, 1);
  }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}

function skinLoop() {
  skinView.raf = 0;
  if (!skinView.ready) return;
  const ease = 0.2;
  skinView.yaw += (skinView.targetYaw - skinView.yaw) * ease;
  skinView.pitch += (skinView.targetPitch - skinView.pitch) * ease;
  skinView.bodyYaw += (skinView.targetBodyYaw - skinView.bodyYaw) * ease;
  skinView.bodyPitch += (skinView.targetBodyPitch - skinView.bodyPitch) * ease;
  renderSkinView();
  if (Math.abs(skinView.targetYaw - skinView.yaw) > 0.0005
      || Math.abs(skinView.targetPitch - skinView.pitch) > 0.0005
      || Math.abs(skinView.targetBodyYaw - skinView.bodyYaw) > 0.0005
      || Math.abs(skinView.targetBodyPitch - skinView.bodyPitch) > 0.0005) {
    skinView.raf = requestAnimationFrame(skinLoop);
  }
}

function kickSkinView() {
  if (!skinView.ready || screen !== "skin") return;
  if (!skinView.raf) skinView.raf = requestAnimationFrame(skinLoop);
}

function stopSkinView() {
  if (skinView.raf) cancelAnimationFrame(skinView.raf);
  skinView.raf = 0;
  skinView.dragging = false;
  skinView.targetYaw = 0;
  skinView.targetPitch = 0;
  const canvas = $("#skin-canvas");
  if (canvas) canvas.classList.remove("dragging");
}

/* The head follows the cursor anywhere in the window. */
function trackSkinPointer(event) {
  if (screen !== "skin") return;
  const canvas = $("#skin-canvas");
  if (!canvas || !skinView.ready) return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const nx = (event.clientX - rect.left - rect.width / 2)
    / Math.max(1, window.innerWidth / 2);
  const ny = (event.clientY - rect.top - rect.height / 2)
    / Math.max(1, window.innerHeight / 2);
  /* The head follows the cursor in every direction. */
  skinView.targetYaw = Math.max(-1, Math.min(1, nx)) * 0.9;
  skinView.targetPitch = Math.max(-1, Math.min(1, ny)) * 0.55;
  kickSkinView();
}

function skinDragStart(event) {
  if (!skinView.ready || event.button !== 0) return;
  skinView.dragging = true;
  skinView.lastX = event.clientX;
  skinView.lastY = event.clientY;
  event.currentTarget.classList.add("dragging");
  if (event.currentTarget.setPointerCapture) {
    event.currentTarget.setPointerCapture(event.pointerId);
  }
}

function skinDragMove(event) {
  if (!skinView.dragging) return;
  const dx = event.clientX - skinView.lastX;
  skinView.lastX = event.clientX;
  skinView.lastY = event.clientY;
  /* Dragging spins the model left/right only. */
  skinView.targetBodyYaw += dx * 0.012;
  skinView.targetBodyPitch = 0;
  kickSkinView();
}

function skinDragEnd(event) {
  if (!skinView.dragging) return;
  skinView.dragging = false;
  event.currentTarget.classList.remove("dragging");
  if (event.currentTarget.releasePointerCapture) {
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch (error) {
      /* pointer capture may already be gone */
    }
  }
}

function drawSkinPreview(dataUrl, variant) {
  const canvas = $("#skin-canvas");
  if (!canvas) return;
  skinView.variant = variant === "slim" ? "slim" : "classic";
  if (!dataUrl) {
    skinView.token += 1;
    skinView.src = "";
    skinView.tex = null;
    skinView.ready = false;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  if (dataUrl === skinView.src && skinView.tex) {
    kickSkinView();
    return;
  }
  const token = ++skinView.token;
  const img = new Image();
  img.onload = () => {
    if (token !== skinView.token) return;
    skinView.src = dataUrl;
    skinView.tex = prepareSkinTexture(img);
    skinView.ready = true;
    kickSkinView();
  };
  img.src = dataUrl;
}

/* The skin page works on any online account, not just the active one. Offline
   accounts stay in the list but are greyed out and cannot be chosen. */
function skinAccountLabel(account) {
  return account.type === "microsoft" ? "Microsoft"
    : account.type === "ely" ? "Ely.by" : "Offline";
}

function fillSkinAccounts() {
  const select = $("#skin-account-select");
  if (!select) return;
  const accounts = S.accounts || [];
  const online = accounts.filter((account) => account.type !== "offline");
  const current = accounts.find((account) => account.id === skin.account);
  if (!current || current.type === "offline") {
    const active = online.find((account) => account.id === S.active_account);
    const fallback = active || online[0]
      || accounts.find((account) => account.active) || accounts[0];
    skin.account = fallback ? fallback.id : "";
  }
  select.replaceChildren();
  if (!accounts.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No accounts";
    select.appendChild(option);
    select.disabled = true;
    return;
  }
  for (const account of accounts) {
    const option = document.createElement("option");
    option.value = account.id;
    option.textContent = `${account.name} · ${skinAccountLabel(account)}`;
    if (account.type === "offline") {
      option.disabled = true;
      option.textContent += " — unavailable";
    }
    option.selected = account.id === skin.account;
    select.appendChild(option);
  }
  select.disabled = !online.length;
}

async function loadSkin() {
  fillSkinAccounts();
  const seq = ++skin.seq;
  skin.busy = true;
  let result = null;
  try {
    result = await call("skin_state", skin.account);
  } finally {
    skin.busy = false;
  }
  if (seq !== skin.seq) return;
  if (!result || !result.ok) {
    skin.data = "";
    skin.type = "";
    setSkinVariantButtons("classic");
    setSkinVariantEnabled(false);
    drawSkinPreview("", "classic");
    $("#skin-sub").textContent = "No account selected";
    $("#skin-account-name").textContent = "No account";
    $("#skin-account-hint").textContent =
      (result && result.error) || "Add an account in Settings first.";
    $("#skin-note").textContent = "";
    $("#skin-path").textContent = "";
    $("#skin-path").title = "";
    $("#btn-skin-apply").textContent = "Apply to account";
    $("#btn-skin-apply").disabled = true;
    $("#btn-skin-choose").disabled = true;
    $("#skin-ely-link").classList.add("hidden");
    return;
  }
  skin.data = result.skin || "";
  skin.variant = result.variant === "slim" ? "slim" : "classic";
  skin.type = result.type || "";
  const isEly = skin.type === "ely";
  const editable = result.online && !isEly;
  setSkinVariantButtons(skin.variant);
  setSkinVariantEnabled(editable);
  drawSkinPreview(skin.data, skin.variant);
  const type = result.type === "microsoft" ? "Microsoft"
    : result.type === "ely" ? "Ely.by" : "Offline";
  $("#skin-sub").textContent = result.name
    ? `${result.name} · ${type}` : type;
  $("#skin-account-name").textContent = result.name || "—";
  $("#skin-account-hint").textContent = isEly
    ? "Ely.by keeps skins on its website; the game loads them through "
      + "authlib-injector."
    : result.online
      ? "The skin belongs to this account and shows in every profile."
      : "Offline accounts cannot use server-side skins.";
  $("#skin-note").textContent = isEly
    ? "The skin cannot be changed from the launcher. Use the link below to "
      + "open ely.by/skins, upload the PNG there and it will show up in game."
    : result.online
      ? "A skin is a 64×64 or 64×32 PNG. It is stored by the launcher and "
        + "only sent to the account you apply it to."
      : "Offline accounts cannot change their skin. Add a Microsoft or "
        + "Ely.by account to manage one.";
  $("#skin-path").textContent = result.remote
    ? "Current skin loaded from ely.by"
    : result.path || (result.default
      ? "Built-in default skin — choose a PNG to replace it."
      : "No skin chosen yet");
  $("#skin-path").title = result.path || "";
  $("#btn-skin-apply").textContent = "Apply to account";
  $("#btn-skin-apply").disabled = !editable || !skin.data;
  $("#btn-skin-choose").disabled = !editable;
  $("#skin-ely-link").classList.toggle("hidden", !isEly);
}

async function chooseSkin() {
  if (skin.busy) return;
  if (skin.type !== "microsoft") return;
  skin.busy = true;
  setStatus("Choose a skin PNG…");
  let result;
  try {
    result = await call("skin_pick", skin.account);
  } finally {
    skin.busy = false;
  }
  if (!result) {
    setStatus("Could not open the file picker.", true);
    return;
  }
  if (!result.ok) {
    if (result.cancelled) setStatus("Ready.");
    else setStatus(result.error || "Could not use that image.", true);
    return;
  }
  await loadSkin();
  setStatus("Skin saved. Press “Apply to account” to send it.");
}

async function changeSkinVariant(variant) {
  if (skin.busy) return;
  if (skin.type !== "microsoft") return;
  if (variant !== "classic" && variant !== "slim") return;
  if (variant === skin.variant) return;
  skin.variant = variant;
  setSkinVariantButtons(variant);
  drawSkinPreview(skin.data, variant);
  const result = await call("skin_variant", variant, skin.account);
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Could not save the model.", true);
  }
}

async function applySkin() {
  if (skin.busy || skin.type !== "microsoft" || !skin.data) return;
  skin.busy = true;
  $("#btn-skin-apply").disabled = true;
  setStatus("Uploading the skin…");
  let result;
  try {
    result = await call("skin_apply", skin.account);
  } finally {
    skin.busy = false;
  }
  if (!result || !result.ok) {
    setStatus((result && result.error) || "Skin upload failed.", true);
    $("#btn-skin-apply").disabled = !skin.data;
    return;
  }
  setStatus(result.message || "Skin applied.");
  await loadSkin();
}
