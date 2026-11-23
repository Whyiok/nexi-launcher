"use strict";

/* ---------------------------------------------------------------- home */

/* The main menu: a slowly panning block landscape with the builds, the
   recent worlds and a big Play button for the most recent build. */

const home = { worlds: [], loaded: false, request: 0, reloadTimer: 0,
               chosen: "", bgFailed: "" };

function homeBuildsSorted() {
  return [...S.instances].sort((a, b) =>
    (Number(b.last_played) || 0) - (Number(a.last_played) || 0)
    || String(a.name || "").localeCompare(String(b.name || "")));
}

function homeProfile(slug) {
  return S.instances.find((inst) => inst.slug === slug) || null;
}

/* The build Home offers to play: the one the user clicked here, otherwise
   the most recently launched one, otherwise the selected build. */
function homeLastInstance() {
  if (!S.instances.length) return null;
  const chosen = home.chosen ? homeProfile(home.chosen) : null;
  if (chosen) return chosen;
  let best = null;
  for (const inst of S.instances) {
    if (!best || (Number(inst.last_played) || 0) > (Number(best.last_played) || 0)) {
      best = inst;
    }
  }
  if (best && Number(best.last_played)) return best;
  return S.instance || homeProfile(S.selected) || S.instances[0];
}

/* A click on a build row makes it the default build of the main menu; the
   page stays on Home and the Play button switches to it. */
async function selectHomeBuild(slug) {
  const inst = homeProfile(slug);
  if (!inst) return;
  home.chosen = slug;
  renderHome();
  await selectProfileSilently(slug);
  renderHome();
  setStatus(`Selected "${inst.name}" — Play starts it.`);
}

function homeLoaderLabel(inst) {
  if (!inst) return "vanilla";
  if (inst.loader === "any") return "vanilla";
  const loader = LOADER_LABELS[inst.loader] || inst.loader;
  return inst.loader_version ? `${loader} ${inst.loader_version}` : loader;
}

