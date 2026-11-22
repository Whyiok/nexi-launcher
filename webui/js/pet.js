"use strict";

/* Axi and Clawd, the launcher companions.
   One of them sits at the left edge of the top bar. It breathes while idle;
   grab it and it switches to its emoting face, sways in your hand and trails
   the cursor, then springs back to its spot when you let go. The character is
   picked in Settings and stored in settings.json. */

const PETS = {
  axi: { idle: "axi.png", emote: "axi_emote.png", label: "Axi" },
  clawd: { idle: "clawd.png", emote: "clawd_emote.png", label: "Clawd" },
};
const AXI_DRAG_THRESHOLD = 5;

let petKind = "axi";

function petFace(kind, face) {
  const art = PETS[kind] || PETS.axi;
  return face === "emote" ? art.emote : art.idle;
}

/* Called from applyState() whenever the backend echoes the saved choice. */
function applyPet(kind) {
  const next = PETS[kind] ? kind : "axi";
  if (axi.el) {
    axi.el.title = PETS[next].label;
    axi.el.setAttribute("aria-label", PETS[next].label);
  }
  if (next === petKind) return;
  petKind = next;
  if (!axi.holding && !axi.returning) {
    clearTimeout(axi.emoteTimer);
    axi.el.classList.remove("hop");
    axiSetFace(petFace(petKind, "idle"));
  }
}

const axi = {
  el: null,
  img: null,
  slot: null,
  armed: false,
  holding: false,
  returning: false,
  pointerId: null,
  startX: 0,
  startY: 0,
  x: 0,
  y: 0,
  tx: 0,
  ty: 0,
  lean: 0,
  raf: 0,
  moved: false,
  emoteTimer: 0,
};

function axiSetFace(src) {
  if (axi.img.getAttribute("src") !== src) axi.img.setAttribute("src", src);
}

function axiFrame() {
  if (!axi.holding) {
    axi.raf = 0;
    return;
  }
  axi.x += (axi.tx - axi.x) * 0.34;
  axi.y += (axi.ty - axi.y) * 0.34;
  const drift = axi.tx - axi.x;
  const lean = Math.max(-15, Math.min(15, drift * 0.55));
  axi.lean += (lean - axi.lean) * 0.2;
  axi.el.style.transform =
    `translate3d(${axi.x.toFixed(2)}px, ${axi.y.toFixed(2)}px, 0) `
    + `rotate(${axi.lean.toFixed(2)}deg)`;
  axi.raf = requestAnimationFrame(axiFrame);
}

function axiBeginHold() {
  const rect = axi.el.getBoundingClientRect();
  axi.el.style.position = "fixed";
  axi.el.style.left = `${rect.left}px`;
  axi.el.style.top = `${rect.top}px`;
  axi.el.style.width = `${rect.width}px`;
  axi.el.style.height = `${rect.height}px`;
  axi.el.style.zIndex = "80";
  axi.el.style.transform = "translate3d(0, 0, 0)";
  axi.x = 0;
  axi.y = 0;
  axi.tx = 0;
  axi.ty = 0;
  axi.lean = 0;
  axi.holding = true;
  axi.el.classList.add("holding");
  document.body.classList.add("pet-holding");
  axiSetFace(petFace(petKind, "emote"));
  if (!axi.raf) axi.raf = requestAnimationFrame(axiFrame);
}

function axiOnDown(event) {
  if (event.pointerType === "mouse" && event.button !== 0) return;
  if (axi.returning || axi.holding) return;
  event.preventDefault();
  axi.armed = true;
  axi.moved = false;
  axi.pointerId = event.pointerId;
  axi.startX = event.clientX;
  axi.startY = event.clientY;
  try { axi.el.setPointerCapture(event.pointerId); } catch (err) { /* noop */ }
}

function axiOnMove(event) {
  if (!axi.armed || event.pointerId !== axi.pointerId) return;
  const dx = event.clientX - axi.startX;
  const dy = event.clientY - axi.startY;
  if (!axi.holding) {
    if (Math.hypot(dx, dy) < AXI_DRAG_THRESHOLD) return;
    axiBeginHold();
  }
  axi.moved = true;
  axi.tx = dx;
  axi.ty = dy;
}

function axiResetInline() {
  const style = axi.el.style;
  style.position = "";
  style.left = "";
  style.top = "";
  style.width = "";
  style.height = "";
  style.zIndex = "";
  style.transform = "";
  style.transition = "";
}

function axiOnUp(event) {
  if (!axi.armed || event.pointerId !== axi.pointerId) return;
  axi.armed = false;
  try { axi.el.releasePointerCapture(event.pointerId); } catch (err) { /* noop */ }
  axi.pointerId = null;
  if (!axi.holding) {
    if (!axi.moved) axiPet();
    return;
  }
  const wasMoved = axi.moved;
  axi.holding = false;
  if (axi.raf) {
    cancelAnimationFrame(axi.raf);
    axi.raf = 0;
  }
  axi.el.classList.remove("holding");
  document.body.classList.remove("pet-holding");
  axi.returning = true;
  if (!wasMoved) {
    axiResetInline();
    axiSetFace(petFace(petKind, "idle"));
    axi.returning = false;
    axiPet();
    return;
  }
  axi.el.style.transition =
    "transform .34s cubic-bezier(.2, .8, .3, 1)";
  axi.el.style.transform = "translate3d(0, 0, 0) rotate(0deg)";
  setTimeout(() => {
    axiResetInline();
    axiSetFace(petFace(petKind, "idle"));
    axi.returning = false;
  }, 360);
}

/* A plain click (no drag) is a pat: short emote and a hop. */
function axiPet() {
  clearTimeout(axi.emoteTimer);
  axi.el.classList.remove("hop");
  void axi.el.offsetWidth;
  axi.el.classList.add("hop");
  axiSetFace(petFace(petKind, "emote"));
  axi.emoteTimer = setTimeout(() => {
    axi.el.classList.remove("hop");
    axiSetFace(petFace(petKind, "idle"));
  }, 640);
}

function axiInit() {
  axi.el = $("#pet");
  axi.img = $("#pet-img");
  axi.slot = $("#pet-slot");
  if (!axi.el || !axi.img || !axi.slot) return;
  /* Warm the browser cache so a face swap never stutters. */
  Object.values(PETS).forEach((art) => {
    [art.idle, art.emote].forEach((src) => {
      const img = new Image();
      img.src = src;
    });
  });
  axi.el.addEventListener("pointerdown", axiOnDown);
  axi.el.addEventListener("pointermove", axiOnMove);
  axi.el.addEventListener("pointerup", axiOnUp);
  axi.el.addEventListener("pointercancel", axiOnUp);
  axi.el.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      axiPet();
    }
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && axi.holding) {
      axi.tx = 0;
      axi.ty = 0;
      axiOnUp({ pointerId: axi.pointerId });
    }
  });
  window.addEventListener("blur", () => {
    if (axi.holding && axi.pointerId !== null) {
      axi.tx = 0;
      axi.ty = 0;
      axiOnUp({ pointerId: axi.pointerId });
    }
  });
}

axiInit();
