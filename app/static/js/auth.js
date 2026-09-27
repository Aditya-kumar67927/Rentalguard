"use strict";
(() => {
  const form = document.getElementById("login-form") || document.getElementById("register-form");
  if (!form) return;
  const isRegister = form.id === "register-form";

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    RG.clearErrors(form);
    const values = RG.formValues(form);
    const button = form.querySelector("button[type=submit]");
    RG.setBusy(button, true, isRegister ? "Creating account…" : "Logging in…");
    try {
      await RG.api(isRegister ? "/api/auth/register" : "/api/auth/login", { method: "POST", body: values });
      // Only same-origin relative paths are ever rendered into data-next (validated server side)
      window.location.assign(form.dataset.next || "/analyze");
    } catch (err) {
      RG.showErrors(form, err);
      RG.setBusy(button, false);
    }
  });
})();
