// sito: small progressive enhancements. Every page works without this file.
(() => {
  const root = document.documentElement;
  const prefersDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

  // Theme toggle (remembered per browser).
  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-theme-toggle]");
    if (!toggle) return;
    const current = root.dataset.theme || (prefersDark() ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("sito-theme", next); } catch (_) { /* private mode */ }
  });

  // Close open <details class="menu"> when clicking elsewhere or pressing Escape.
  document.addEventListener("click", (event) => {
    document.querySelectorAll("details.menu[open]").forEach((menu) => {
      if (!menu.contains(event.target)) menu.removeAttribute("open");
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll("details.menu[open]").forEach((menu) => {
      menu.removeAttribute("open");
      menu.querySelector("summary")?.focus();
    });
  });

  // Row selection for bulk actions: checkboxes named "ids" inside a form with [data-bulk].
  const updateBulk = (form) => {
    if (!form) return;
    const checked = form.querySelectorAll('input[name="ids"]:checked').length;
    const bar = form.querySelector("[data-bulkbar]");
    if (bar) {
      bar.hidden = checked === 0;
      const count = bar.querySelector("[data-count]");
      if (count) count.textContent = checked.toLocaleString();
    }
    const all = form.querySelector("[data-select-all]");
    if (all) {
      const boxes = form.querySelectorAll('input[name="ids"]').length;
      all.checked = boxes > 0 && checked === boxes;
      all.indeterminate = checked > 0 && checked < boxes;
    }
  };
  document.addEventListener("change", (event) => {
    const target = event.target;
    if (target.matches("[data-select-all]")) {
      target.form?.querySelectorAll('input[name="ids"]').forEach((box) => {
        box.checked = target.checked;
        box.closest("tr")?.classList.toggle("is-selected", box.checked);
      });
      updateBulk(target.form);
    } else if (target.matches('input[name="ids"]')) {
      target.closest("tr")?.classList.toggle("is-selected", target.checked);
      updateBulk(target.form);
    } else if (target.matches("[data-autosubmit]")) {
      target.form?.requestSubmit();
    }
  });

  // Native confirmation for destructive forms: <form data-confirm="..."> or <button data-confirm>.
  document.addEventListener("submit", (event) => {
    const message = event.submitter?.dataset.confirm || event.target.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  }, true);

  // Scroll an opened editor/picker into view.
  window.addEventListener("DOMContentLoaded", () => {
    document.querySelector(".tray.is-editing, .picker")?.scrollIntoView({ block: "nearest" });
  });
})();
