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
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(hex).catch(() => fallbackCopy(hex));
    } else {
      fallbackCopy(hex);
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
        copyHex(color.hex);
        status.textContent = `${color.name} ${next.has(color.code) ? "selected" : "removed"}; ${color.hex} copied`;
        sendValue(ordered);
      });
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
