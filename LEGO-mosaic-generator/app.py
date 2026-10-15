"""Streamlit interface for the LEGO mosaic generator."""
import base64
import hashlib
import html
import io
import json
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import lego_mosaic as L


square_cropper = components.declare_component(
    "mosaic_square_cropper",
    path=str(Path(__file__).parent / "square_cropper_component"),
)


def set_color_selection(selected: bool) -> None:
    for color in L.COLOR_PALETTE:
        st.session_state[f"use_color_{color.code}"] = selected


def get_output_dir() -> Path:
    """Use a writable, isolated output directory for each browser session."""
    if "output_dir" not in st.session_state:
        st.session_state["output_dir"] = tempfile.mkdtemp(prefix="lego-mosaic-")
    return Path(st.session_state["output_dir"])


def render_color_swatch(color) -> None:
    """Show a palette swatch with its Bambu name tooltip and copy action."""
    title = html.escape(
        f"Bambu Lab: {color.name_en} ({color.code} · {color.hex})", quote=True
    )
    components.html(
        f"""<!doctype html><html><head><style>
        html,body{{margin:0;width:100%;height:32px;background:transparent;}}
        body{{display:flex;align-items:center;justify-content:center;}}
        button{{width:20px;height:20px;padding:0;border:1px solid #ffffff66;
          border-radius:50%;background-color:{color.hex} !important;cursor:pointer;}}
        button:hover{{outline:2px solid #ffffffaa;outline-offset:2px;}}
        button.copied{{outline:2px solid #0d9488;outline-offset:2px;}}
        </style></head><body>
        <button id="swatch" type="button" title="{title}"
          aria-label="Copy {color.hex}"></button>
        <script>
        const swatch=document.getElementById("swatch");
        const color={json.dumps(color.hex)};
        swatch.addEventListener("click",async()=>{{
          try{{await navigator.clipboard.writeText(color);}}
          catch(error){{
            const field=document.createElement("textarea");
            field.value=color;field.style.position="fixed";field.style.opacity="0";
            document.body.appendChild(field);field.select();document.execCommand("copy");field.remove();
          }}
          swatch.classList.add("copied");swatch.title="Copied "+color;
          setTimeout(()=>{{swatch.classList.remove("copied");swatch.title={json.dumps(title)};}},1200);
        }});
        </script></body></html>""",
        height=32,
        scrolling=False,
    )


