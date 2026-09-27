"use strict";
(() => {
  const section = document.getElementById("result-section");
  const subtitle = document.getElementById("result-subtitle");
  const dialog = document.getElementById("report-dialog");
  const reportForm = document.getElementById("report-form");
  const id = Number(section?.dataset.analysisId);
  if (!id) return;
  let current = null;

  async function load() {
    try {
      const { analysis } = await RG.api(`/api/analysis/${id}`);
      show(analysis);
    } catch (err) {
      subtitle.textContent = "";
      const msg = err.status === 404 ? "This assessment does not exist or you do not have access to it."
        : err.message;
      section.replaceChildren(RG.el("div", { class: "card empty-state" },
        RG.el("h3", {}, "Assessment unavailable"), RG.el("p", {}, msg),
        RG.isLoggedIn() ? null : RG.el("a", { class: "btn btn-primary", href: `/login?next=/results/${id}` }, "Log in")));
    }
  }

  function show(analysis) {
    current = analysis;
    const when = new Date(analysis.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
    subtitle.textContent = `Assessment #${analysis.id} · ${when}`;
    const handlers = {};
    if (RG.isLoggedIn()) {
      handlers.onReport = () => { RG.clearErrors(reportForm); dialog.showModal(); };
      handlers.onReanalyze = async () => {
        try {
          const res = await RG.api("/api/analyze", { method: "POST", body: { listing_id: analysis.listing_id } });
          window.location.assign(`/results/${res.analysis.id}`);
        } catch (err) { RG.toast(err.message, "error"); }
      };
    }
    RGResult.render(section, analysis, handlers);
  }

  document.getElementById("report-cancel")?.addEventListener("click", () => dialog.close());
  reportForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    RG.clearErrors(reportForm);
    const values = RG.formValues(reportForm);
    const btn = reportForm.querySelector("button[type=submit]");
    RG.setBusy(btn, true, "Sending…");
    try {
      await RG.api("/api/reports", { method: "POST", body: { listing_id: current.listing_id, ...values } });
      dialog.close();
      RG.toast("Thank you - your report was recorded.");
    } catch (err) {
      RG.showErrors(reportForm, err);
    } finally {
      RG.setBusy(btn, false);
    }
  });

  load();
})();
