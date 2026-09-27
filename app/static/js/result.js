/* Renders a risk assessment. Shared by analyze.js (inline) and result_page.js (permalink). */
"use strict";

const RGResult = (() => {
  const { el, fmtINR, fmtNum, badge } = RG;
  const SVG = "http://www.w3.org/2000/svg";
  const CATEGORY_NAMES = {
    price: "Price", deposit: "Deposit", text: "Text", duplicate: "Duplicates", contact: "Contact",
    ml: "ML model", community: "Reports", completeness: "Completeness", general: "Other",
  };
  const ICONS = {
    warn: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
    check: "M20 6 9 17l-5-5",
    chart: "M3 3v18h18M7 15l4-4 3 3 5-6",
    text: "M4 6h16M4 12h10M4 18h7",
    copy: "M8 8h12v12H8zM16 8V4H4v12h4",
    user: "M12 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8ZM4 21a8 8 0 0 1 16 0",
    coin: "M12 2v4M12 18v4M2 12h4M18 12h4M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10Z",
    cpu: "M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3M6 6h12v12H6z",
  };

  function icon(name) {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const p = document.createElementNS(SVG, "path");
    p.setAttribute("d", ICONS[name] || ICONS.warn);
    svg.append(p);
    return svg;
  }

  function gauge(score, level, size = "") {
    const r = 52, c = 2 * Math.PI * r;
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 120 120");
    svg.setAttribute("aria-hidden", "true");
    const track = document.createElementNS(SVG, "circle");
    const val = document.createElementNS(SVG, "circle");
    for (const circle of [track, val]) {
      circle.setAttribute("cx", "60"); circle.setAttribute("cy", "60"); circle.setAttribute("r", String(r));
      circle.setAttribute("fill", "none"); circle.setAttribute("stroke-width", "12");
    }
    track.setAttribute("class", "track");
    val.setAttribute("class", `value stroke-${level}`);
    val.setAttribute("stroke-dasharray", c.toFixed(1));
    val.setAttribute("stroke-dashoffset", c.toFixed(1));
    svg.append(track, val);
    requestAnimationFrame(() => requestAnimationFrame(() =>
      val.setAttribute("stroke-dashoffset", (c * (1 - score / 100)).toFixed(1))));
    return el("div", { class: `gauge ${size}`, role: "img", "aria-label": `Risk score ${score} out of 100` },
      svg, el("div", { class: "label" }, el("div", {}, el("strong", {}, String(score)), el("span", {}, "/ 100"))));
  }

  function card(title, iconName, ...body) {
    return el("section", { class: "card" },
      el("div", { class: "card-head" }, el("div", { class: "card-title" },
        el("div", { class: "card-icon" }, icon(iconName)), el("h3", {}, title))),
      ...body);
  }

  function kv(pairs) {
    const dl = el("dl", { class: "kv" });
    for (const [k, v] of pairs) {
      if (v === undefined) continue;
      dl.append(el("dt", {}, k), el("dd", {}, v === null ? "—" : v));
    }
    return dl;
  }

  const levelChip = (text, level) => el("span", { class: `badge plain lvl-${level}` }, text);
  const PRICE_LEVEL = { HIGH: "VERY_HIGH", MODERATE: "MODERATE", NORMAL: "LOW", ABOVE_MARKET: "none", UNKNOWN: "none" };
  const PRICE_TEXT = { HIGH: "High anomaly", MODERATE: "Moderate anomaly", NORMAL: "Normal",
                       ABOVE_MARKET: "Above market", UNKNOWN: "Unavailable" };

  // ------------------------------------------------------------------
  function scoreSection(analysis, handlers) {
    const r = analysis.result;
    const L = analysis.listing || {};
    const meta = el("div", { class: "score-meta" },
      L.locality ? el("span", { class: "chip" }, L.locality) : null,
      L.bhk ? el("span", { class: "chip" }, `${L.bhk} BHK`) : null,
      L.rent ? el("span", { class: "chip" }, `${fmtINR(L.rent)}/month`) : null,
      L.source === "dataset" ? el("span", { class: "chip" }, "Reference dataset (2018)") : null,
      L.source === "demo" ? el("span", { class: "chip" }, "Synthetic demo listing") : null,
    );
    const actions = el("div", { class: "row score-actions" });
    if (handlers.onReanalyze) actions.append(el("button", { class: "btn btn-secondary btn-sm", type: "button", onclick: handlers.onReanalyze }, "Re-run analysis"));
    if (handlers.onReport) actions.append(el("button", { class: "btn btn-danger btn-sm", type: "button", onclick: handlers.onReport }, "Report listing"));
    if (handlers.permalink) actions.append(el("a", { class: "btn btn-ghost btn-sm", href: handlers.permalink }, "Open permalink"));

    return el("section", { class: "card" },
      el("div", { class: "score-card" },
        gauge(r.risk_score, r.risk_level),
        el("div", { class: "summary" },
          el("div", { class: "row" }, badge(r.risk_level), el("span", { class: "small muted" }, "Risk assessment")),
          el("p", {}, r.summary), meta, actions)),
      breakdown(r),
      el("p", { class: "disclaimer" }, r.disclaimer));
  }

  function breakdown(r) {
    const byCat = {};
    for (const c of r.contributions) byCat[c.category] = (byCat[c.category] || 0) + c.points;
    const total = Object.values(byCat).reduce((a, b) => a + b, 0);
    if (!total) return el("div");
    const bar = el("div", { class: "breakdown", role: "img", "aria-label": "Score breakdown by category" });
    const legend = el("div", { class: "legend" });
    for (const [cat, pts] of Object.entries(byCat).sort((a, b) => b[1] - a[1])) {
      const seg = el("span", { class: `seg-${cat}`, title: `${CATEGORY_NAMES[cat] || cat}: ${pts} pts` });
      seg.style.width = `${(pts / Math.max(total, 100)) * 100}%`;
      bar.append(seg);
      legend.append(el("span", {}, el("i", { class: `seg-${cat} breakdown-key` }), `${CATEGORY_NAMES[cat] || cat} +${pts}`));
    }
    const note = r.rule_points_capped ? el("span", { class: "small muted" }, " (rule points capped at 80)") : null;
    return el("div", {}, el("div", { class: "small muted" }, "Score breakdown", note), bar, legend);
  }

  function indicatorsSection(r) {
    const list = el("ul", { class: "indicator-list" });
    for (const c of r.contributions) {
      list.append(el("li", { class: `indicator cat-${c.category}` },
        el("div", { class: "ico" }, icon(c.category === "ml" ? "cpu" : "warn")),
        el("div", {},
          el("h4", {}, c.label),
          el("p", {}, c.explanation),
          c.evidence && c.evidence.length ? el("div", { class: "evidence" }, c.evidence.map((e) => el("span", {}, e))) : null),
        el("div", { class: "points" }, `+${c.points}`)));
    }
    const body = r.contributions.length ? list : el("div", { class: "empty-indicators" }, icon("check"),
      "No risk indicators were detected. Standard precautions still apply.");
    return card("Risk indicators", "warn", body);
  }

  function priceSection(p) {
    if (!p.available) return card("Price analysis", "chart", el("p", { class: "muted" }, p.explanation));
    const [lo, hi] = p.expected_range;
    const min = Math.min(p.actual_rent, lo) * 0.8, max = Math.max(p.actual_rent, hi) * 1.15;
    const pos = (v) => `${Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100))}%`;
    const band = el("div", { class: "band" });
    band.style.left = pos(lo); band.style.width = `calc(${pos(hi)} - ${pos(lo)})`;
    const marker = el("div", { class: "marker", title: "Listed rent" });
    marker.style.left = pos(p.actual_rent);
    const mlabel = el("div", { class: "marker-label" }, `Listed ${fmtINR(p.actual_rent)}`);
    mlabel.style.left = pos(p.actual_rent);
    const blabel = el("div", { class: "band-label" }, "Comparable range");
    blabel.style.left = `calc((${pos(lo)} + ${pos(hi)}) / 2)`;
    const dev = p.deviation_percent;
    return card("Price analysis", "chart",
      el("div", { class: "row-between" },
        el("div", {}, el("div", { class: "small muted" }, "Estimated comparable rent"),
          el("div", { class: "big-number" }, `${fmtINR(lo)} – ${fmtINR(hi)}`)),
        levelChip(PRICE_TEXT[p.anomaly_level] || p.anomaly_level, PRICE_LEVEL[p.anomaly_level] || "none")),
      el("div", { class: "range-bar" }, band, marker, mlabel, blabel),
      kv([["Listed rent", fmtINR(p.actual_rent)], ["Expected rent", fmtINR(p.expected_rent)],
          ["Difference", dev >= 0 ? `${dev.toFixed(0)}% below expected` : `${Math.abs(dev).toFixed(0)}% above expected`],
          ["Robust z-score", p.z_score.toFixed(2)],
          ["Peer group", `${p.peer_group.bhk} BHK · ${p.peer_group.name} (n=${fmtNum(p.peer_group.count)})`],
          ["Peer estimate", fmtINR(p.peer_estimate)],
          ["ML model estimate", p.model_estimate ? fmtINR(p.model_estimate) : "not used"]]),
      el("div", { class: "explain" }, p.explanation),
      el("div", { class: "method" }, p.method, ". Reference prices are from July 2018."));
  }

  function depositSection(d) {
    const lvl = { HIGH: "VERY_HIGH", ELEVATED: "MODERATE", NORMAL: "LOW", LOW: "none", NOT_PROVIDED: "none" }[d.level] || "none";
    const txt = { HIGH: "Unusually high", ELEVATED: "Above typical", NORMAL: "Typical", LOW: "Below typical", NOT_PROVIDED: "Not provided" }[d.level] || d.level;
    return card("Deposit analysis", "coin",
      el("div", { class: "row-between" },
        el("div", { class: "big-number" }, d.available ? `${Number(d.ratio).toFixed(1)}× rent` : "—"), levelChip(txt, lvl)),
      d.available ? kv([["Deposit", fmtINR(d.deposit)], ["Typical ratio", `${Number(d.peer_median_ratio).toFixed(1)}× (${d.scope})`],
                        ["95th percentile", `${Number(d.peer_p95_ratio).toFixed(1)}×`]]) : null,
      el("div", { class: "explain" }, d.explanation));
  }

  function textSection(t) {
    const cats = Object.entries(t.category_labels || {});
    const tags = el("div", { class: "tag-list" }, cats.length ? cats.map(([, label]) => el("span", { class: "badge plain lvl-HIGH" }, label))
      : el("span", { class: "badge plain lvl-LOW" }, "No risky patterns matched"));
    return card("Text analysis", "text", tags,
      kv([["Words analyzed", fmtNum(t.word_count)], ["Urgency score", (t.urgency_score || 0).toFixed(2)],
          ["Advance payment detected", t.advance_payment_detected ? "Yes" : "No"],
          ["No-viewing claim", t.no_viewing_detected ? "Yes" : "No"],
          ["Owner abroad claim", t.owner_abroad_detected ? "Yes" : "No"],
          ["TF-IDF similarity to risky patterns", `${Math.round((t.semantic_risk_similarity || 0) * 100)}%`]]),
      t.semantic_match ? el("div", { class: "explain" }, `Closest known risky pattern: “${t.semantic_match.closest_pattern}”`) : null,
      !t.available ? el("div", { class: "explain" }, "No description was provided, so text analysis was limited.") : null);
  }

  function duplicateSection(d) {
    const lvl = { POSSIBLE_DUPLICATE: d.conflicting_duplicate ? "VERY_HIGH" : "MODERATE", SIMILAR: "none", UNIQUE: "LOW" }[d.level] || "none";
    const txt = { POSSIBLE_DUPLICATE: "Possible duplicate", SIMILAR: "Similar wording", UNIQUE: "No close match", NOT_APPLICABLE: "Not applicable" }[d.level] || d.level;
    let table = null;
    if (d.matches && d.matches.length) {
      const rows = d.matches.map((m) => el("tr", {},
        el("td", {}, m.private ? "Another user's private listing" : (m.locality || "—")),
        el("td", { class: "num" }, `${Math.round(m.similarity * 100)}%`),
        el("td", { class: "num" }, m.rent ? fmtINR(m.rent) : "—"),
        el("td", {}, m.source === "dataset" ? "Reference data" : m.source === "demo" ? "Demo" : "User")));
      table = el("div", { class: "table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Matching listing"), el("th", { class: "num" }, "Similarity"),
          el("th", { class: "num" }, "Rent"), el("th", {}, "Source"))), el("tbody", {}, rows)));
    }
    return card("Duplicate analysis", "copy",
      el("div", { class: "row-between" },
        el("div", { class: "big-number" }, `${Math.round((d.max_similarity || 0) * 100)}%`), levelChip(txt, lvl)),
      el("div", { class: "explain" }, d.explanation), table ? el("div", { class: "section-gap-sm" }, table) : null);
  }

  function contactSection(c) {
    const lvl = { REPORTED: "VERY_HIGH", WIDESPREAD: "MODERATE", REPEATED: "none", UNIQUE: "LOW", NOT_PROVIDED: "none" }[c.level] || "none";
    const txt = { REPORTED: "Reported", WIDESPREAD: "Widespread", REPEATED: "Repeated contact", UNIQUE: "Unique", NOT_PROVIDED: "Not provided" }[c.level] || c.level;
    return card("Contact analysis", "user",
      el("div", { class: "row-between" }, el("div", { class: "big-number" }, c.available ? fmtNum(c.listings_per_contact) : "—"), levelChip(txt, lvl)),
      c.available ? kv([["Listings with this contact", fmtNum(c.listings_per_contact)], ["Distinct localities", fmtNum(c.localities)],
                        ["User reports", fmtNum(c.reported_count)]]) : null,
      el("div", { class: "explain" }, c.explanation));
  }

  function mlSection(ml) {
    return card("Machine-learning estimate", "cpu",
      ml.available
        ? el("div", {}, el("div", { class: "big-number" }, `${Math.round(ml.risk_probability * 100)}%`),
            kv([["Model", ml.model_name], ["Points contributed", `+${ml.points} of max 20`]]),
            el("div", { class: "explain" }, "Trained on a documented synthetic dataset. The probability reflects similarity to simulated risky patterns, not a measured real-world fraud rate."))
        : el("p", { class: "muted" }, "The ML model is not loaded; the score is based on rule indicators only."));
  }

  function descriptionSection(listing, text) {
    const desc = (listing && listing.description) || "";
    if (!desc) return null;
    const box = el("div", { class: "desc-box" });
    const phrases = (text.risk_phrases || []).filter(Boolean).sort((a, b) => b.length - a.length);
    if (!phrases.length) {
      box.textContent = desc;
    } else {
      const escaped = phrases.map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
      const re = new RegExp(`(${escaped.join("|")})`, "gi");
      let last = 0;
      for (const m of desc.matchAll(re)) {
        box.append(document.createTextNode(desc.slice(last, m.index)), el("mark", {}, m[0]));
        last = m.index + m[0].length;
      }
      box.append(document.createTextNode(desc.slice(last)));
    }
    return card("Listing description", "text", box,
      el("p", { class: "method" }, "Highlighted phrases triggered text indicators. Phone numbers and e-mails in reference data are redacted."));
  }

  function render(container, analysis, handlers = {}) {
    const r = analysis.result;
    container.replaceChildren(
      scoreSection(analysis, handlers),
      el("div", { class: "grid grid-2 section-gap" },
        indicatorsSection(r), priceSection(r.price), depositSection(r.deposit), textSection(r.text),
        duplicateSection(r.duplicates), contactSection(r.contact), mlSection(r.ml),
        descriptionSection(analysis.listing, r.text)));
  }

  return { render, gauge };
})();
