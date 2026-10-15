(() => {
  const container = document.getElementById("swatches");
  const status = document.getElementById("status");
  const buttons = new Map();
  let colors = [];
  let selectedCodes = new Set();

  const post = (type, extra = {}) => window.parent.postMessage({
    isStreamlitMessage: true,
    type,
    ...extra,
  }, "*");

  function orderedSelection() {
    return colors.filter((color) => selectedCodes.has(color.code)).map((color) => color.code);
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
    status.textContent = `${color.name} ${selectedCodes.has(code) ? "selected" : "removed"}; ${color.hex} copied`;
    copyHex(color.hex);
    post("streamlit:setComponentValue", { value, dataType: "json" });
  }

  function render(args) {
    colors = Array.isArray(args.colors) ? args.colors : [];
    selectedCodes = new Set(Array.isArray(args.selected_codes) ? args.selected_codes : []);
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
