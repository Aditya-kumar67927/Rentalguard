// End-to-end browser check using headless Chrome over the DevTools Protocol.
// No npm dependencies: Node >= 22 provides fetch and WebSocket.
//
//   node tests/e2e/browser_flow.mjs [baseUrl] [chromePath] [screenshotDir]
//
// Flow: register -> analyze demo listing -> results -> history -> market -> dashboard
//       -> methodology -> permalink -> report -> logout, collecting JS exceptions,
//       console errors and failed (>= 400) requests on every page.
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.argv[2] || "http://127.0.0.1:5000";
const CHROME = process.argv[3] || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const SHOTS = process.argv[4] || join(tmpdir(), "rentalguard-shots");
const PORT = 9333;
mkdirSync(SHOTS, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, "--no-first-run",
  "--no-default-browser-check", `--user-data-dir=${mkdtempSync(join(tmpdir(), "rg-chrome-"))}`,
  "--window-size=1366,900", "about:blank"], { stdio: "ignore" });

async function endpoint() {
  for (let i = 0; i < 50; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = targets.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch (_) { /* not up yet */ }
    await sleep(200);
  }
  throw new Error("Chrome did not start");
}

const ws = new WebSocket(await endpoint());
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let seq = 0;
const pending = new Map();
const listeners = [];
const problems = [];
let currentPage = "";

ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    return;
  }
  if (msg.method === "Runtime.exceptionThrown") {
    problems.push(`[${currentPage}] JS exception: ${msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text}`);
  } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
    problems.push(`[${currentPage}] console.error: ${msg.params.args.map((a) => a.value ?? a.description).join(" ")}`);
  } else if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error"
             && !(currentPage.includes("expect-400") && /status of 400/.test(msg.params.entry.text))) {
    problems.push(`[${currentPage}] ${msg.params.entry.source}: ${msg.params.entry.text} ${msg.params.entry.url || ""}`);
  } else if (msg.method === "Network.responseReceived" && msg.params.response.status >= 400
             && !(currentPage.includes("expect-400") && msg.params.response.status === 400)) {
    problems.push(`[${currentPage}] HTTP ${msg.params.response.status} ${msg.params.response.url}`);
  }
  listeners.forEach((fn) => fn(msg));
});

function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evaluate(expression) {
  const res = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (res.exceptionDetails) throw new Error(`eval failed: ${res.exceptionDetails.exception?.description}`);
  return res.result.value;
}

async function waitFor(expression, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await evaluate(`!!(${expression})`)) return true;
    await sleep(150);
  }
  throw new Error(`timeout waiting for: ${expression}`);
}

async function goto(path) {
  currentPage = path;
  const loaded = new Promise((r) => {
    const fn = (m) => { if (m.method === "Page.loadEventFired") { listeners.splice(listeners.indexOf(fn), 1); r(); } };
    listeners.push(fn);
  });
  await send("Page.navigate", { url: BASE + path });
  await loaded;
}

async function shot(name, mobile = false) {
  if (mobile) await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await sleep(700);
  const { data } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true,
    clip: undefined });
  writeFileSync(join(SHOTS, `${name}.png`), Buffer.from(data, "base64"));
  if (mobile) await send("Emulation.clearDeviceMetricsOverride");
}

const steps = [];
const step = async (name, fn) => {
  try { await fn(); steps.push(`PASS ${name}`); } catch (e) { steps.push(`FAIL ${name}: ${e.message}`); }
};

await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable"); await send("Network.enable");
// Deterministic screenshots: no chart animations while the page is resized for full-page capture
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
const email = `e2e-${Date.now()}@example.com`;
let analysisUrl = "";

