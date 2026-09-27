/* RentalGuard shared front-end utilities (vanilla JS, no framework).
 * Security note: all dynamic content is inserted with textContent / DOM nodes,
 * never innerHTML, so listing text can never inject markup. */
"use strict";

const RG = (() => {
  class ApiError extends Error {
    constructor(status, data) {
      super((data && data.message) || `Request failed (${status})`);
      this.status = status;
      this.data = data || {};
    }
  }

  async function api(path, { method = "GET", body } = {}) {
    const opts = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let resp;
    try {
      resp = await fetch(path, opts);
    } catch (err) {
      throw new ApiError(0, { message: "Network error - check your connection and try again." });
    }
    let data = null;
    try { data = await resp.json(); } catch (_) { /* non-JSON body */ }
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data;
  }

  const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
  const num = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
  const fmtINR = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : inr.format(v));
  const fmtNum = (v) => (v === null || v === undefined ? "—" : num.format(v));
  const fmtPct = (v, digits = 0) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`);

  const LEVEL_LABELS = { LOW: "Low risk", MODERATE: "Moderate risk", HIGH: "High risk", VERY_HIGH: "Very high risk" };
  const levelLabel = (l) => LEVEL_LABELS[l] || "Not analyzed";

  /** Tiny hyperscript helper: el("div", {class: "x"}, "text", childNode) */
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "dataset") Object.assign(node.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  function badge(level) {
    return el("span", { class: `badge lvl-${level || "none"}` }, levelLabel(level));
  }

  function toast(message, type = "info", ms = 3800) {
    const host = document.getElementById("toast-host");
    if (!host) return;
    const t = el("div", { class: `toast ${type === "error" ? "error" : ""}`, role: "status" }, message);
    host.append(t);
    setTimeout(() => t.remove(), ms);
  }

  function clearErrors(form) {
    form.querySelectorAll("[data-error-for]").forEach((n) => (n.textContent = ""));
    form.querySelectorAll(".field.invalid").forEach((n) => n.classList.remove("invalid"));
    const alert = form.querySelector("[data-form-alert]");
    if (alert) { alert.textContent = ""; alert.classList.add("hidden"); }
  }

  function showErrors(form, err) {
    const fields = (err.data && err.data.fields) || {};
    let placed = false;
    for (const [name, msg] of Object.entries(fields)) {
      const slot = form.querySelector(`[data-error-for="${CSS.escape(name)}"]`);
      if (slot) {
        slot.textContent = msg;
        slot.closest(".field")?.classList.add("invalid");
        placed = true;
      }
    }
    const alert = form.querySelector("[data-form-alert]");
    if (alert && (!placed || fields._body)) {
      alert.textContent = fields._body || err.message;
      alert.classList.remove("hidden");
    }
    const first = form.querySelector(".field.invalid input, .field.invalid select, .field.invalid textarea");
    if (first) first.focus();
  }

  function setBusy(button, busy, busyText = "Working…") {
    if (!button) return;
    if (busy) {
      button.dataset.label = button.textContent;
      button.disabled = true;
      button.replaceChildren(el("span", { class: "spinner" }), busyText);
    } else {
      button.disabled = false;
      button.textContent = button.dataset.label || button.textContent;
    }
  }

  /** Read form fields into an object; empty strings become null. */
  function formValues(form) {
    const out = {};
    for (const [k, v] of new FormData(form).entries()) {
      const s = String(v).trim();
      out[k] = s === "" ? null : s;
    }
    return out;
  }

  function debounce(fn, ms = 250) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }

  // ---- global UI wiring -------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.querySelector(".nav-toggle");
    const links = document.getElementById("nav-links");
    if (toggle && links) {
      toggle.addEventListener("click", () => {
        const open = links.classList.toggle("open");
        toggle.setAttribute("aria-expanded", String(open));
      });
    }
    const logout = document.getElementById("logout-btn");
    if (logout) {
      logout.addEventListener("click", async () => {
        try { await api("/api/auth/logout", { method: "POST", body: {} }); } catch (_) { /* ignore */ }
        window.location.assign("/");
      });
    }
  });

  return { api, ApiError, el, badge, toast, fmtINR, fmtNum, fmtPct, levelLabel, clearErrors, showErrors,
           setBusy, formValues, debounce, isLoggedIn: () => document.body.dataset.authenticated === "true" };
})();
