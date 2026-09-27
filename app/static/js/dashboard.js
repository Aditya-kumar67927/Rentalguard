/* Dashboard charts (Chart.js). Single-series charts use one hue; the risk
 * distribution uses the reserved status colours, always paired with text labels. */
"use strict";
(() => {
  const { el, fmtINR, fmtNum, badge } = RG;
  const buttons = document.querySelectorAll(".segmented button");
  const subtitle = document.getElementById("dash-subtitle");
  const charts = {};
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let scope = "market";

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const STATUS = { LOW: "#0ca30c", MODERATE: "#fab219", HIGH: "#ec835a", VERY_HIGH: "#d03b3b" };
  const LEVEL_TEXT = { LOW: "Low", MODERATE: "Moderate", HIGH: "High", VERY_HIGH: "Very high" };

  function baseOptions({ horizontal = false, money = false } = {}) {
    const ink = css("--muted") || "#6b6a66";
    const grid = css("--line") || "#e4e3dd";
    const valueAxis = {
      beginAtZero: true, grid: { color: grid }, border: { display: false },
      ticks: { color: ink, callback: (v) => (money ? fmtINR(v) : fmtNum(v)), maxTicksLimit: 6 },
    };
    const catAxis = { grid: { display: false }, border: { color: css("--line-strong") }, ticks: { color: ink, autoSkip: false } };
    return {
      responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? "y" : "x",
      animation: reducedMotion ? false : { duration: 500 },
      plugins: {
        legend: { display: false },
        tooltip: {
          padding: 10, cornerRadius: 8,
          callbacks: { label: (ctx) => ` ${money ? fmtINR(ctx.parsed[horizontal ? "x" : "y"]) : fmtNum(ctx.parsed[horizontal ? "x" : "y"])}` },
        },
      },
      scales: horizontal ? { x: valueAxis, y: catAxis } : { x: catAxis, y: valueAxis },
    };
  }

  function draw(id, labels, data, colors, opts) {
    if (typeof Chart === "undefined") return;
    charts[id]?.destroy();
    const canvas = document.getElementById(id);
    charts[id] = new Chart(canvas, {
      type: "bar",
      data: { labels, datasets: [{ data, backgroundColor: colors, borderRadius: 4, borderSkipped: false, maxBarThickness: 42 }] },
      options: baseOptions(opts),
    });
  }

  function emptyChart(id, message) {
    charts[id]?.destroy();
    const box = document.getElementById(id).parentElement;
    box.querySelector(".chart-empty")?.remove();
    if (message) box.append(el("div", { class: "empty-state chart-empty" }, message));
  }

  function setKpi(name, value) {
    const n = document.querySelector(`[data-kpi="${name}"]`);
    if (n) n.textContent = value;
  }

  async function load() {
    buttons.forEach((b) => b.classList.toggle("active", b.dataset.scope === scope));
    subtitle.textContent = scope === "market"
      ? "Reference dataset (99acres Mumbai, July 2018) and demo listings, scored by the RentalGuard risk engine."
      : "Statistics for the listings you have analyzed.";
    let s;
    try {
      s = await RG.api(`/api/dashboard/stats?scope=${scope}`);
    } catch (err) {
      RG.toast(err.message, "error");
      return;
    }
    const highCount = (s.risk_distribution.HIGH || 0) + (s.risk_distribution.VERY_HIGH || 0);
    setKpi("analyzed", fmtNum(s.listings_analyzed));
    setKpi("total", `${fmtNum(s.total_listings)} listings in scope`);
    setKpi("avg_rent", fmtINR(s.average_rent));
    setKpi("median_rent", s.median_rent ? `Median ${fmtINR(s.median_rent)}` : "");
    setKpi("avg_score", s.average_risk_score ?? "—");
    setKpi("high", fmtNum(highCount));
    setKpi("high_share", s.listings_analyzed ? `${(() => { const pct = (highCount / s.listings_analyzed) * 100; return pct > 0 && pct < 0.1 ? "<0.1" : pct.toFixed(1); })()}% of analyzed` : "");

    const blue = css("--brand") || "#2a78d6";
    const levels = ["LOW", "MODERATE", "HIGH", "VERY_HIGH"];   // fixed order, never rely on key order
    ["chart-risk", "chart-indicators", "chart-locality", "chart-bhk"].forEach((id) => emptyChart(id, null));

    if (!s.listings_analyzed) {
      emptyChart("chart-risk", "No analyzed listings yet.");
      emptyChart("chart-indicators", "No indicators yet.");
    } else {
      draw("chart-risk", levels.map((l) => LEVEL_TEXT[l]), levels.map((l) => s.risk_distribution[l]), levels.map((l) => STATUS[l]));
      if (s.top_indicators.length) {
        draw("chart-indicators", s.top_indicators.map((i) => i.label), s.top_indicators.map((i) => i.count), blue, { horizontal: true });
      } else {
        emptyChart("chart-indicators", "No risk indicators triggered.");
      }
    }
    if (s.rent_by_locality.length) {
      draw("chart-locality", s.rent_by_locality.map((r) => `${r.locality} (${r.count})`), s.rent_by_locality.map((r) => r.avg_rent), blue,
        { horizontal: true, money: true });
    } else emptyChart("chart-locality", "No listings yet.");
    const bhkLabels = Object.keys(s.bhk_distribution);
    if (bhkLabels.length) draw("chart-bhk", bhkLabels, bhkLabels.map((k) => s.bhk_distribution[k]), blue);
    else emptyChart("chart-bhk", "No listings yet.");

    const tbody = document.getElementById("top-risk");
    tbody.replaceChildren(...(s.highest_risk.length ? s.highest_risk.map((r) => el("tr", {},
      el("td", {}, r.locality), el("td", {}, String(r.bhk)), el("td", { class: "num" }, fmtINR(r.rent)),
      el("td", { class: "num" }, String(r.risk_score)), el("td", {}, badge(r.risk_level)),
      el("td", { class: "num" }, String(r.reports)),
      el("td", {}, r.analysis_id ? el("a", { class: "btn btn-secondary btn-sm", href: `/results/${r.analysis_id}` }, "View") : "")))
      : [el("tr", {}, el("td", { colspan: "7", class: "muted" }, "No listings with a moderate or higher risk score."))]));
  }

  buttons.forEach((b) => b.addEventListener("click", () => {
    if (b.disabled || b.dataset.scope === scope) return;
    scope = b.dataset.scope;
    load();
  }));
  if (typeof Chart === "undefined") RG.toast("Charts could not be loaded (offline?). Statistics are still shown.", "error");
  load();
})();