await step("landing page", async () => {
  await goto("/");
  await waitFor(`document.querySelector('[data-stat=total]').textContent !== '—'`);
  await shot("01_landing");
});
await step("register", async () => {
  await goto("/register");
  await evaluate(`(() => { const f = document.getElementById('register-form');
    f.name.value = 'E2E Tester'; f.email.value = '${email}'; f.password.value = 'e2e-pass-123';
    f.requestSubmit(); })()`);
  await waitFor(`location.pathname === '/analyze'`);
});
await step("analyze demo listing (payment request)", async () => {
  currentPage = "/analyze";
  await evaluate(`document.querySelector('[data-example=payment]').click()`);
  await evaluate(`document.getElementById('analyze-form').requestSubmit()`);
  await waitFor(`document.querySelector('#result-section .gauge')`);
  const level = await evaluate(`document.querySelector('#result-section .badge').textContent`);
  if (!/risk/i.test(level)) throw new Error(`unexpected level text ${level}`);
  analysisUrl = await evaluate(`document.querySelector('#result-section a[href^="/results/"]').getAttribute('href')`);
  await shot("02_analyze_result");
  await shot("02b_analyze_result_mobile", true);
});
await step("analyze invalid form shows field errors", async () => {
  currentPage = "/analyze (expect-400)";
  await evaluate(`(() => { const f = document.getElementById('analyze-form'); f.reset(); })()`);
  await sleep(100);
  await evaluate(`document.getElementById('analyze-form').requestSubmit()`);
  await waitFor(`document.querySelector('[data-error-for=rent]').textContent.length > 0`);
});
await step("results permalink + report dialog", async () => {
  await goto(analysisUrl);
  await waitFor(`document.querySelector('#result-section .gauge')`);
  await evaluate(`[...document.querySelectorAll('#result-section button')].find(b => b.textContent.includes('Report')).click()`);
  await waitFor(`document.getElementById('report-dialog').open`);
  await evaluate(`document.getElementById('report-form').requestSubmit()`);
  await waitFor(`!document.getElementById('report-dialog').open`);
  await shot("03_results_page");
});
await step("history search/filter", async () => {
  await goto("/history");
  await waitFor(`document.querySelectorAll('#listing-rows tr td a').length >= 1`);
  await evaluate(`(() => { const s = document.getElementById('f-level'); s.value = 'LOW'; s.dispatchEvent(new Event('change', {bubbles: true})); })()`);
  await waitFor(`document.getElementById('listing-rows').textContent.includes('No matching listings')`);
  await shot("04_history");
});
await step("market explorer", async () => {
  await goto("/market");
  await waitFor(`document.querySelectorAll('#listing-rows tr').length >= 10`);
  await evaluate(`(() => { const q = document.getElementById('f-q'); q.value = 'powai'; q.dispatchEvent(new Event('input', {bubbles: true})); })()`);
  await waitFor(`[...document.querySelectorAll('#listing-rows tr td:first-child')].every(td => /powai/i.test(td.textContent))`);
  await shot("05_market");
});
await step("dashboard charts", async () => {
  await goto("/dashboard");
  await waitFor(`typeof Chart !== 'undefined' && Chart.getChart('chart-risk') && Chart.getChart('chart-bhk')`);
  await waitFor(`document.querySelectorAll('#top-risk tr td a').length >= 1`);
  await shot("06_dashboard");
  await evaluate(`document.querySelector('.segmented [data-scope=mine]').click()`);
  await waitFor(`document.querySelector('[data-kpi=analyzed]').textContent === '1'`);
  await shot("06b_dashboard_mine");
  await shot("06c_dashboard_mobile", true);
});
await step("methodology", async () => {
  await goto("/methodology");
  await waitFor(`document.querySelector('#model-info dl')`);
  await shot("07_methodology");
});
await step("logout", async () => {
  await goto("/analyze");
  await evaluate(`document.getElementById('logout-btn').click()`);
  await waitFor(`location.pathname === '/'`);
  await waitFor(`document.body.dataset.authenticated === 'false'`);
});
await step("protected page redirects after logout", async () => {
  await goto("/history");
  await waitFor(`location.pathname === '/login'`);
});

console.log(steps.join("\n"));
console.log(problems.length ? `\nBrowser problems (${problems.length}):\n` + problems.join("\n") : "\nNo JS exceptions, console errors or failed requests.");
console.log(`Screenshots: ${SHOTS}`);
ws.close();
chrome.kill();
process.exit(steps.some((s) => s.startsWith("FAIL")) || problems.length ? 1 : 0);
