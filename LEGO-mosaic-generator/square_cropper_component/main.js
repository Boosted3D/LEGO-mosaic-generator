(() => {
  const image = document.getElementById("photo");
  const stage = document.getElementById("stage");
  const frame = document.getElementById("crop-frame");
  const handle = document.getElementById("resize-handle");
  const status = document.getElementById("status");
  let imageData = null;
  let box = null;
  let drag = null;
  let sendTimer = null;

  const post = (type, extra = {}) => window.parent.postMessage({
    isStreamlitMessage: true,
    type,
    ...extra,
  }, "*");

  function bounds() {
    return { width: image.clientWidth, height: image.clientHeight };
  }

  function clampBox() {
    const { width, height } = bounds();
    if (!width || !height || !box) return;
    box.size = Math.max(1, Math.min(box.size, width, height));
    box.left = Math.max(0, Math.min(box.left, width - box.size));
    box.top = Math.max(0, Math.min(box.top, height - box.size));
  }

  function draw() {
    clampBox();
    if (!box) return;
    frame.style.left = `${box.left}px`;
    frame.style.top = `${box.top}px`;
    frame.style.width = `${box.size}px`;
    frame.style.height = `${box.size}px`;
    post("streamlit:setFrameHeight", { height: Math.ceil(stage.getBoundingClientRect().height + 4) });
  }

  function sendValue() {
    if (!box) return;
    const { width, height } = bounds();
    const minSide = Math.min(width, height);
    if (!minSide) return;
    post("streamlit:setComponentValue", {
      value: {
        left: box.left / width,
        top: box.top / height,
        size: box.size / minSide,
      },
      dataType: "json",
    });
    status.textContent = "Crop updated";
  }

  function scheduleSend() {
    if (sendTimer) return;
    sendTimer = window.setTimeout(() => {
      sendTimer = null;
      sendValue();
    }, 85);
  }

  function startPointer(event) {
    if (!box) return;
    event.preventDefault();
    const rect = image.getBoundingClientRect();
    drag = {
      pointerX: event.clientX,
      pointerY: event.clientY,
      left: box.left,
      top: box.top,
      size: box.size,
      resizing: event.target === handle,
      rect,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function movePointer(event) {
    if (!drag) return;
    const scaleX = image.clientWidth / drag.rect.width;
    const scaleY = image.clientHeight / drag.rect.height;
    const dx = (event.clientX - drag.pointerX) * scaleX;
    const dy = (event.clientY - drag.pointerY) * scaleY;
    const { width, height } = bounds();
    if (drag.resizing) {
      const maxSize = Math.max(1, Math.min(width - drag.left, height - drag.top));
      box.size = Math.max(Math.min(48, maxSize), Math.min(maxSize, drag.size + Math.max(dx, dy)));
    } else {
      box.left = Math.max(0, Math.min(width - box.size, drag.left + dx));
      box.top = Math.max(0, Math.min(height - box.size, drag.top + dy));
    }
    draw();
    scheduleSend();
  }

  function endPointer() {
    if (!drag) return;
    drag = null;
    if (sendTimer) {
      window.clearTimeout(sendTimer);
      sendTimer = null;
    }
    sendValue();
  }

  function render(args) {
    if (args.image_data !== imageData) {
      imageData = args.image_data;
      box = null;
      image.onload = () => {
        const { width, height } = bounds();
        const defaultSize = Math.min(width, height) * 0.6;
        box = {
          left: (width - defaultSize) / 2,
          top: (height - defaultSize) / 2,
          size: defaultSize,
        };
        draw();
      };
      image.src = `data:image/png;base64,${imageData}`;
    } else if (box) {
      draw();
    }
  }

  frame.addEventListener("pointerdown", startPointer);
  handle.addEventListener("pointerdown", startPointer);
  frame.addEventListener("pointermove", movePointer);
  handle.addEventListener("pointermove", movePointer);
  frame.addEventListener("pointerup", endPointer);
  handle.addEventListener("pointerup", endPointer);
  frame.addEventListener("pointercancel", endPointer);
  handle.addEventListener("pointercancel", endPointer);
  window.addEventListener("resize", draw);
  window.addEventListener("message", (event) => {
    if (event.data && event.data.type === "streamlit:render") render(event.data.args || {});
  });

  post("streamlit:componentReady", { apiVersion: 1 });
  post("streamlit:setFrameHeight", { height: 510 });
})();
