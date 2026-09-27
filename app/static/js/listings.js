/* Search / filter / sort / paginate listings (History and Market pages). */
"use strict";
(() => {
  const form = document.getElementById("filters");
  const tbody = document.getElementById("listing-rows");
  const info = document.getElementById("pager-info");
  const prev = document.getElementById("prev-page");
  const next = document.getElementById("next-page");
  if (!form) return;
  const scope = form.dataset.scope;
  const { el, fmtINR, fmtNum, badge } = RG;
  let page = 1;
  let pages = 1;
  let requestSeq = 0;   // ignore out-of-order responses

  function params() {
    const p = new URLSearchParams({ scope, page: String(page), per_page: "20" });
    for (const [k, v] of Object.entries(RG.formValues(form))) {
      if (v !== null) p.set(k, k.endsWith("_rent") ? v.replace(/[,\s₹]/g, "") : v);
    }
    return p;
  }

  function row(item) {
    const link = item.latest_analysis_id
      ? el("a", { class: "btn btn-secondary btn-sm", href: `/results/${item.latest_analysis_id}` }, "View")
      : el("span", { class: "muted small" }, "—");
    return el("tr", {},
      el("td", {}, item.locality, item.source === "demo" ? el("span", { class: "chip" }, " demo") : null),
      el("td", {}, item.bhk ? `${item.bhk}` : "—"),
      el("td", { class: "num" }, fmtINR(item.rent)),
      el("td", { class: "num" }, item.area_sqft ? `${fmtNum(item.area_sqft)} sq.ft` : "—"),
      el("td", {}, item.furnishing === "unknown" ? "—" : item.furnishing),
      el("td", { class: "num" }, item.latest_risk_score ?? "—"),
      el("td", {}, item.latest_risk_level ? badge(item.latest_risk_level) : el("span", { class: "muted small" }, "Not analyzed")),
      el("td", {}, link));
  }

  async function load() {
    const seq = ++requestSeq;
    tbody.replaceChildren(el("tr", {}, el("td", { colspan: "8" },
      el("div", { class: "loading-panel" }, el("div", { class: "spinner dark" }), "Loading…"))));
    try {
      const data = await RG.api(`/api/listings?${params()}`);
      if (seq !== requestSeq) return;
      pages = data.pages;
      if (!data.items.length) {
        const filtered = Object.entries(RG.formValues(form)).some(([k, v]) => k !== "sort" && v !== null);
        const empty = scope === "mine" && !filtered
          ? el("div", { class: "empty-state" }, el("h3", {}, "No listings yet"),
              el("p", {}, "Analyze your first listing to start building your history."),
              el("a", { class: "btn btn-primary", href: "/analyze" }, "Analyze a listing"))
          : el("div", { class: "empty-state" }, el("h3", {}, "No matching listings"), el("p", {}, "Try widening your filters."));
        tbody.replaceChildren(el("tr", {}, el("td", { colspan: "8" }, empty)));
      } else {
        tbody.replaceChildren(...data.items.map(row));
      }
      info.textContent = `${fmtNum(data.total)} listing${data.total === 1 ? "" : "s"} · page ${data.page} of ${data.pages}`;
      prev.disabled = page <= 1;
      next.disabled = page >= pages;
    } catch (err) {
      if (err.status === 401) { window.location.assign(`/login?next=${location.pathname}`); return; }
      tbody.replaceChildren(el("tr", {}, el("td", { colspan: "8", class: "muted" }, err.message)));
    }
  }

  const reload = () => { page = 1; load(); };
  form.addEventListener("change", reload);
  form.addEventListener("input", RG.debounce((e) => { if (e.target.tagName === "INPUT") reload(); }, 350));
  form.addEventListener("submit", (e) => { e.preventDefault(); reload(); });
  prev.addEventListener("click", () => { if (page > 1) { page -= 1; load(); } });
  next.addEventListener("click", () => { if (page < pages) { page += 1; load(); } });
  load();
})();
