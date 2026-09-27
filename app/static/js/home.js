"use strict";
(async () => {
  const slot = document.querySelector('[data-stat="total"]');
  if (!slot) return;
  try {
    const stats = await RG.api("/api/dashboard/stats?scope=market");
    slot.textContent = RG.fmtNum(stats.total_listings);
  } catch (_) {
    slot.textContent = "9,000+";
  }
})();
