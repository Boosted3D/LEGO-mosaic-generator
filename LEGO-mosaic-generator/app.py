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
color_swatch_selector = components.declare_component(
    "mosaic_color_swatch_selector",
    path=str(Path(__file__).parent / "color_selector_component"),
)


def get_output_dir() -> Path:
    """Use a writable, isolated output directory for each browser session."""
    if "output_dir" not in st.session_state:
        st.session_state["output_dir"] = tempfile.mkdtemp(prefix="lego-mosaic-")
    return Path(st.session_state["output_dir"])


def render_color_swatch_legend(colors) -> None:
    """Render a non-interactive swatch legend for grayscale mode."""
    swatches = []
    for index, color in enumerate(colors):
        title = html.escape(
            f"Bambu Lab: {color.name_en} ({color.code} · {color.hex})", quote=True
        )
        swatches.append(
            f'<button class="palette-swatch" type="button" title="{title}" '
            f'aria-label="Copy {html.escape(color.hex, quote=True)}" '
            f'style="background-color:{html.escape(color.hex, quote=True)} !important" '
            f'data-color="{html.escape(color.hex, quote=True)}" data-index="{index}"></button>'
        )
    components.html(
        """<!doctype html><html><head><style>
        html,body{margin:0;width:100%;height:34px;background:transparent;}
        .palette-row{height:34px;display:flex;align-items:center;gap:7px;overflow-x:auto;overflow-y:hidden;}
        .palette-swatch{box-sizing:border-box;flex:0 0 24px;width:24px;height:24px;padding:0;
          border:2px solid #151820;border-radius:50%;outline:1px solid #d7dce3;cursor:pointer;}
        </style></head><body><div class="palette-row">"""
        + "".join(swatches)
        + """</div></body></html>""",
        height=36,
        scrolling=False,
    )


