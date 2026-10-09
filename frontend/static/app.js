// Destination editor: one row per target (a number or a group). Groups are
// chosen by name from a selector populated with the WhatsApp groups. Rows are
// serialized back into the hidden `whatsapp_destination` field (newline-joined)
// so the backend storage format is unchanged.
(function () {
  "use strict";

  const list = document.getElementById("dest-list");
  const hidden = document.getElementById("dest-hidden");
  const addBtn = document.getElementById("dest-add");
  if (!list || !hidden || !addBtn) return;

  const readJSON = (id, fallback) => {
    const el = document.getElementById(id);
    if (!el) return fallback;
    try { return JSON.parse(el.textContent) || fallback; } catch (e) { return fallback; }
  };

  const groups = readJSON("wa-groups", []);      // [{id, name}]
  const targets = readJSON("wa-targets", []);     // ["55...", "123@g.us", ...]
  const groupById = new Map(groups.map((g) => [g.id, g.name]));
  const isGroupId = (v) => typeof v === "string" && v.endsWith("@g.us");

  function groupOptions(selected) {
    let html = '<option value="">— escolher grupo —</option>';
    let found = false;
    for (const g of groups) {
      const sel = g.id === selected ? " selected" : "";
      if (sel) found = true;
      html += `<option value="${escapeHtml(g.id)}"${sel}>${escapeHtml(g.name)}</option>`;
    }
    // Keep an unknown/previously-saved group id selectable even if not listed.
    if (selected && !found) {
      const label = groupById.get(selected) || selected;
      html += `<option value="${escapeHtml(selected)}" selected>${escapeHtml(label)}</option>`;
    }
    return html;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function makeRow(type, value) {
    const row = document.createElement("div");
    row.className = "dest-row";
    row.innerHTML = `
      <select class="dest-type" aria-label="Tipo de destino">
        <option value="number"${type === "number" ? " selected" : ""}>Número</option>
        <option value="group"${type === "group" ? " selected" : ""}>Grupo</option>
      </select>
      <input class="dest-number" type="text" inputmode="numeric"
             placeholder="55XXXXXXXXXXX" value="${type === "number" ? escapeHtml(value) : ""}"
             ${type === "group" ? "hidden" : ""}>
      <select class="dest-group" ${type === "number" ? "hidden" : ""}>${groupOptions(type === "group" ? value : "")}</select>
      <button type="button" class="dest-del" aria-label="Remover" title="Remover">×</button>
    `;

    const typeSel = row.querySelector(".dest-type");
    const numInput = row.querySelector(".dest-number");
    const grpSel = row.querySelector(".dest-group");

    typeSel.addEventListener("change", () => {
      const isGroup = typeSel.value === "group";
      numInput.hidden = isGroup;
      grpSel.hidden = !isGroup;
      sync();
    });
    numInput.addEventListener("input", sync);
    grpSel.addEventListener("change", sync);
    row.querySelector(".dest-del").addEventListener("click", () => { row.remove(); sync(); });

    return row;
  }

  function sync() {
    const out = [];
    for (const row of list.querySelectorAll(".dest-row")) {
      const type = row.querySelector(".dest-type").value;
      const val = type === "group"
        ? row.querySelector(".dest-group").value.trim()
        : row.querySelector(".dest-number").value.trim();
      if (val) out.push(val);
    }
    hidden.value = out.join("\n");
  }

  // Build initial rows from saved targets (infer type from the value shape).
  if (targets.length) {
    for (const t of targets) list.appendChild(makeRow(isGroupId(t) ? "group" : "number", t));
  } else {
    list.appendChild(makeRow("number", ""));
  }
  sync();

  addBtn.addEventListener("click", () => { list.appendChild(makeRow("number", "")); sync(); });

  // Safety: make sure the hidden field is current before any form submit.
  const form = hidden.closest("form");
  if (form) form.addEventListener("submit", sync);
})();