st.set_page_config(
    page_title="LEGO Mosaic → 3D Print",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root { --surface:#111318; --card:#15181f; --line:#2d313a; --muted:#9299a6; --green:#00ae42; --teal:#0d9488; }
html, body, [class*="css"] { font-family:Inter,ui-sans-serif,system-ui,sans-serif; }
.stApp { background:#0c0e12; }
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display:none; }
.main .block-container { max-width:1200px; padding:2rem 2rem 4rem; }
[data-testid="stBaseButton-primary"] { background:var(--green); border:1px solid var(--green); border-radius:8px; color:white; transition:filter .15s ease,transform .15s ease; }
[data-testid="stBaseButton-primary"]:hover { background:#07983e; border-color:#07983e; transform:translateY(-1px); }
[data-testid="stDownloadButton"] button { border-radius:8px; }
[data-testid="stFileUploader"] section { border:1px dashed #343943; border-radius:8px; background:#111318; min-height:94px; transition:border-color .18s ease,background .18s ease; }
[data-testid="stFileUploader"] section:hover,[data-testid="stFileUploader"] section:focus-within { border-color:#00ae42; background:#121914; }
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] { color:#aab2bd; }
[data-testid="stFileUploader"] button { border-radius:6px; }
.app-header { display:flex; justify-content:space-between; align-items:center; gap:24px; margin:4px 0 28px; }
.brand-lockup { display:flex; align-items:center; gap:16px; min-width:0; }
.brand-mark { width:50px; height:50px; flex:none; }
.brand-copy h1 { margin:0; font-size:clamp(1.8rem,3vw,2.45rem); line-height:1.15; font-weight:700; letter-spacing:-.045em; color:#f4f6f8; }
.title-arrow { width:.78em; height:.78em; vertical-align:-.04em; fill:none; stroke:#aab3bd; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
.brand-copy p { margin:8px 0 0; color:#9299a6; font-size:.88rem; }
.engine-badge { display:flex; align-items:center; gap:8px; white-space:nowrap; padding:7px 10px; border:1px solid #273a30; border-radius:7px; background:#111a15; color:#c7d7cd; font-size:.76rem; }
.engine-badge span { width:7px; height:7px; border-radius:50%; background:#00ae42; }
.stepper { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin:0 0 30px; }
.step-item { display:flex; align-items:center; gap:12px; padding:14px 16px; border:1px solid #2d313a; border-radius:8px; background:#111318; color:#c4cad3; }
.step-number { display:grid; place-items:center; width:28px; height:28px; flex:none; border:1px solid #424852; border-radius:50%; color:#aeb5c0; font-size:.8rem; font-weight:600; }
.step-item.active { border-color:#00ae4266; background:#101712; color:#f2f4f6; }
.step-item.active .step-number,.step-item.done .step-number { border-color:#00ae42; background:#00ae42; color:#fff; }
.step-label { font-weight:600; font-size:.9rem; }
.section-heading { margin:0 0 16px; color:#f1f3f6; font-size:1.15rem; font-weight:650; }
.section-kicker { margin:0 0 6px; color:#00ae42; text-transform:uppercase; letter-spacing:.1em; font-size:.7rem; font-weight:700; }
.upload-copy { text-align:center; padding:22px 20px 8px; border:1px dashed #343943; border-bottom:0; border-radius:8px 8px 0 0; background:#13161c; }
.upload-copy svg { width:28px; height:28px; color:#aab2bd; margin-bottom:8px; }
.upload-copy strong { display:block; color:#f0f2f5; font-size:.98rem; font-weight:600; }
.upload-copy span { display:block; color:#9299a6; font-size:.82rem; margin-top:5px; }
.step-help { color:#8d95a1; font-size:.86rem; margin-top:4px; }
.preview-frame { padding:12px; border:1px solid #2d313a; border-radius:8px; background:#0d0f13; min-height:250px; }
.color-card { height:100%; min-height:58px; padding:8px; border:1px solid #2d313a; border-radius:7px; background:#15181f; }
.color-name { min-height:32px; display:flex; align-items:center; color:#e8ebef; font-size:.78rem; line-height:1.1; font-weight:500; }
[data-testid="stToggle"] [role="switch"][aria-checked="true"] { background:#0d9488 !important; border-color:#0d9488 !important; }
[data-testid="stToggle"] [role="switch"][aria-checked="false"] { background:#343943 !important; border-color:#454b55 !important; }
[data-testid="stSlider"] [role="slider"] { background:#0d9488; border-color:#0d9488; }
[data-testid="stSlider"] [data-baseweb="slider"] > div > div { background:#0d9488; }
.empty-preview { min-height:260px; border:1px dashed #303640; border-radius:8px; background:#101217; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:24px; text-align:center; }
.placeholder-grid { display:grid; grid-template-columns:repeat(10,14px); gap:4px; margin-bottom:18px; opacity:.36; }
.placeholder-grid span { width:14px; height:14px; border-radius:3px; background:#252b34; border:1px solid #343b46; }
.placeholder-grid span:nth-child(7n),.placeholder-grid span:nth-child(13n),.placeholder-grid span:nth-child(29n) { background:#304136; border-color:#3b5944; }
.empty-preview strong { color:#d8dde4; font-size:.98rem; font-weight:600; }
.empty-preview p { max-width:500px; margin:7px 0 0; color:#858e9a; font-size:.86rem; }
.result-meta { color:#aeb5c0; font-size:.88rem; margin:8px 0 16px; }
.swatch-dot { width:16px; height:16px; border-radius:50%; display:inline-block; border:1px solid #ffffff55; vertical-align:-3px; margin-right:8px; }
@media (max-width:700px) {
  .main .block-container { padding:1.2rem .8rem 3rem; }
  .app-header { align-items:flex-start; flex-direction:column; }
  .stepper { grid-template-columns:1fr; gap:7px; }
  .workflow-section { padding:16px; }
  .color-name { font-size:.7rem; }
}
</style>
""",
    unsafe_allow_html=True,
)

# Header and workflow stepper
st.markdown(
    """
<header class="app-header">
  <div class="brand-lockup">
    <svg class="brand-mark" viewBox="0 0 64 64" role="img" aria-label="Four-stud mosaic logo">
      <defs><linearGradient id="studGradient" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#51d98a"/><stop offset="100%" stop-color="#00AE42"/></linearGradient></defs>
      <rect x="7" y="18" width="50" height="39" rx="9" fill="#151a20" stroke="#3b4650" stroke-width="2"/>
      <rect x="12" y="10" width="17" height="17" rx="5" fill="url(#studGradient)"/><rect x="35" y="10" width="17" height="17" rx="5" fill="url(#studGradient)"/>
      <rect x="12" y="33" width="17" height="17" rx="5" fill="url(#studGradient)"/><rect x="35" y="33" width="17" height="17" rx="5" fill="url(#studGradient)"/>
    </svg>
    <div class="brand-copy">
      <h1>LEGO Mosaic <svg class="title-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6"/></svg> Bambu Lab 3D Print</h1>
      <p>Turn a photo into a printable mosaic. Preview, adjust, and export your Bambu Studio project.</p>
    </div>
  </div>
  <div class="engine-badge"><span></span>Engine Online</div>
</header>
""",
    unsafe_allow_html=True,
)
active_step = 3 if st.session_state.get("res") else 2 if st.session_state.get("image_upload") else 1
step_labels = ("Photo & Format", "Colors & Editing", "Preview & Export")
step_items = []
for step_number, step_label in enumerate(step_labels, start=1):
    status = "active" if step_number == active_step else "done" if step_number < active_step else ""
    number_label = "✓" if step_number < active_step else str(step_number)
    step_items.append(
        f'<div class="step-item {status}"><span class="step-number">{number_label}</span>'
        f'<span class="step-label">{step_label}</span></div>'
    )
st.markdown(f'<div class="stepper" aria-label="Mosaic workflow">{"".join(step_items)}</div>', unsafe_allow_html=True)

# Step 1: image upload and mosaic size
st.markdown('<div class="section-kicker">Step 1</div><h2 class="section-heading">Photo &amp; Format</h2>', unsafe_allow_html=True)
upload_copy = st.container()
with upload_copy:
    st.markdown(
        '''<div class="upload-copy">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/>
          </svg><strong>Drag your image here or click to upload</strong><span>Supports JPG and PNG · max. 200 MB</span>
        </div>''',
        unsafe_allow_html=True,
    )
upload = st.file_uploader(
    "Image (JPG/PNG)", type=["jpg", "jpeg", "png"],
    label_visibility="collapsed", key="image_upload",
)
format_col, reserve_col = st.columns([1, 1], gap="medium")
with format_col:
    grid_size = st.selectbox(
        "Mosaic format", [24, 30, 48, 60], index=2,
        format_func=lambda x: f"{x}×{x} studs" + (f" (4 tiles of {x // 2}×{x // 2})" if x in (48, 60) else " (1 plate)"),
    )
with reserve_col:
    reserve = st.number_input("Reserve (%)", 0.0, 100.0, 5.0, 1.0)

with st.expander("Advanced print settings", expanded=False):
    advanced_cols = st.columns(2, gap="medium")
    with advanced_cols[0]:
        loose_all = st.checkbox("Include loose studs (needed + reserve)", value=True)
        edge_margin = st.number_input(
            "Edge margin (mm)", min_value=0.0, max_value=50.0,
            value=float(L.EDGE_MARGIN_MM), step=0.5,
        )
    with advanced_cols[1]:
        rotation = st.selectbox(
            "Plate rotation", [0, 90, 180, 270], index=0,
            format_func=lambda degrees: f"{degrees}°",
        )
        scale_to_fit = st.checkbox(
            "Uniformly scale plates to fit", value=False,
            help="Only scale if you explicitly turn this on. All plates use the same X/Y scale.",
        )
    st.caption(f"Minimum space between studs: {L.MIN_STUD_GAP_MM:.1f} mm")

# Step 2: crop, live mosaic preview, image adjustments, and color selection
st.markdown('<div class="section-kicker">Step 2</div><h2 class="section-heading">Colors &amp; Image Editing</h2><p class="step-help">Adjust the crop and image settings. The mosaic preview updates as you make changes.</p>', unsafe_allow_html=True)
mode_label = st.radio("Palette", ["Color", "Grayscale"], horizontal=True)
palette_mode = "color" if mode_label == "Color" else "grayscale"
selected_colors = None
if palette_mode == "color":
    swatch_title_col, select_all_col, clear_all_col = st.columns([4, 1, 1], vertical_alignment="center")
    with swatch_title_col:
        st.markdown("**Colors to use**")
    select_all_col.button("Select all", use_container_width=True, on_click=set_color_selection, args=(True,))
    clear_all_col.button("Clear all", use_container_width=True, on_click=set_color_selection, args=(False,))
    selected_codes = []
    color_columns = st.columns(4, gap="small")
    for index, color in enumerate(L.COLOR_PALETTE):
        with color_columns[index % 4]:
            with st.container(border=True):
                swatch_col, name_col, toggle_col = st.columns([0.55, 2.0, 0.65], vertical_alignment="center", gap="small")
                with swatch_col:
                    render_color_swatch(color)
                with name_col:
                    st.markdown(f'<div class="color-name">{html.escape(color.name_en)}</div>', unsafe_allow_html=True)
                with toggle_col:
                    checked = st.toggle(
                        f"Use {color.name_en}", value=True,
                        key=f"use_color_{color.code}", label_visibility="collapsed",
                    )
                if checked:
                    selected_codes.append(color.code)
    selected_colors = tuple(selected_codes)

auto = st.checkbox("Auto-enhance contrast", value=True)
preview_palette = L.palette_for_mode(palette_mode, selected_colors)
current_result_signature = "__no_image__"
source_image = cropped_image = None
crop_zoom, crop_x, crop_y = 1.0, 0.5, 0.5
brightness, contrast, saturation, sharpness = 1.0, 1.0, 1.0, 1.0
processed_image_bytes = None

if upload is not None:
    try:
        image_bytes = upload.getvalue()
        source_image = L.load_image(io.BytesIO(image_bytes))
    except L.MosaicError as exc:
        st.error(str(exc))
        st.stop()

    crop_col, mosaic_col = st.columns(2, gap="large")
    with crop_col:
        st.caption("Photo crop")
        crop_display = source_image.copy()
        crop_display.thumbnail((700, 700))
        crop_display_buffer = io.BytesIO()
        crop_display.save(crop_display_buffer, format="PNG")
        crop_value = square_cropper(
            image_data=base64.b64encode(crop_display_buffer.getvalue()).decode("ascii"),
            key=f"mosaic_cropper_{hashlib.sha256(image_bytes).hexdigest()[:12]}",
            default={"left": 0.2, "top": 0.2, "size": 0.6},
        )
        st.caption("Drag the square to move it; drag the corner to resize.")

    crop_width, crop_height = source_image.size
    if not isinstance(crop_value, dict):
        default_side = 0.6 * min(crop_width, crop_height)
        crop_value = {
            "left": (crop_width - default_side) / (2 * crop_width),
            "top": (crop_height - default_side) / (2 * crop_height),
            "size": 0.6,
        }
    crop_size = max(1, min(
        min(crop_width, crop_height),
        round(float(crop_value.get("size", 0.6)) * min(crop_width, crop_height)),
    ))
    crop_left = max(0, min(crop_width - crop_size, round(float(crop_value.get("left", 0.2)) * crop_width)))
    crop_top = max(0, min(crop_height - crop_size, round(float(crop_value.get("top", 0.2)) * crop_height)))
    cropped_image = source_image.crop((crop_left, crop_top, crop_left + crop_size, crop_top + crop_size))
    cropped_buffer = io.BytesIO()
    cropped_image.save(cropped_buffer, format="PNG")
    processed_image_bytes = cropped_buffer.getvalue()

    with crop_col:
        st.markdown("**Image adjustments**")
        slider_cols = st.columns(2, gap="medium")
        brightness = slider_cols[0].slider("Brightness", 0.5, 2.0, 1.0, 0.05)
        contrast = slider_cols[1].slider("Contrast", 0.5, 2.0, 1.0, 0.05)
        extra_cols = st.columns(2, gap="medium")
        saturation = extra_cols[0].slider("Color intensity", 0.0, 1.8, 1.0, 0.05)
        sharpness = extra_cols[1].slider("Sharpness", 0.0, 2.0, 1.0, 0.05)

    if not preview_palette:
        with mosaic_col:
            st.warning("Select at least one color to see the live preview and generate the mosaic.")
    else:
        preview_idx = L.mosaic_indices(
            cropped_image, grid_size, preview_palette,
            autocontrast=auto, brightness=brightness, contrast=contrast,
            saturation=saturation, sharpness=sharpness,
            crop_zoom=crop_zoom, crop_x=crop_x, crop_y=crop_y,
        )
        with mosaic_col:
            st.caption(f"Live mosaic · {grid_size}×{grid_size} studs")
            preview_cell_size = max(7, 420 // grid_size)
            with st.container(border=True):
                st.image(
                    L.render_preview_image(preview_idx, cell=preview_cell_size, palette=preview_palette),
                    width=420,
                )

# Keep all generation options connected to the same live-preview controls.
opts = None
if upload is not None and processed_image_bytes is not None:
    opts = L.Options(
        grid=grid_size, palette_mode=palette_mode, selected_colors=selected_colors,
        reserve_pct=reserve, dither=False, autocontrast=auto,
        loose_include_needed=loose_all, bed_margin=edge_margin,
        rotation_degrees=rotation, scale_to_fit=scale_to_fit,
        crop_zoom=crop_zoom, crop_x=crop_x, crop_y=crop_y,
        brightness=brightness, contrast=contrast, saturation=saturation,
        sharpness=sharpness,
    )
    signature_values = (
        hashlib.sha256(image_bytes).hexdigest(), hashlib.sha256(processed_image_bytes).hexdigest(),
        grid_size, palette_mode, selected_colors, reserve, auto, loose_all,
        edge_margin, rotation, scale_to_fit, crop_zoom, crop_x, crop_y,
        brightness, contrast, saturation, sharpness,
    )
    current_result_signature = hashlib.sha256(repr(signature_values).encode("utf-8")).hexdigest()

# Step 3: generate, inspect, and export
st.markdown('<div class="section-kicker">Step 3</div><h2 class="section-heading">Preview &amp; Export</h2>', unsafe_allow_html=True)
res = st.session_state.get("res") if st.session_state.get("res_signature") == current_result_signature else None
can_generate = upload is not None and bool(preview_palette)
if st.button("Generate mosaic", type="primary", disabled=not can_generate, use_container_width=True):
    try:
        with st.spinner("Generating your mosaic project…"):
            res = L.generate(io.BytesIO(processed_image_bytes), get_output_dir(), options=opts)
    except L.MosaicError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error(f"Unexpected error: {exc!r}")
        st.exception(exc)
        st.stop()
    st.session_state["res"] = res
    st.session_state["res_signature"] = current_result_signature
    st.session_state["palette_mode"] = palette_mode

res = st.session_state.get("res") if st.session_state.get("res_signature") == current_result_signature else None
if upload is None:
    st.info("Upload a photo in Step 1 to generate your mosaic.")
elif not preview_palette:
    st.info("Select at least one color in Step 2 to continue.")

if res:
    for warning in res.warnings:
        st.warning(warning)
    st.markdown(
        f'<div class="result-meta">✓ Mosaic ready · {len(res.project_plate_names)} print plates</div>',
        unsafe_allow_html=True,
    )
    if res.uniform_scale < 1.0:
        st.info(res.warnings[-1])
    with st.expander("Print plate fit and edge clearance"):
        st.caption(f"Required edge margin: {edge_margin:g} mm · rotation: {rotation}°")
        for item in res.plate_edge_clearance:
            if "position_mm" in item and "center_shift_mm" in item:
                x, y = item["position_mm"]
                dx, dy = item["center_shift_mm"]
                brim_note = " · brim disabled for this plate" if item.get("brim_disabled") else ""
                st.write(
                    f"{item['plate']}: position ({x:.2f}, {y:.2f}) mm · "
                    f"shift ({dx:+.2f}, {dy:+.2f}) mm from bed center · "
                    f"edge {item['edge_clearance_mm']:.2f} mm · "
                    f"exclusion gap {item['exclusion_clearance_mm']:.2f} mm{brim_note}"
                )
            else:
                clearance = item.get("edge_clearance_mm", item.get("clearance_mm"))
                st.write(item["plate"] if clearance is None else f"{item['plate']}: edge clearance {float(clearance):.2f} mm")

    preview_col, bom_col = st.columns([1.25, 1], gap="large")
    with preview_col:
        with st.container(border=True):
            st.subheader("Mosaic preview")
            st.image(str(res.files["docs"][1]), use_container_width=True)
    with bom_col:
        with st.container(border=True):
            st.subheader("Parts overview")
            table_rows = []
            for row in res.bom:
                swatch = "#%02X%02X%02X" % tuple(row["rgb"])
                code = html.escape(row["code"])
                table_rows.append(
                    "<tr>"
                    f'<td><span class="swatch-dot" style="background:{swatch}"></span>{code}</td>'
                    f'<td>{row["needed"]}</td><td>{row["reserve_extra"]}</td>'
                    f'<td>{row["total_to_print"]}</td></tr>'
                )
            total_needed = sum(row["needed"] for row in res.bom)
            total_reserve = sum(row["reserve_extra"] for row in res.bom)
            total_pieces = total_needed + total_reserve
            table_html = (
                '<table style="width:100%;border-collapse:collapse;font-size:.9rem">'
                '<thead><tr style="color:#9299a6;text-align:left;border-bottom:1px solid #2d313a">'
                '<th style="padding:8px 4px">Color</th><th>Studs</th><th>Reserve</th>'
                '<th>Total pieces</th></tr></thead>'
                f'<tbody>{"".join(table_rows)}</tbody>'
                '<tfoot><tr style="border-top:1px solid #2d313a;font-weight:600">'
                f'<td style="padding:10px 4px">Total</td><td>{total_needed}</td>'
                f'<td>{total_reserve}</td><td>{total_pieces}</td></tr></tfoot></table>'
            )
            st.markdown(table_html, unsafe_allow_html=True)

    with st.expander("Building instructions"):
        st.image(str(res.files["docs"][0]), use_container_width=True)
        instruction_pdf = res.files["docs"][2]
        st.download_button(
            "Download printable instructions (PDF)", instruction_pdf.read_bytes(),
            file_name="building_instructions.pdf", mime="application/pdf",
        )
    project_file = res.files["bambu_project"][0]
    st.caption("One Bambu Studio project with multiple named print plates.")
    st.download_button(
        "Download Bambu Studio project (.3MF)", project_file.read_bytes(),
        "lego_mosaic_bambu_project.3mf",
        "application/vnd.ms-package.3dmanufacturing-3dmodel+zip",
        type="primary", use_container_width=True,
    )
else:
    placeholder_cells = "".join("<span></span>" for _ in range(60))
    st.markdown(
        '<section class="empty-preview">'
        f'<div class="placeholder-grid">{placeholder_cells}</div>'
        '<strong>Your generated mosaic and parts overview will appear here</strong>'
        '<p>Adjust the photo and colors in Step 2, then generate your project to preview and export it.</p>'
        '</section>',
        unsafe_allow_html=True,
    )