def render_bom_table(rows) -> None:
    """Render the current parts count in a compact table."""
    table_rows = []
    for row in rows:
        swatch = "#%02X%02X%02X" % tuple(row["rgb"])
        code = html.escape(row["code"])
        table_rows.append(
            "<tr>"
            f'<td><span class="swatch-dot" style="background:{swatch}"></span>{code}</td>'
            f'<td>{row["needed"]}</td><td>{row["reserve_extra"]}</td>'
            f'<td>{row["total_to_print"]}</td></tr>'
        )
    total_needed = sum(row["needed"] for row in rows)
    total_reserve = sum(row["reserve_extra"] for row in rows)
    total_pieces = total_needed + total_reserve
    st.markdown(
        '<table class="parts-table"><thead><tr><th>Color</th><th>Studs</th>'
        '<th>Reserve</th><th>Total</th></tr></thead>'
        f'<tbody>{"".join(table_rows)}</tbody>'
        '<tfoot><tr><td>Total</td>'
        f'<td>{total_needed}</td><td>{total_reserve}</td><td>{total_pieces}</td>'
        '</tr></tfoot></table>',
        unsafe_allow_html=True,
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
:root { --surface:#0e1117; --card:#141821; --line:#2d333d; --muted:#9299a6; --green:#00ae42; --teal:#0d9488; }
html, body, [class*="css"] { font-family:Inter,ui-sans-serif,system-ui,sans-serif; }
.stApp { background:#0e1117; }
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display:none; }
.main .block-container { max-width:1440px; padding:1.5rem 2rem 3rem; }
[data-testid="stBaseButton-primary"] { background:var(--green); border:1px solid var(--green); border-radius:8px; color:white; transition:filter .15s ease,transform .15s ease,box-shadow .15s ease; }
[data-testid="stBaseButton-primary"]:hover { background:#07983e; border-color:#07983e; box-shadow:0 4px 16px #00ae4230; transform:translateY(-1px); }
[data-testid="stDownloadButton"] button { min-height:48px; border-radius:8px; box-shadow:0 4px 18px #00ae4230; }
[data-testid="stFileUploader"] section { border:1px dashed #343943; border-radius:8px; background:#111318; min-height:84px; transition:border-color .18s ease,background .18s ease; }
[data-testid="stFileUploader"] section:hover,[data-testid="stFileUploader"] section:focus-within { border-color:#00ae42; background:#121914; }
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] { color:#aab2bd; }
[data-testid="stFileUploader"] button { border-radius:6px; }
.app-header { display:flex; justify-content:space-between; align-items:center; gap:24px; margin:4px 0 24px; }
.brand-lockup { display:flex; align-items:center; gap:14px; min-width:0; }
.brand-mark { width:46px; height:46px; flex:none; }
.brand-copy h1 { margin:0; font-size:clamp(1.65rem,2.6vw,2.25rem); line-height:1.15; font-weight:700; letter-spacing:-.045em; color:#f4f6f8; }
.title-arrow { width:.78em; height:.78em; vertical-align:-.04em; fill:none; stroke:#aab3bd; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
.brand-copy p { margin:7px 0 0; color:#9299a6; font-size:.84rem; }
.engine-badge { display:flex; align-items:center; gap:8px; white-space:nowrap; padding:7px 10px; border:1px solid #273a30; border-radius:7px; background:#111a15; color:#c7d7cd; font-size:.74rem; }
.engine-badge span { width:7px; height:7px; border-radius:50%; background:#00ae42; }
.stepper { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:0 0 22px; }
.step-item { display:flex; align-items:center; gap:10px; padding:10px 13px; border:1px solid #2d313a; border-radius:8px; background:#111318; color:#c4cad3; }
.step-number { display:grid; place-items:center; width:25px; height:25px; flex:none; border:1px solid #424852; border-radius:50%; color:#aeb5c0; font-size:.76rem; font-weight:600; }
.step-item.active { border-color:#00ae4266; background:#101712; color:#f2f4f6; }
.step-item.active .step-number,.step-item.done .step-number { border-color:#00ae42; background:#00ae42; color:#fff; }
.step-label { font-weight:600; font-size:.83rem; }
.workspace-title { margin:0 0 12px; color:#eef1f5; font-size:1rem; font-weight:650; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color:#2d333d !important; border-radius:7px !important; background:#141821; }
[data-testid="stExpander"] { border:1px solid #2d333d; border-radius:7px; background:#141821; }
[data-testid="stExpander"] summary { font-size:.88rem; font-weight:600; }
.upload-copy { text-align:center; padding:18px 12px 5px; border:1px dashed #343943; border-bottom:0; border-radius:8px 8px 0 0; background:#13161c; }
.upload-copy svg { width:25px; height:25px; color:#aab2bd; margin-bottom:7px; }
.upload-copy strong { display:block; color:#f0f2f5; font-size:.9rem; font-weight:600; }
.upload-copy span { display:block; color:#9299a6; font-size:.76rem; margin-top:4px; }
.color-name { min-height:30px; display:flex; align-items:center; color:#e8ebef; font-size:.76rem; line-height:1.1; font-weight:500; }
[data-testid="stToggle"] [role="switch"][aria-checked="true"] { background:#0d9488 !important; border-color:#0d9488 !important; }
[data-testid="stToggle"] [role="switch"][aria-checked="false"] { background:#343943 !important; border-color:#454b55 !important; }
[data-testid="stSlider"] [role="slider"] { background:#0d9488; border-color:#0d9488; }
[data-testid="stSlider"] [data-baseweb="slider"] > div > div { background:#0d9488; }
#preview-workspace-anchor { height:0; }
.preview-card { padding:14px; border:1px solid #2d313a; border-radius:8px; background:#0d0f13; margin:8px 0 16px; }
.parts-table { width:100%; border-collapse:collapse; font-size:.82rem; }
.parts-table th { padding:8px 4px; color:#9299a6; text-align:left; font-weight:500; border-bottom:1px solid #2d313a; }
.parts-table td { padding:8px 4px; color:#e0e4e9; border-bottom:1px solid #242831; }
.parts-table td:not(:first-child),.parts-table th:not(:first-child) { text-align:right; font-variant-numeric:tabular-nums; }
.parts-table tfoot td { border-top:1px solid #414650; border-bottom:0; font-weight:650; }
.swatch-dot { width:14px; height:14px; border-radius:50%; display:inline-block; border:1px solid #ffffff55; vertical-align:-3px; margin-right:7px; }
.result-meta { color:#c3d8ca; font-size:.86rem; margin:5px 0 12px; }
.empty-preview { min-height:280px; border:1px dashed #303640; border-radius:8px; background:#101217; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:22px; text-align:center; }
.placeholder-grid { display:grid; grid-template-columns:repeat(10,13px); gap:4px; margin-bottom:16px; opacity:.35; }
.placeholder-grid span { width:13px; height:13px; border-radius:3px; background:#252b34; border:1px solid #343b46; }
.placeholder-grid span:nth-child(7n),.placeholder-grid span:nth-child(13n),.placeholder-grid span:nth-child(29n) { background:#304136; border-color:#3b5944; }
.empty-preview strong { color:#d8dde4; font-size:.95rem; font-weight:600; }
.empty-preview p { max-width:390px; margin:7px 0 0; color:#858e9a; font-size:.82rem; }
@media (max-width:850px) {
  .main .block-container { padding:1rem .75rem 2rem; }
  .app-header { align-items:flex-start; flex-direction:column; }
  .stepper { grid-template-columns:repeat(2,1fr); gap:6px; }
  [data-testid="stVerticalBlockBorderWrapper"] { padding:10px; }
}
</style>
""",
    unsafe_allow_html=True,
)

# App header and workflow indicator
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
      <p>Upload a photo, tune the mosaic, and export a Bambu Studio project.</p>
    </div>
  </div>
  <div class="engine-badge"><span></span>Engine Online</div>
</header>
""",
    unsafe_allow_html=True,
)
active_step = 4 if st.session_state.get("res") else 2 if st.session_state.get("image_upload") else 1
step_labels = ("Upload & Crop", "Format & Adjust", "Color Palette", "Preview & Export")
step_items = []
for step_number, step_label in enumerate(step_labels, start=1):
    status = "active" if step_number == active_step else "done" if step_number < active_step else ""
    number_label = "✓" if step_number < active_step else str(step_number)
    step_items.append(
        f'<div class="step-item {status}"><span class="step-number">{number_label}</span>'
        f'<span class="step-label">{step_label}</span></div>'
    )
st.markdown(f'<div class="stepper" aria-label="Mosaic workflow">{"".join(step_items)}</div>', unsafe_allow_html=True)

control_col = st.container()

# Left: grouped controls
with control_col:
    st.markdown('<h2 class="workspace-title">Control Center</h2>', unsafe_allow_html=True)

    with st.expander("01 · Upload & Crop", expanded=True):
        st.markdown(
            '''<div class="upload-copy">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/>
              </svg><strong>Drag your image here or click to upload</strong><span>JPG or PNG · max. 200 MB</span>
            </div>''',
            unsafe_allow_html=True,
        )
        upload = st.file_uploader(
            "Image (JPG/PNG)", type=["jpg", "jpeg", "png"],
            label_visibility="collapsed", key="image_upload",
        )
        source_image = None
        image_bytes = None
        if upload is not None:
            try:
                image_bytes = upload.getvalue()
                source_image = L.load_image(io.BytesIO(image_bytes))
            except L.MosaicError as exc:
                st.error(str(exc))
                st.stop()

        crop_zoom, crop_x, crop_y = 1.0, 0.5, 0.5
        cropped_image = None
        processed_image_bytes = None
        if source_image is not None:
            st.markdown("**Adjust your mosaic**")
            st.caption("Drag the square to move it; drag the corner to resize.")
            crop_display = source_image.copy()
            crop_display.thumbnail((800, 800))
            crop_display_buffer = io.BytesIO()
            crop_display.save(crop_display_buffer, format="PNG")
            crop_value = square_cropper(
                image_data=base64.b64encode(crop_display_buffer.getvalue()).decode("ascii"),
                key=f"mosaic_cropper_{hashlib.sha256(image_bytes).hexdigest()[:12]}",
                default={"left": 0.2, "top": 0.2, "size": 0.6},
            )
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
        else:
            st.caption("Upload a photo to choose the area used for your mosaic.")

    # Format and image controls follow the crop tool in the workflow.
    crop_zoom, crop_x, crop_y = 1.0, 0.5, 0.5
    brightness = contrast = saturation = sharpness = 1.0
    auto = st.session_state.get("auto_enhance", True)
    with st.expander("02 · Format & Image Adjustments", expanded=upload is not None):
        grid_size = st.selectbox(
            "Mosaic format", [24, 30, 48, 60], index=2,
            format_func=lambda x: f"{x}×{x} studs" + (f" (4 tiles of {x // 2}×{x // 2})" if x in (48, 60) else " (1 plate)"),
        )
        reserve = st.number_input("Reserve (%)", 0.0, 100.0, 5.0, 1.0)
        auto = st.checkbox("Auto-enhance contrast", value=True)
        brightness = st.slider("Brightness", 0.5, 2.0, 1.0, 0.05, format="%.2f")
        contrast = st.slider("Contrast", 0.5, 2.0, 1.0, 0.05, format="%.2f")
        extra_cols = st.columns(2, gap="small")
        saturation = extra_cols[0].slider("Color intensity", 0.0, 1.8, 1.0, 0.05)
        sharpness = extra_cols[1].slider("Sharpness", 0.0, 2.0, 1.0, 0.05)
    with st.expander("Additional Print Settings", expanded=False):
        loose_all = st.checkbox("Include loose studs (needed + reserve)", value=True)
        edge_margin = st.number_input(
            "Edge margin (mm)", min_value=0.0, max_value=50.0,
            value=float(L.EDGE_MARGIN_MM), step=0.5,
        )
        rotation = st.selectbox(
            "Plate rotation", [0, 90, 180, 270], index=0,
            format_func=lambda degrees: f"{degrees}°",
        )
        scale_to_fit = st.checkbox(
            "Uniformly scale plates to fit", value=False,
            help="Only scale if you explicitly turn this on. All plates use the same X/Y scale.",
        )
        st.caption(f"Minimum space between studs: {L.MIN_STUD_GAP_MM:.1f} mm")

    with st.expander("03 · Color Palette", expanded=True):
        mode_label = st.radio("Palette", ["Color", "Grayscale"], horizontal=True)
        palette_mode = "color" if mode_label == "Color" else "grayscale"
        if palette_mode == "color":
            color_codes = tuple(color.code for color in L.COLOR_PALETTE)
            selected_codes = tuple(
                code for code in color_codes
                if code in st.session_state.get("selected_color_codes", color_codes)
            )
            selected_result = color_swatch_selector(
                colors=[
                    {"code": color.code, "name": color.name_en, "hex": color.hex}
                    for color in L.COLOR_PALETTE
                ],
                selected_codes=list(selected_codes),
                key="mosaic_color_selector",
            )
            if isinstance(selected_result, (list, tuple)):
                selected_codes = tuple(code for code in color_codes if code in selected_result)
                st.session_state["selected_color_codes"] = selected_codes
            elif "selected_color_codes" not in st.session_state:
                st.session_state["selected_color_codes"] = selected_codes
            selected_colors = tuple(st.session_state["selected_color_codes"])
        else:
            selected_colors = None
            render_color_swatch_legend(L.GRAYSCALE_PALETTE)

# Build the same image-to-stud grid used by the generator for instant live updates.
preview_palette = L.palette_for_mode(palette_mode, selected_colors)
preview_idx = None
current_result_signature = "__no_image__"
opts = None
live_bom = []
if cropped_image is not None:
    if preview_palette:
        preview_idx = L.mosaic_indices(
            cropped_image, grid_size, preview_palette,
            autocontrast=auto, brightness=brightness, contrast=contrast,
            saturation=saturation, sharpness=sharpness,
            crop_zoom=crop_zoom, crop_x=crop_x, crop_y=crop_y,
        )
        live_bom = L.make_bom(L.count_studs(preview_idx, preview_palette), reserve, preview_palette)
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

# Step 4: live preview, BOM, generation status, and project exports
workspace_col = st.container()
with workspace_col:
    st.markdown('<div id="preview-workspace-anchor"></div><h2 class="workspace-title">04 · Live Preview &amp; Export</h2>', unsafe_allow_html=True)
    res = st.session_state.get("res") if st.session_state.get("res_signature") == current_result_signature else None
    if preview_idx is not None:
        photo_col, mosaic_col = st.columns(2, gap="medium")
        with photo_col:
            st.markdown("**Selected photo area**")
            st.image(cropped_image, width=500)
        with mosaic_col:
            st.markdown("**Live mosaic preview**")
            st.image(
                L.render_preview_image(preview_idx, cell=max(5, 500 // grid_size), palette=preview_palette),
                width=500,
            )
        st.markdown("**Parts overview**")
        render_bom_table(live_bom)
    else:
        placeholder_cells = "".join("<span></span>" for _ in range(50))
        st.markdown(
            '<section class="empty-preview">'
            f'<div class="placeholder-grid">{placeholder_cells}</div>'
            '<strong>Your mosaic preview and parts list will appear here</strong>'
            '<p>Upload an image and adjust the controls to see the result update live.</p>'
            '</section>',
            unsafe_allow_html=True,
        )

    can_generate = upload is not None and preview_idx is not None
    if st.button("Generate mosaic", type="primary", disabled=not can_generate, use_container_width=True):
        try:
            with st.spinner("Generating your Bambu Studio project…"):
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
        st.rerun()

    if upload is None:
        st.caption("Upload a photo in the Control Center to enable project generation.")
    elif not preview_palette:
        st.warning("Select at least one color to generate the mosaic.")

    if res:
        for warning in res.warnings:
            st.warning(warning)
        st.markdown(
            f'<div class="result-meta">✓ Project ready · {len(res.project_plate_names)} print plates</div>',
            unsafe_allow_html=True,
        )
        if res.uniform_scale < 1.0:
            st.info(res.warnings[-1])
        with st.expander("Print plate fit and edge clearance", expanded=False):
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
        with st.expander("Building instructions", expanded=False):
            st.image(str(res.files["docs"][0]), use_container_width=True)
            instruction_pdf = res.files["docs"][2]
            st.download_button(
                "Download printable instructions (PDF)", instruction_pdf.read_bytes(),
                file_name="building_instructions.pdf", mime="application/pdf",
            )
        project_file = res.files["bambu_project"][0]
        st.download_button(
            "Download Bambu Studio project (.3MF)", project_file.read_bytes(),
            "lego_mosaic_bambu_project.3mf",
            "application/vnd.ms-package.3dmanufacturing-3dmodel+zip",
            type="primary", use_container_width=True,
        )
