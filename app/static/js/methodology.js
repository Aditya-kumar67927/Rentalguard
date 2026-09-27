"use strict";
(async () => {
  const box = document.getElementById("model-info");
  const gen = document.getElementById("model-generated");
  if (!box) return;
  const { el, fmtINR, fmtPct } = RG;
  try {
    const info = await RG.api("/api/model/info");
    if (!info.price_model && !info.risk_model) {
      box.replaceChildren(el("p", { class: "muted" }, "No trained models found. Run: python -m app.ml.train"));
      return;
    }
    gen.textContent = info.generated_at ? `trained ${new Date(info.generated_at).toLocaleDateString("en-IN")}` : "";
    const rows = [];
    if (info.price_model?.test) {
      const t = info.price_model.test, b = info.price_baseline || {};
      rows.push(el("h4", {}, `Price model: ${info.price_model.selected.replaceAll("_", " ")}`),
        el("dl", { class: "kv" },
          el("dt", {}, "Median abs. % error (test)"), el("dd", {}, `${fmtPct(t.median_ape, 1)} (baseline ${fmtPct(b.median_ape, 1)})`),
          el("dt", {}, "Mean abs. error (test)"), el("dd", {}, `${fmtINR(t.mae_rupees)} (baseline ${fmtINR(b.mae_rupees)})`),
          el("dt", {}, "Within ±20% of actual"), el("dd", {}, fmtPct(t.within_20pct, 1)),
          el("dt", {}, "R² on log rent"), el("dd", {}, t.r2_log.toFixed(3))));
    }
    if (info.risk_model?.test) {
      const t = info.risk_model.test, b = info.risk_rule_baseline || {};
      rows.push(el("h4", { class: "section-gap-sm" }, `Risk model: ${info.risk_model.selected.replaceAll("_", " ")}`),
        el("dl", { class: "kv" },
          el("dt", {}, "Precision / recall (test)"), el("dd", {}, `${t.precision.toFixed(2)} / ${t.recall.toFixed(2)}`),
          el("dt", {}, "F1"), el("dd", {}, `${t.f1.toFixed(2)} (rules only ${b.f1?.toFixed(2) ?? "—"})`),
          el("dt", {}, "ROC-AUC"), el("dd", {}, t.roc_auc.toFixed(3)),
          el("dt", {}, "PR-AUC"), el("dd", {}, `${t.pr_auc.toFixed(3)} (rules only ${b.pr_auc?.toFixed(3) ?? "—"})`)),
        el("p", { class: "method" }, `Labels: ${info.label_source}. These metrics measure agreement with a simulation, not real-world accuracy.`));
    }
    box.replaceChildren(...rows);
  } catch (err) {
    box.replaceChildren(el("p", { class: "muted" }, err.message));
  }
})();
