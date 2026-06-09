/* Bulk multi-select on the collection list. Selection state is inherently
 * client-side; this keeps the bar in sync. HTMX does the actual mutation +
 * #results swap. Listeners are delegated on document/body so they survive swaps.
 */
(function () {
  "use strict";
  var bar = document.getElementById("bulk-bar");
  if (!bar) return;

  var nEl = document.getElementById("bulk-n");
  var hint = document.getElementById("bulk-hint");
  var selectAll = document.getElementById("select-all");
  var form = document.getElementById("bulk-form");
  var actionSel = document.getElementById("bulk-action");
  var toggles = [form, document.getElementById("bulk-delete"), document.getElementById("bulk-clear")];

  function boxes() {
    return Array.prototype.slice.call(document.querySelectorAll("#results input[name=ids]"));
  }
  function checkedBoxes() {
    return boxes().filter(function (b) { return b.checked; });
  }

  function refresh() {
    var all = boxes();
    var sel = checkedBoxes();
    var any = sel.length > 0;
    nEl.textContent = sel.length;
    toggles.forEach(function (el) { if (el) el.classList.toggle("hidden", !any); });
    if (hint) hint.classList.toggle("hidden", any);
    if (selectAll) {
      selectAll.checked = all.length > 0 && sel.length === all.length;
      selectAll.indeterminate = any && sel.length < all.length;
    }
  }

  // Show only the value control matching the chosen action, and disable the
  // others so a single `value` is posted (every control shares the name).
  function syncValues() {
    if (!actionSel) return;
    var action = actionSel.value;
    form.querySelectorAll(".bulk-value").forEach(function (el) {
      var on = el.getAttribute("data-for") === action;
      el.classList.toggle("hidden", !on);
      el.querySelectorAll("input, select").forEach(function (i) { i.disabled = !on; });
    });
  }

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t.matches && t.matches("#results input[name=ids]")) {
      refresh();
    } else if (t === selectAll) {
      boxes().forEach(function (b) { b.checked = selectAll.checked; });
      refresh();
    } else if (t === actionSel) {
      syncValues();
    }
  });

  document.addEventListener("click", function (e) {
    if (e.target && e.target.id === "bulk-clear") {
      checkedBoxes().forEach(function (b) { b.checked = false; });
      refresh();
    }
  });

  // The list is replaced on filter changes and after a bulk apply — recount.
  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target && e.target.id === "results") refresh();
  });

  syncValues();
  refresh();
})();
