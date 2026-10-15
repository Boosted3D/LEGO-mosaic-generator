"""Streamlit interface for the LEGO mosaic generator."""
import io
import html
import hashlib
import tempfile
from pathlib import Path

import streamlit as st
from streamlit_cropper import st_cropper

import lego_mosaic as L


def set_color_selection(selected: bool) -> None:
    for color in L.COLOR_PALETTE:
        st.session_state[f"use_color_{color.code}"] = selected

def get_output_dir() -> Path:
    """Use a writable, isolated output directory for each browser session."""
    if "output_dir" not in st.session_state:
        st.session_state["output_dir"] = tempfile.mkdtemp(prefix="lego-mosaic-")
    return Path(st.session_state["output_dir"])

st.set_page_config(page_title="LEGO Mosaic → 3D Print", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root { --surface: #111318; --card: #15181f; --line: #2d313a; --muted: #9299a6; --green: #00ae42; }
html, body, [class*="css"] { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
.stApp { background: #0c0e12; }
[data-testid="stSidebar"] { background: #111318; border-right: 1px solid var(--line); }
[data-testid="stBaseButton-primary"] { background: var(--green); border: 1px solid var(--green); border-radius: 10px; color: white; transition: transform .15s ease, filter .15s ease; }
[data-testid="stBaseButton-primary"]:hover { background: #07983e; border-color: #07983e; transform: translateY(-1px); }
[data-testid="stDownloadButton"] button { border-radius: 10px; }
[data-testid="stFileUploader"] section { border: 1px dashed #2d313a; border-radius: 0 0 16px 16px; background: #111318; min-height: 100px; transition: border-color .18s ease, box-shadow .18s ease, background .18s ease; }
[data-testid="stFileUploader"] section:hover, [data-testid="stFileUploader"] section:focus-within { border-color: #00ae42; box-shadow: 0 0 0 3px #00ae421a; background: #121914; }
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] { color: #aab2bd; }
[data-testid="stFileUploader"] button { border-radius: 8px; }
.upload-copy { text-align:center; padding:24px 20px 12px; border:1px dashed #2d313a; border-bottom:0; border-radius:16px 16px 0 0; background:linear-gradient(180deg,#14171d,#111318); }
.upload-copy svg { width:30px; height:30px; color:#aab2bd; margin-bottom:8px; }
.upload-copy strong { display:block; color:#f0f2f5; font-size:1rem; font-weight:600; }
.upload-copy span { display:block; color:#9299a6; font-size:.82rem; margin-top:5px; }
.sidebar-section-title { color:#838c98; font-size:.68rem; font-weight:700; letter-spacing:.11em; margin:18px 0 8px; }
.sidebar-rule { border:0; border-top:1px solid #2d313a; margin:14px 0; }
.swatch-chip { display:flex; justify-content:center; margin:5px 0 1px; }
.swatch-chip .swatch-dot { width:21px; height:21px; margin:0; border:1px solid #ffffff44; }
[class*="st-key-use_color_"] [data-testid="stCheckbox"] label { justify-content:center; min-height:31px; border:1px solid #343a44; border-radius:999px; padding:2px 8px; background:#15181f; transition:opacity .15s ease,border-color .15s ease,background .15s ease; }
[class*="st-key-use_color_"] [data-testid="stCheckbox"] label:has(input:checked) { border-color:#00ae42; background:#102018; box-shadow:0 0 0 2px #00ae4217; opacity:1; }
[class*="st-key-use_color_"] [data-testid="stCheckbox"] label:not(:has(input:checked)) { opacity:.5; }
[class*="st-key-use_color_"] [data-testid="stCheckbox"] label > span:first-child { display:none; }
.empty-preview { min-height:300px; border:1px solid #2d313a; border-radius:18px; background:radial-gradient(ellipse at 50% 35%,#171b22 0%,#111318 70%); display:flex; flex-direction:column; align-items:center; justify-content:center; padding:30px; text-align:center; }
.placeholder-grid { display:grid; grid-template-columns:repeat(10,16px); gap:4px; margin-bottom:24px; opacity:.44; }
.placeholder-grid span { width:16px; height:16px; border-radius:4px; background:#252b34; border:1px solid #343b46; }
.placeholder-grid span:nth-child(7n),.placeholder-grid span:nth-child(13n),.placeholder-grid span:nth-child(29n) { background:#304136; border-color:#3b5944; }
.empty-preview strong { color:#d8dde4; font-size:1rem; font-weight:600; }
.empty-preview p { max-width:520px; margin:8px 0 0; color:#858e9a; font-size:.88rem; }
.result-meta { color: #aeb5c0; background: #15181f; border: 1px solid #2d313a; border-radius: 999px; padding: 6px 12px; display: inline-block; font-size: .86rem; }
.swatch-dot { width: 16px; height: 16px; border-radius: 50%; display: inline-block; border: 1px solid #ffffff55; vertical-align: -3px; margin-right: 8px; }
.app-header { display:flex; justify-content:space-between; align-items:center; gap:24px; margin:12px 0 30px; }
.brand-lockup { display:flex; align-items:center; gap:16px; min-width:0; }
.brand-mark { width:54px; height:54px; flex:none; }
.brand-copy h1 { margin:0; font-size:clamp(1.8rem,3vw,2.55rem); line-height:1.15; font-weight:700; letter-spacing:-.045em; color:#f4f6f8; }
.title-arrow { width:.78em; height:.78em; vertical-align:-.04em; fill:none; stroke:#aab3bd; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
.brand-copy p { margin:8px 0 0; color:#888; font-size:.88rem; }
.engine-badge { display:flex; align-items:center; gap:8px; white-space:nowrap; padding:8px 12px; border:1px solid #273a30; border-radius:999px; background:#111a15; color:#c7d7cd; font-size:.78rem; }
.engine-badge span { width:7px; height:7px; border-radius:50%; background:#00ae42; box-shadow:0 0 10px #00ae4280; }
@media (max-width:700px) { .app-header { align-items:flex-start; flex-direction:column; } .brand-mark { width:42px; height:42px; } }
</style>
""", unsafe_allow_html=True)
st.markdown("""
<header class="app-header">
  <div class="brand-lockup">
    <svg class="brand-mark" viewBox="0 0 64 64" role="img" aria-label="Four-stud mosaic logo">
      <defs>
        <linearGradient id="studGradient" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#51d98a"/><stop offset="100%" stop-color="#00AE42"/>
        </linearGradient>
      </defs>
      <rect x="7" y="18" width="50" height="39" rx="9" fill="#151a20" stroke="#3b4650" stroke-width="2"/>
      <rect x="12" y="10" width="17" height="17" rx="5" fill="url(#studGradient)"/>
      <rect x="35" y="10" width="17" height="17" rx="5" fill="url(#studGradient)"/>
      <rect x="12" y="33" width="17" height="17" rx="5" fill="url(#studGradient)"/>
      <rect x="35" y="33" width="17" height="17" rx="5" fill="url(#studGradient)"/>
    </svg>
    <div class="brand-copy">
      <h1>LEGO Mosaic <svg class="title-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6"/></svg> Bambu Lab 3D Print</h1>
      <p>Upload an image and choose color or grayscale. Default format: 48×48 studs, split into four 24×24 tiles.</p>
    </div>
  </div>
  <div class="engine-badge"><span></span>Engine Online</div>
</header>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Settings")
    st.markdown('<div class="sidebar-section-title">01 &nbsp; KLEURENPALET</div>', unsafe_allow_html=True)
    mode_label = st.radio("Palette", ["Kleur", "Grijstinten"], horizontal=True)
    palette_mode = "color" if mode_label == "Kleur" else "grayscale"
    selected_colors = None
    if palette_mode == "color":
        st.markdown("**Colors to use**")
        select_all_col, clear_all_col = st.columns(2)
        select_all_col.button("Select all", use_container_width=True, on_click=set_color_selection, args=(True,))
        clear_all_col.button("Clear all", use_container_width=True, on_click=set_color_selection, args=(False,))
        color_columns = st.columns(3)
        selected_codes = []
        for index, color in enumerate(L.COLOR_PALETTE):
            with color_columns[index % 3]:
                st.markdown(f'<div class="swatch-chip"><span class="swatch-dot" title="{html.escape(color.name_en)}" style="background:{color.hex}"></span></div>', unsafe_allow_html=True)
                checked = st.checkbox(color.code, value=True, key=f"use_color_{color.code}", help=color.name_en)
                if checked:
                    selected_codes.append(color.code)
        selected_colors = tuple(selected_codes)
    st.markdown('<hr class="sidebar-rule"><div class="sidebar-section-title">02 &nbsp; FORMAAT &amp; AFMETINGEN</div>', unsafe_allow_html=True)
    grid_size = st.selectbox("Format", [24, 30, 48, 60], index=2,
                             format_func=lambda x: f"{x}×{x} studs" + (f" (4 tiles of {x // 2}×{x // 2})" if x in (48, 60) else " (1 plate)"))
    reserve = st.number_input("Reserve (%)", 0.0, 100.0, 5.0, 1.0)
    st.markdown('<hr class="sidebar-rule"><div class="sidebar-section-title">03 &nbsp; PRINT INSTELLINGEN</div>', unsafe_allow_html=True)
    auto = st.checkbox("Auto-enhance contrast", value=True)
    loose_all = st.checkbox("Include loose studs (needed + reserve)", value=True)
    st.caption(f"Minimum space between studs: {L.MIN_STUD_GAP_MM:.1f} mm")
    edge_margin = st.number_input("Edge margin (mm)", min_value=0.0, max_value=50.0,
                                  value=float(L.EDGE_MARGIN_MM), step=0.5)
    rotation = st.selectbox("Plate rotation", [0, 90, 180, 270], index=0,
                            format_func=lambda degrees: f"{degrees}°")
    scale_to_fit = st.checkbox("Uniformly scale plates to fit", value=False,
                               help="Only scale if you explicitly turn this on. All plates use the same X/Y scale.")

st.markdown('''
<div class="upload-copy">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/>
  </svg>
  <strong>Sleep je afbeelding hiernaartoe of klik om te uploaden</strong>
  <span>Ondersteunt JPG en PNG · max. 200 MB</span>
</div>
''', unsafe_allow_html=True)
upload = st.file_uploader("Image (JPG/PNG)", type=["jpg", "jpeg", "png"], label_visibility="collapsed")
current_result_signature = "__no_image__"

if upload is not None:
    try:
        image_bytes = upload.getvalue()
        source_image = L.load_image(io.BytesIO(image_bytes))
    except L.MosaicError as exc:
        st.error(str(exc))
        st.stop()

    st.markdown("### Adjust your mosaic")
    crop_col, mosaic_col = st.columns(2, gap="medium")
    with crop_col:
        st.caption("Drag the square over your photo to choose the crop")
        cropped_image = st_cropper(
            source_image,
            realtime_update=True,
            box_color="#00AE42",
            aspect_ratio=(1, 1),
            return_type="image",
            should_resize_image=True,
            key=f"mosaic_cropper_{hashlib.sha256(image_bytes).hexdigest()[:12]}",
        )
    if cropped_image is None:
        cropped_image = source_image
    crop_zoom, crop_x, crop_y = 1.0, 0.5, 0.5
    cropped_buffer = io.BytesIO()
    cropped_image.save(cropped_buffer, format="PNG")
    processed_image_bytes = cropped_buffer.getvalue()

    with st.expander("Image adjustments", expanded=False):
        adjust_cols = st.columns(4)
        brightness = adjust_cols[0].slider("Brightness", 0.5, 1.5, 1.0, 0.05)
        contrast = adjust_cols[1].slider("Contrast", 0.5, 1.8, 1.0, 0.05)
        saturation = adjust_cols[2].slider("Color intensity", 0.0, 1.8, 1.0, 0.05)
        sharpness = adjust_cols[3].slider("Sharpness", 0.0, 2.0, 1.0, 0.05)

    preview_palette = L.palette_for_mode(palette_mode, selected_colors)
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
        grid_size, palette_mode, selected_colors,
        reserve, auto, loose_all, edge_margin, rotation, scale_to_fit,
        crop_zoom, crop_x, crop_y, brightness, contrast, saturation, sharpness,
    )
    current_result_signature = hashlib.sha256(repr(signature_values).encode("utf-8")).hexdigest()

    if not preview_palette:
        st.warning("Select at least one color to preview and generate the mosaic.")
    else:
        preview_idx = L.mosaic_indices(
            cropped_image, grid_size, preview_palette,
            autocontrast=auto, brightness=brightness, contrast=contrast,
            saturation=saturation, sharpness=sharpness,
            crop_zoom=crop_zoom, crop_x=crop_x, crop_y=crop_y,
        )
        with mosaic_col:
            st.caption(f"Mosaic · {grid_size}×{grid_size} studs")
            preview_cell_size = max(7, 420 // grid_size)
            st.image(
                L.render_preview_image(
                    preview_idx, cell=preview_cell_size, palette=preview_palette
                ),
                width=420,
            )

    if st.button("Generate mosaic", type="primary", disabled=not preview_palette):
        try:
            with st.spinner("Generating (3D files may take a moment)…"):
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
if res:
    for w in res.warnings:
        st.warning(w)
    st.markdown(f'<div class="result-meta">✓ Mosaic ready&nbsp;&nbsp;·&nbsp;&nbsp;{len(res.project_plate_names)} print plates</div>', unsafe_allow_html=True)
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
                    f"exclusion gap {item['exclusion_clearance_mm']:.2f} mm"
                    f"{brim_note}"
                )
            else:
                # Streamlit can retain a result created before placement reports
                # gained position fields. Keep that session usable after deploy.
                clearance = item.get("edge_clearance_mm", item.get("clearance_mm"))
                if clearance is None:
                    st.write(item["plate"])
                else:
                    st.write(f"{item['plate']}: edge clearance {float(clearance):.2f} mm")
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
                rgb = row["rgb"]
                swatch = "#%02X%02X%02X" % tuple(rgb)
                code = html.escape(row["code"])
                table_rows.append(
                    "<tr>"
                    f'<td><span class="swatch-dot" style="background:{swatch}"></span>{code}</td>'
                    f'<td>{row["needed"]}</td>'
                    f'<td>{row["reserve_extra"]}</td><td>{row["total_to_print"]}</td>'
                    "</tr>"
                )
            total_needed = sum(row["needed"] for row in res.bom)
            total_reserve = sum(row["reserve_extra"] for row in res.bom)
            total_pieces = total_needed + total_reserve
            table_html = (
                '<table style="width:100%;border-collapse:collapse;font-size:.9rem">'
                '<thead><tr style="color:#9299a6;text-align:left;border-bottom:1px solid #2d313a">'
                '<th style="padding:8px 4px">Color</th><th>Studs</th>'
                '<th>Reserve</th><th>Total pieces</th></tr></thead>'
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
            "Download printable instructions (PDF)",
            instruction_pdf.read_bytes(),
            file_name="building_instructions.pdf",
            mime="application/pdf",
        )

    project_file = res.files["bambu_project"][0]
    st.caption("One Bambu Studio project with multiple named print plates.")
    st.download_button(
        "Download Bambu Studio project (.3MF)",
        project_file.read_bytes(),
        "lego_mosaic_bambu_project.3mf",
        "application/vnd.ms-package.3dmanufacturing-3dmodel+zip",
        type="primary",
    )
else:
    placeholder_cells = "".join("<span></span>" for _ in range(60))
    st.markdown(
        '<section class="empty-preview">'
        f'<div class="placeholder-grid">{placeholder_cells}</div>'
        '<strong>Your mosaic preview will appear here</strong>'
        '<p>Upload een afbeelding om direct de 2D LEGO-preview en het 3D-bestandsoverzicht te bekijken.</p>'
        '</section>',
        unsafe_allow_html=True,
    )
