(() => {
  const swatches = document.getElementById("swatches");
  const status = document.getElementById("status");
  let lastArgs = null;

  const post = (type, extra = {}) => window.parent.postMessage({
    isStreamlitMessage: true,
    type,
    ...extra,
  }, "*");

  function sendValue(selectedCodes) {
    post("streamlit:setComponentValue", {
      value: selectedCodes,
      dataType: "json",
    });
  }

  function copyHex(hex) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(hex).catch(() => {});
      }
    } catch (_) {
      // Clipboard access may be blocked in embedded browsers; selection still works.
    }
  }

  function fallbackCopy(hex) {
    const field = document.createElement("textarea");
    field.value = hex;
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    document.execCommand("copy");
    field.remove();
  }

  function render(args) {
    lastArgs = args;
    const selected = new Set(args.selected_codes || []);
    swatches.replaceChildren();

    (args.colors || []).forEach((color) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "swatch";
      const isSelected = selected.has(color.code);
      button.style.setProperty("background-color", isSelected ? color.hex : "#0e1117", "important");
      button.title = `Bambu Lab: ${color.name} (${color.code} · ${color.hex})`;
      button.setAttribute("aria-label", `${color.name}, ${color.code}, ${color.hex}`);
      button.setAttribute("aria-pressed", isSelected ? "true" : "false");
      button.addEventListener("click", () => {
        const next = new Set(lastArgs.selected_codes || []);
        if (next.has(color.code)) next.delete(color.code);
        else next.add(color.code);
        const ordered = (lastArgs.colors || [])
          .map((entry) => entry.code)
          .filter((code) => next.has(code));
        // Update locally at click time so the swatch responds immediately,
        // without waiting for Streamlit's round-trip and rerender.
        lastArgs.selected_codes = ordered;
        for (const swatch of swatches.children) {
          const entry = lastArgs.colors.find((item) => item.code === swatch.dataset.code);
          const selectedNow = next.has(swatch.dataset.code);
          swatch.setAttribute("aria-pressed", selectedNow ? "true" : "false");
          swatch.style.setProperty(
            "background-color",
            selectedNow ? entry.hex : "#0e1117",
            "important",
          );
        }
        copyHex(color.hex);
        status.textContent = `${color.name} ${next.has(color.code) ? "selected" : "removed"}; ${color.hex} copied`;
        sendValue(ordered);
      });
      button.dataset.code = color.code;
      swatches.appendChild(button);
    });
    post("streamlit:setFrameHeight", { height: 40 });
  }

  window.addEventListener("message", (event) => {
    if (event.data && event.data.type === "streamlit:render") {
      render(event.data.args || {});
    }
  });

  post("streamlit:componentReady", { apiVersion: 1 });
  post("streamlit:setFrameHeight", { height: 40 });
})();