function homeAgo(epochSeconds) {
  const stamp = Number(epochSeconds) || 0;
  if (!stamp) return "";
  const diff = Math.max(0, Date.now() / 1000 - stamp);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} d ago`;
  return new Date(stamp * 1000).toLocaleDateString();
}

function renderHome() {
  applyHomeBackground();
  const last = homeLastInstance();
  const title = $("#home-title");
  if (title) title.textContent = last ? last.name : "No profiles yet";
  const meta = $("#home-meta");
  if (meta) {
    meta.textContent = last
      ? `Minecraft ${last.base} · ${homeLoaderLabel(last)}`
      : "Create a profile to get started.";
  }
  renderHomeBadges(last);
  renderHomePlay();
  renderHomeBuilds();
  renderHomeWorlds();
}

function renderHomeBadges(inst) {
  const time = $("#home-playtime");
  if (time) {
    time.classList.toggle("hidden", !inst);
    const text = $("#home-playtime-text");
    if (text && inst) text.textContent = formatPlaytime(inst.playtime);
  }
}

function renderHomePlay() {
  const last = homeLastInstance();
  const button = $("#home-play");
  if (!button) return;
  const running = !!last && isInstanceRunning(last.slug);
  const starting = !!last && isInstanceStarting(last.slug);
  button.disabled = !last || starting;
  button.classList.toggle("running", running);
  $("#home-play-label").textContent = running
    ? "Stop" : (starting ? "Starting…" : "Play");
  const glyph = $("#home-play-icon");
  if (glyph) glyph.setAttribute("href", running ? "#i-stop" : "#i-play");
  button.title = !last
    ? "Create a profile to get started."
    : (running ? "Stop the game" : `Play "${last.name}"`);
  button.setAttribute("aria-label", button.title);
}

function homeBuildIcon(inst) {
  const icon = elem("span", "home-build-icon");
  if (inst.icon) {
    const img = new Image();
    img.alt = "";
    img.decoding = "async";
    img.src = inst.icon;
    img.addEventListener("error", () => {
      img.remove();
      icon.textContent = profileLetter(inst.name);
    });
    icon.appendChild(img);
  } else {
    icon.textContent = profileLetter(inst.name);
  }
  return icon;
}

/* Selecting a build only moves the accent highlight; the rows themselves
   stay put. Rebuilding them on every click made the list blink (icons
   reloaded, a hovered row lost its hover) and nudged the layout, so they are
   only replaced when the build data really changes. */
let homeBuildsKey = "";

function homeBuildsSignature() {
  return homeBuildsSorted().map((inst) => [
    inst.slug,
    inst.name,
    inst.base,
    inst.loader || "",
    inst.loader_version || "",
    Number(inst.last_played) || 0,
    inst.icon || "",
  ].join("\u0000")).join("\u0001");
}

function renderHomeBuilds() {
  const list = $("#home-builds");
  if (!list) return;
  const key = homeBuildsSignature();
  if (key !== homeBuildsKey || !list.childElementCount) {
    homeBuildsKey = key;
    list.replaceChildren();
    if (!S.instances.length) {
      list.appendChild(elem("div", "home-empty",
                            "Create a profile to get started."));
      return;
    }
    const last = homeLastInstance();
    for (const inst of homeBuildsSorted()) {
      const row = elem("div", "home-build" +
        (last && inst.slug === last.slug ? " last" : ""));
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.dataset.slug = inst.slug;
      row.title = `${inst.name} — Minecraft ${inst.base} · ${homeLoaderLabel(inst)}`;
      row.appendChild(homeBuildIcon(inst));
      const text = elem("span", "home-build-text");
      text.appendChild(elem("span", "home-build-name", inst.name));
      text.appendChild(elem("span", "home-build-meta",
        `Minecraft ${inst.base} · ${homeLoaderLabel(inst)}`));
      row.appendChild(text);
      const play = elem("button", "home-build-play");
      play.type = "button";
      play.dataset.homePlay = inst.slug;
      play.title = "Play this build";
      play.setAttribute("aria-label", `Play ${inst.name}`);
      play.appendChild(iconNode("i-play"));
      row.appendChild(play);
      list.appendChild(row);
    }
  }
  const last = homeLastInstance();
  for (const row of $$(".home-build", list)) {
    row.classList.toggle("last", !!last && row.dataset.slug === last.slug);
  }
}

function renderHomeWorlds() {
  const list = $("#home-worlds");
  if (!list) return;
  list.replaceChildren();
  if (!home.loaded) {
    list.appendChild(elem("div", "home-empty", "Loading…"));
    return;
  }
  if (!home.worlds.length) {
    list.appendChild(elem("div", "home-empty", "No recent worlds yet."));
    return;
  }
  for (const world of home.worlds) {
    const row = elem("button", "home-world");
    row.type = "button";
    row.dataset.slug = world.profile_slug;
    row.dataset.world = world.world;
    row.title = `Continue in "${world.world}"`;
    const icon = elem("span", "home-world-icon");
    const inst = homeProfile(world.profile_slug);
    if (inst && inst.icon) {
      const img = new Image();
      img.alt = "";
      img.decoding = "async";
      img.src = inst.icon;
      img.addEventListener("error", () => {
        img.remove();
        icon.appendChild(iconNode("i-world"));
      });
      icon.appendChild(img);
    } else {
      icon.appendChild(iconNode("i-world"));
    }
    row.appendChild(icon);
    const text = elem("span", "home-world-text");
    text.appendChild(elem("span", "home-world-name", world.world));
    text.appendChild(elem("span", "home-world-meta",
      `${world.profile_name || ""} · ${homeAgo(world.modified)}`
        .replace(/^ · /, "")));
    row.appendChild(text);
    const go = iconNode("i-play");
    go.classList.add("home-world-go");
    row.appendChild(go);
    list.appendChild(row);
  }
}

/* Re-render just the Play button when the game starts or stops. */
function syncHome() {
  if (screen === "home") renderHomePlay();
}

async function loadHome() {
  const seq = ++home.request;
  const result = await call("home_state");
  if (seq !== home.request) return;
  home.loaded = true;
  home.worlds = (result && result.ok && Array.isArray(result.worlds))
    ? result.worlds : [];
  if (screen === "home") renderHomeWorlds();
}

function maybeReloadHome() {
  if (screen !== "home") return;
  clearTimeout(home.reloadTimer);
  home.reloadTimer = setTimeout(loadHome, 400);
}

/* Launch (or stop) one build, optionally straight into one of its worlds. */
async function homeStart(slug, world = "") {
  const inst = homeProfile(slug);
  if (!inst || playBusy) return;
  home.chosen = slug;
  if (isInstanceRunning(slug)) {
    if (world) {
      setStatus("This profile is already running.", true);
      return;
    }
    await selectProfileSilently(slug);
    await stopGame();
    renderHome();
    return;
  }
  if (isInstanceStarting(slug)) return;
  await selectProfileSilently(slug);
  markStarting(slug);
  renderHome();
  setStatus(world
    ? `Starting "${inst.name}" in "${world}"…`
    : `Starting "${inst.name}"…`);
  const result = await call("play", world);
  if (!result || !result.ok) {
    clearStarting(slug);
    setStatus((result && result.error) || "Could not start the game.", true);
    renderHome();
    return;
  }
  await refreshState();
  if (screen === "home") loadHome();
  renderHome();
}

function homePlay() {
  const last = homeLastInstance();
  if (!last) {
    setScreen("create");
    return;
  }
  return homeStart(last.slug);
}

function homePlayWorld(slug, world) {
  if (!slug || !world) return;
  return homeStart(slug, world);
}

/* ------------------------------------------------------------ panorama */

/* The background picked in Settings replaces the panorama. GIFs go into an
   <img>, MP4/WebM into a muted looping <video>; both are served by the
   launcher's loopback server because the page itself runs over http. */

function homeBackground() {
  const bg = S && S.background;
  if (!bg || !bg.active || !bg.url || home.bgFailed === bg.url) return null;
  return bg;
}

/* A background that cannot be decoded falls back to the panorama instead of
   leaving a black rectangle. */
function bindHomeBackground() {
  const recover = () => {
    const bg = S && S.background;
    if (!bg || !bg.active || !bg.url) return;
    home.bgFailed = bg.url;
    const video = $("#home-bg-video");
    if (video) video.hidden = true;
    const image = $("#home-bg-image");
    if (image) image.hidden = true;
    if (screen === "home") startHomePanorama();
  };
  const video = $("#home-bg-video");
  if (video) video.addEventListener("error", recover);
  const image = $("#home-bg-image");
  if (image) image.addEventListener("error", recover);
}

function applyHomeBackground() {
  const image = $("#home-bg-image");
  const video = $("#home-bg-video");
  const canvas = $("#home-panorama");
  const bg = homeBackground();
  const kind = bg ? bg.kind : "";
  if (canvas) canvas.classList.toggle("off", !!bg);
  if (image) {
    if (kind === "image") {
      if (image.getAttribute("src") !== bg.url) image.src = bg.url;
      image.hidden = false;
    } else {
      image.hidden = true;
    }
  }
  if (video) {
    if (kind === "video") {
      if (video.getAttribute("src") !== bg.url) {
        video.src = bg.url;
        video.load();
      }
      video.hidden = false;
      if (screen === "home") {
        const playing = video.play();
        if (playing && playing.catch) playing.catch(() => {});
      }
    } else {
      if (!video.hidden) video.pause();
      video.hidden = true;
    }
  }
}

const panorama = {
  raf: 0, last: 0, time: 0, scroll: 0, reduce: false,
  canvas: null, ctx: null, width: 0, height: 0, dpr: 1,
  features: null, accent: "110, 231, 183",
};

function panoramaSeed(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function panoramaWrap(value, size) {
  return ((value % size) + size) % size;
}

function panoramaFeatures(width, height) {
  const rnd = panoramaSeed(20261116);
  const tile = Math.max(640, Math.round(width * 1.25));
  const stars = [];
  const starCount = Math.round(Math.min(90, Math.max(28, width / 20)));
  for (let i = 0; i < starCount; i += 1) {
    stars.push({
      x: rnd() * tile,
      y: rnd() * height * 0.52,
      size: rnd() < 0.82 ? 1 : 2,
      alpha: 0.12 + rnd() * 0.4,
    });
  }
  const clouds = [];
  for (let i = 0; i < 14; i += 1) {
    const blocks = [];
    const blockCount = 2 + Math.floor(rnd() * 3);
    for (let b = 0; b < blockCount; b += 1) {
      blocks.push({
        dx: b * (18 + rnd() * 16),
        dy: (rnd() - 0.5) * 10,
        w: 26 + rnd() * 40,
        h: 10 + rnd() * 8,
      });
    }
    clouds.push({
      x: rnd() * tile,
      y: height * (0.05 + rnd() * 0.32),
      blocks,
      alpha: 0.06 + rnd() * 0.09,
      speed: 0.08 + rnd() * 0.1,
    });
  }
  const trees = [];
  for (let i = 0; i < 11; i += 1) {
    trees.push({ x: rnd() * tile, scale: 0.55 + rnd() * 0.85 });
  }
  return { tile, stars, clouds, trees };
}

const HOME_HILLS = {
  far: { speed: 0.1, block: 18, p1: 0.8, p2: 2.4, p3: 5.1 },
  mid: { speed: 0.27, block: 16, p1: 2.1, p2: 5.6, p3: 1.3 },
  near: { speed: 0.56, block: 14, p1: 4.4, p2: 0.7, p3: 3.6 },
};

function homeHillHeight(x, tile, opts) {
  const phase = (x / tile) * Math.PI * 2;
  const wave = Math.sin(phase + opts.p1)
    + 0.55 * Math.sin(phase * 2 + opts.p2)
    + 0.24 * Math.sin(phase * 3 + opts.p3);
  return opts.base - opts.amp * (0.5 + 0.5 * (wave / 1.79));
}

function homeHillLayer(ctx, width, height, tile, scroll, opts, colors) {
  const name = opts.name;
  const layer = HOME_HILLS[name];
  const offset = panoramaWrap(scroll * layer.speed, tile);
  const step = layer.block;
  const geometry = { base: height * opts.base, amp: height * opts.amp };
  const options = Object.assign({}, layer, geometry);
  const tops = [];
  ctx.beginPath();
  ctx.moveTo(-step, height);
  for (let x = -step; x <= width + step; x += step) {
    const top = homeHillHeight(x + offset, tile, options);
    tops.push({ x, y: Math.round(top / step) * step });
  }
  for (const point of tops) ctx.lineTo(point.x, point.y);
  ctx.lineTo(width + step, height);
  ctx.closePath();
  ctx.fillStyle = colors.fill;
  ctx.fill();
  if (colors.top) {
    ctx.strokeStyle = colors.top;
    ctx.lineWidth = Math.max(2, step * 0.3);
    ctx.beginPath();
    tops.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();
  }
  return { options, offset };
}

function homeTree(ctx, x, ground, scale, color) {
  const trunk = Math.max(3, Math.round(4 * scale));
  const trunkHeight = Math.round(30 * scale);
  ctx.fillStyle = color;
  ctx.fillRect(Math.round(x - trunk / 2),
               Math.round(ground - trunkHeight), trunk, trunkHeight);
  const leaf = Math.max(10, Math.round(20 * scale));
  const top = ground - trunkHeight - leaf * 0.6;
  const blocks = [
    [x - leaf * 0.9, top, leaf * 1.8, leaf * 0.8],
    [x - leaf * 0.6, top - leaf * 0.5, leaf * 1.2, leaf * 0.8],
    [x - leaf * 0.35, top - leaf * 0.95, leaf * 0.7, leaf * 0.6],
  ];
  for (const [bx, by, bw, bh] of blocks) {
    ctx.fillRect(Math.round(bx), Math.round(by),
                 Math.round(bw), Math.round(bh));
  }
}

function homePanoramaDraw() {
  const ctx = panorama.ctx;
  if (!ctx || !panorama.width || !panorama.height) return;
  const width = panorama.width;
  const height = panorama.height;
  const features = panorama.features
    || (panorama.features = panoramaFeatures(width, height));
  const tile = features.tile;
  const scroll = panorama.scroll;
  const light = activeMode === "light";
  const accent = panorama.accent;

  ctx.setTransform(panorama.dpr, 0, 0, panorama.dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const sky = ctx.createLinearGradient(0, 0, 0, height);
  if (light) {
    sky.addColorStop(0, "#7fb9dd");
    sky.addColorStop(0.48, "#cfe6ef");
    sky.addColorStop(1, "#f2e2c4");
  } else {
    sky.addColorStop(0, "#050b14");
    sky.addColorStop(0.42, "#0d1e35");
    sky.addColorStop(0.72, "#1b3c54");
    sky.addColorStop(1, "#2b5459");
  }
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, width, height);

  const glow = ctx.createRadialGradient(
    width * 0.72, height * 0.66, 0,
    width * 0.72, height * 0.66, Math.max(width, height) * 0.85);
  glow.addColorStop(0, `rgba(${accent}, ${light ? 0.2 : 0.3})`);
  glow.addColorStop(0.55, `rgba(${accent}, ${light ? 0.06 : 0.1})`);
  glow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, width, height);

  if (!light) {
    ctx.fillStyle = "#dfeaff";
    for (const star of features.stars) {
      const x = panoramaWrap(star.x - scroll * 0.03, tile);
      const twinkle = 0.6 + 0.4 * Math.sin(panorama.time * 1.7 + star.x);
      ctx.globalAlpha = star.alpha * twinkle;
      for (const ox of [x, x + tile, x - tile]) {
        if (ox < -4 || ox > width + 4) continue;
        ctx.fillRect(Math.round(ox), Math.round(star.y),
                     star.size, star.size);
      }
    }
    ctx.globalAlpha = 1;
  }

  const sunX = panoramaWrap(width * 0.76 - scroll * 0.05, width + 240) - 120;
  const sunY = height * 0.2;
  const sunSize = Math.max(34, Math.min(64, width * 0.042));
  const sunGlow = ctx.createRadialGradient(
    sunX, sunY, 0, sunX, sunY, sunSize * 4);
  sunGlow.addColorStop(0, light ? "rgba(255,244,205,.8)"
                                : "rgba(255,216,160,.5)");
  sunGlow.addColorStop(0.32, light ? "rgba(255,238,195,.34)"
                                   : "rgba(255,190,120,.16)");
  sunGlow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = sunGlow;
  ctx.fillRect(sunX - sunSize * 4, sunY - sunSize * 4,
               sunSize * 8, sunSize * 8);
  ctx.fillStyle = light ? "#fff5d6" : "#ffe3b0";
  ctx.fillRect(Math.round(sunX - sunSize / 2), Math.round(sunY - sunSize / 2),
               sunSize, sunSize);

  ctx.fillStyle = light ? "#ffffff" : "#e9f2ff";
  for (const cloud of features.clouds) {
    const x = panoramaWrap(cloud.x - scroll * cloud.speed, tile);
    ctx.globalAlpha = cloud.alpha;
    for (const ox of [x, x + tile, x - tile]) {
      for (const block of cloud.blocks) {
        const bx = ox + block.dx;
        if (bx > width + 90 || bx + block.w < -90) continue;
        ctx.fillRect(Math.round(bx), Math.round(cloud.y + block.dy),
                     Math.round(block.w), Math.round(block.h));
      }
    }
  }
  ctx.globalAlpha = 1;

  homeHillLayer(ctx, width, height, tile, scroll,
    { name: "far", base: 0.62, amp: 0.11 },
    { fill: light ? "#a9cbd4" : "#10293c" });
  homeHillLayer(ctx, width, height, tile, scroll,
    { name: "mid", base: 0.73, amp: 0.13 },
    { fill: light ? "#6f9f8f" : "#0c2029" });
  const near = homeHillLayer(ctx, width, height, tile, scroll,
    { name: "near", base: 0.85, amp: 0.1 },
    { fill: light ? "#39664a" : "#08160f",
      top: `rgba(${accent}, ${light ? 0.55 : 0.4})` });

  ctx.fillStyle = light ? "#2c513a" : "#0a1a11";
  for (const tree of features.trees) {
    const x = panoramaWrap(tree.x - scroll * near.options.speed, tile);
    for (const ox of [x, x + tile, x - tile]) {
      if (ox < -60 || ox > width + 60) continue;
      const ground = homeHillHeight(ox + near.offset, tile, near.options);
      homeTree(ctx, ox, ground, tree.scale, ctx.fillStyle);
    }
  }

  const vignette = ctx.createRadialGradient(
    width * 0.5, height * 0.45, Math.min(width, height) * 0.2,
    width * 0.5, height * 0.45, Math.max(width, height) * 0.8);
  vignette.addColorStop(0, "rgba(0,0,0,0)");
  vignette.addColorStop(1, light ? "rgba(18,32,42,.2)" : "rgba(0,0,0,.5)");
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, width, height);
}

function homePanoramaFrame(now) {
  if (!panorama.ctx) return;
  if (!panorama.last) panorama.last = now;
  const delta = Math.min(0.05, (now - panorama.last) / 1000);
  panorama.last = now;
  panorama.time += delta;
  if (!panorama.reduce) panorama.scroll += delta * 16;
  homePanoramaDraw();
  panorama.raf = panorama.reduce ? 0 : requestAnimationFrame(homePanoramaFrame);
}

function resizeHomePanorama() {
  const canvas = panorama.canvas || $("#home-panorama");
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const width = Math.round(rect.width);
  const height = Math.round(rect.height);
  if (width < 2 || height < 2) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  panorama.canvas = canvas;
  panorama.ctx = panorama.ctx || canvas.getContext("2d");
  if (canvas.width !== Math.round(width * dpr)
      || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  panorama.width = width;
  panorama.height = height;
  panorama.dpr = dpr;
  panorama.features = panoramaFeatures(width, height);
  if (!panorama.raf) homePanoramaDraw();
}

function startHomePanorama() {
  const canvas = $("#home-panorama");
  if (!canvas) return;
  applyHomeBackground();
  if (homeBackground()) {
    // The custom image/video covers the canvas: no need to animate it.
    if (panorama.raf) cancelAnimationFrame(panorama.raf);
    panorama.raf = 0;
    panorama.last = 0;
    return;
  }
  panorama.canvas = canvas;
  panorama.ctx = canvas.getContext("2d");
  panorama.reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  panorama.accent = (getComputedStyle(document.documentElement)
    .getPropertyValue("--accent-rgb").trim()) || panorama.accent;
  resizeHomePanorama();
  if (!panorama.raf) {
    panorama.last = 0;
    panorama.raf = requestAnimationFrame(homePanoramaFrame);
  }
}

function stopHomePanorama() {
  if (panorama.raf) cancelAnimationFrame(panorama.raf);
  panorama.raf = 0;
  panorama.last = 0;
  const video = $("#home-bg-video");
  if (video) video.pause();
}

/* Accent and colour mode changed: pick the new colours up right away. */
function refreshHomePanorama() {
  panorama.accent = (getComputedStyle(document.documentElement)
    .getPropertyValue("--accent-rgb").trim()) || panorama.accent;
  if (screen === "home" && !panorama.raf) homePanoramaDraw();
}

/* The Play button leans a few degrees towards the pointer. */
function bindHomePlayTilt() {
  const button = $("#home-play");
  if (!button) return;
  button.addEventListener("pointermove", (event) => {
    const rect = button.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = (event.clientX - rect.left) / rect.width - 0.5;
    const y = (event.clientY - rect.top) / rect.height - 0.5;
    button.style.setProperty("--tilt-y", `${(x * 7).toFixed(2)}deg`);
    button.style.setProperty("--tilt-x", `${(-y * 6).toFixed(2)}deg`);
  });
  button.addEventListener("pointerleave", () => {
    button.style.removeProperty("--tilt-x");
    button.style.removeProperty("--tilt-y");
  });
}

bindHomeBackground();
bindHomePlayTilt();
