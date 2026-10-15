(() => {
  const container = document.getElementById("swatches");
  const status = document.getElementById("status");
  const buttons = new Map();
  let colors = [];
  let selectedCodes = new Set();
  let pendingSelection = null;

  const post = (type, extra = {}) => window.parent.postMessage({
    isStreamlitMessage: true,
    type,
    ...extra,
  }, "*");

  function orderedSelection() {
    return colors.filter((color) => selectedCodes.has(color.code)).map((color) => color.code);
  }

  function sameSelection(left, right) {
    const a = new Set(left);
    const b = new Set(right);
    return a.size === b.size && [...a].every((code) => b.has(code));
  }

  function syncButton(button, color) {
    const selected = selectedCodes.has(color.code);
    button.dataset.code = color.code;
    button.style.setProperty("background-color", selected ? color.hex : "#0e1117", "important");
    button.title = `Bambu Lab: ${color.name} (${color.code} · ${color.hex})`;
    button.setAttribute("aria-label", `${color.name}, ${color.code}, ${color.hex}`);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  }

  function copyHex(hex) {
    if (!navigator.clipboard?.writeText) return;
    navigator.clipboard.writeText(hex).catch(() => {
      // Clipboard permission is optional; it must never block selection.
    });
  }

  function toggleColor(code) {
    const color = colors.find((item) => item.code === code);
    if (!color) return;

    if (selectedCodes.has(code)) selectedCodes.delete(code);
    else selectedCodes.add(code);

    for (const item of colors) syncButton(buttons.get(item.code), item);
    const value = orderedSelection();
    pendingSelection = value;
    status.textContent = `${color.name} ${selectedCodes.has(code) ? "selected" : "removed"}; ${color.hex} copied`;
    copyHex(color.hex);
    post("streamlit:setComponentValue", { value, dataType: "json" });
  }

  function render(args) {
    colors = Array.isArray(args.colors) ? args.colors : [];
    const incomingSelection = Array.isArray(args.selected_codes) ? args.selected_codes : [];
    if (pendingSelection && sameSelection(incomingSelection, pendingSelection)) {
      pendingSelection = null;
      selectedCodes = new Set(incomingSelection);
    } else if (pendingSelection) {
      // Keep the immediate click state while Streamlit sends the updated value back.
      selectedCodes = new Set(pendingSelection);
    } else {
      selectedCodes = new Set(incomingSelection);
    }
    const currentCodes = new Set(colors.map((color) => color.code));

    for (const [code, button] of buttons) {
      if (!currentCodes.has(code)) {
        button.remove();
        buttons.delete(code);
      }
    }

    for (const color of colors) {
      let button = buttons.get(color.code);
      if (!button) {
        button = document.createElement("button");
        button.type = "button";
        button.className = "swatch";
        button.addEventListener("click", () => toggleColor(button.dataset.code));
        buttons.set(color.code, button);
        container.appendChild(button);
      }
      syncButton(button, color);
    }
    post("streamlit:setFrameHeight", { height: 44 });
  }

  window.addEventListener("message", (event) => {
    if (event.data?.type === "streamlit:render") render(event.data.args || {});
  });

  post("streamlit:componentReady", { apiVersion: 1 });
  post("streamlit:setFrameHeight", { height: 44 });
})();
