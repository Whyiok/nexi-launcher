"use strict";

/* ------------------------------------------------------------ crash screen */
/* Shown when the game exits on its own. The backend has already read the
   log, named a likely cause and offered a repair; this only renders it. */

const crashScreen = { open: false, slug: "", fix: null };

function crashNode(id) {
  return document.getElementById(id);
}

function showCrashScreen(ev) {
  const root = crashNode("crash-screen");
  if (!root) return;
  const crash = ev && ev.crash && typeof ev.crash === "object" ? ev.crash : {};
  crashScreen.open = true;
  crashScreen.slug = ev.slug || (S.instance ? S.instance.slug : "");
  crashScreen.fix = crash.fix && crash.fix.action ? crash.fix : null;

  crashNode("crash-title").textContent =
    crash.title || "Minecraft closed unexpectedly";
  crashNode("crash-summary").textContent = crash.summary || ev.message ||
    "The game exited before it could show a clear error.";
  crashNode("crash-why").textContent = crash.why || "";
  crashNode("crash-why-block").classList.toggle("hidden", !crash.why);

  const steps = Array.isArray(crash.steps) ? crash.steps : [];
  const list = crashNode("crash-steps");
  list.textContent = "";
  for (const step of steps) {
    const item = document.createElement("li");
    item.textContent = String(step);
    list.appendChild(item);
  }
  crashNode("crash-steps-block").classList.toggle("hidden", !steps.length);

  crashNode("crash-log").textContent = String(crash.log || "").trim() ||
    "The game stopped before writing anything to the log.";
  const report = crashNode("crash-report-path");
  report.textContent = crash.report_name
    ? `Crash report: ${crash.report_name}`
    : "No crash report was written for this session.";
  crashNode("crash-details").open = false;

  const fix = crashNode("btn-crash-fix");
  fix.classList.toggle("hidden", !crashScreen.fix);
  fix.disabled = false;
  fix.textContent = crashScreen.fix
    ? (crashScreen.fix.label || "Fix automatically")
    : "Fix automatically";

  const status = crashNode("crash-status");
  status.textContent = "";
  status.classList.add("hidden");
  status.classList.remove("error");

  root.classList.remove("hidden");
  document.body.classList.add("crash-open");
  fix.classList.contains("hidden")
    ? crashNode("btn-crash-close").focus()
    : fix.focus();
}

function hideCrashScreen() {
  const root = crashNode("crash-screen");
  if (!root) return;
  root.classList.add("hidden");
  document.body.classList.remove("crash-open");
  crashScreen.open = false;
  crashScreen.fix = null;
}

async function runCrashFix() {
  if (!crashScreen.fix) return;
  const fix = crashScreen.fix;
  const button = crashNode("btn-crash-fix");
  const status = crashNode("crash-status");
  const verifying = fix.action === "verify_files";
  button.disabled = true;
  button.textContent = verifying ? "Checking files…" : "Applying…";
  status.classList.remove("hidden");
  status.classList.remove("error");
  status.textContent = verifying
    ? "Checking every game file — this can take a few minutes."
    : "Applying the fix…";
  const result = await call("crash_fix", fix.action, crashScreen.slug);
  if (result && result.ok) {
    status.textContent = result.message || "Fixed. Start the game again.";
    button.classList.add("hidden");
    crashNode("btn-crash-close").focus();
    if (typeof refreshState === "function") refreshState();
    return;
  }
  status.classList.add("error");
  status.textContent = (result && result.error) ||
    "The fix could not be applied.";
  button.disabled = false;
  button.textContent = fix.label || "Fix automatically";
}

function bindCrashScreen() {
  const close = () => hideCrashScreen();
  for (const id of ["btn-crash-close", "btn-crash-close-2"]) {
    const node = crashNode(id);
    if (node) node.addEventListener("click", close);
  }
  const fix = crashNode("btn-crash-fix");
  if (fix) fix.addEventListener("click", runCrashFix);
  const folder = crashNode("btn-crash-logs");
  if (folder) {
    folder.addEventListener("click", () => call("open_instance", "logs"));
  }
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && crashScreen.open) hideCrashScreen();
  });
}
