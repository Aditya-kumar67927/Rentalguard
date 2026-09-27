"use strict";
(() => {
  const form = document.getElementById("analyze-form");
  const output = document.getElementById("result-section");
  const button = document.getElementById("analyze-btn");
  const desc = document.getElementById("description");
  const counter = document.getElementById("char-count");
  const locality = document.getElementById("locality");
  const options = document.getElementById("locality-options");
  if (!form) return;

  // ---- Demo listings (synthetic, for demonstration only) -----------------
  const EXAMPLES = {
    normal: {
      locality: "Andheri West", rent: "35000", deposit: "150000", bhk: "2", area_sqft: "650", bathrooms: "2",
      furnishing: "semi-furnished", property_type: "apartment",
      description: "Well maintained 2 BHK semi-furnished flat in a gated society, 8 minutes walk from Andheri station. " +
        "Modular kitchen, 2 bathrooms, covered parking, lift and 24x7 security. Family preferred. " +
        "Deposit 1.5 lakh. Please call to schedule a visit on weekends.",
    },
    price: {
      locality: "Andheri West", rent: "8000", deposit: "20000", bhk: "2", area_sqft: "650", bathrooms: "2",
      furnishing: "semi-furnished", property_type: "apartment",
      description: "Well maintained 2 BHK semi-furnished flat in a gated society near Andheri station. " +
        "Modular kitchen, covered parking and 24x7 security. Family preferred.",
    },
    payment: {
      locality: "Powai", rent: "30000", deposit: "100000", bhk: "2", area_sqft: "", bathrooms: "",
      furnishing: "furnished", property_type: "apartment",
      description: "Fully furnished 2 BHK with lake view in Hiranandani. I am currently in Dubai so a physical viewing " +
        "is not possible. Send token amount before viewing to block the flat and I will courier the keys to you.",
    },
    urgency: {
      locality: "Bandra West", rent: "85000", deposit: "300000", bhk: "2", area_sqft: "900", bathrooms: "2",
      furnishing: "furnished", property_type: "apartment",
      description: "Premium 2 BHK near Carter Road. Many people are interested in this flat. Pay immediately or " +
        "the property will be given to someone else. Offer valid today only.",
    },
    duplicate: {
      locality: "Kharghar", rent: "22000", deposit: "60000", bhk: "2", area_sqft: "900", bathrooms: "2",
      furnishing: "furnished", property_type: "apartment",
      description: "Sea facing fully furnished 2 BHK apartment on a high floor with a large balcony, Italian marble " +
        "flooring, modular kitchen with chimney and hob, two air conditioners, one covered car park, gym and " +
        "swimming pool in the society, walking distance to the promenade and cafes.",
    },
  };

  document.getElementById("examples")?.addEventListener("click", (event) => {
    const key = event.target?.dataset?.example;
    if (!key) return;
    const ex = EXAMPLES[key];
    for (const [name, value] of Object.entries(ex)) {
      const field = form.elements.namedItem(name);
      if (field) field.value = value;
    }
    updateCounter();
    RG.clearErrors(form);
    RG.toast("Demo listing loaded - press “Analyze Listing”.");
  });

  // ---- Character counter ----------------------------------------------------
  const updateCounter = () => { counter.textContent = `${RG.fmtNum(desc.value.length)} / 5,000`; };
  desc.addEventListener("input", updateCounter);
  form.addEventListener("reset", () => setTimeout(() => { updateCounter(); RG.clearErrors(form); }, 0));

  // ---- Locality autocomplete (server does binary-search prefix lookup) -------
  locality.addEventListener("input", RG.debounce(async () => {
    const q = locality.value.trim();
    if (q.length < 2) return;
    try {
      const { items } = await RG.api(`/api/localities?q=${encodeURIComponent(q)}`);
      options.replaceChildren(...items.map((i) => RG.el("option", { value: i.display }, `${i.zone} · ${i.n} listings`)));
    } catch (_) { /* autocomplete is best-effort */ }
  }, 200));

  // ---- Submit ---------------------------------------------------------------
  const NUMERIC = ["rent", "deposit", "bhk", "area_sqft", "bathrooms"];

  async function submit(event) {
    event.preventDefault();
    RG.clearErrors(form);
    const values = RG.formValues(form);
    for (const k of NUMERIC) if (values[k] !== null) values[k] = values[k].replace(/[,\s₹]/g, "");
    RG.setBusy(button, true, "Analyzing…");
    output.replaceChildren(RG.el("div", { class: "card loading-panel" }, RG.el("div", { class: "spinner dark" }),
      "Running price, text, duplicate, contact and ML checks…"));
    try {
      const { analysis } = await RG.api("/api/analyze", { method: "POST", body: values });
      show(analysis);
      RG.toast("Analysis saved to your history.");
    } catch (err) {
      output.replaceChildren();
      if (err.status === 401) { window.location.assign("/login?next=/analyze"); return; }
      RG.showErrors(form, err);
    } finally {
      RG.setBusy(button, false);
    }
  }

  function show(analysis) {
    RGResult.render(output, analysis, {
      permalink: `/results/${analysis.id}`,
      onReanalyze: async () => {
        try {
          const res = await RG.api("/api/analyze", { method: "POST", body: { listing_id: analysis.listing_id } });
          show(res.analysis);
          RG.toast("Analysis re-run.");
        } catch (err) { RG.toast(err.message, "error"); }
      },
    });
    output.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  form.addEventListener("submit", submit);
  updateCounter();
})();
