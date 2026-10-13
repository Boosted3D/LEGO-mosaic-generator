"""Streamlit interface for the LEGO mosaic generator."""
import io
import html
import tempfile
import zipfile
from pathlib import Path

import streamlit as st

import lego_mosaic as L


def set_color_selection(selected: bool) -> None:
    for color in L.COLOR_PALETTE:
        st.session_state[f"use_color_{color.code}"] = selected

def get_output_dir() -> Path:
    """Use a writable, isolated output directory for each browser session."""
    if "output_dir" not in st.session_state:
        st.session_state["output_dir"] = tempfile.mkdtemp(prefix="lego-mosaic-")
    return Path(st.session_state["output_dir"])

st.set_page_config(page_title="LEGO Mosaic → 3D Print", page_icon="🧱", layout="wide")
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
[data-testid="stFileUploader"] section { border: 1px dashed #424854; border-radius: 14px; background: #111318; }
.result-meta { color: #aeb5c0; background: #15181f; border: 1px solid #2d313a; border-radius: 999px; padding: 6px 12px; display: inline-block; font-size: .86rem; }
.swatch-dot { width: 16px; height: 16px; border-radius: 50%; display: inline-block; border: 1px solid #ffffff55; vertical-align: -3px; margin-right: 8px; }
</style>
""", unsafe_allow_html=True)
st.title("🧱 LEGO Mosaic → Bambu Lab 3D Print")
st.caption("Upload an image and choose color or grayscale. The default format is 48×48 studs, split into four 24×24 tiles.")

with st.sidebar:
    st.header("Settings")
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
                st.markdown(f'<div class="swatch-dot" title="{html.escape(color.name_en)}" style="background:{color.hex}"></div>', unsafe_allow_html=True)
                checked = st.checkbox(color.code, value=True, key=f"use_color_{color.code}", help=color.name_en)
                if checked:
                    selected_codes.append(color.code)
        selected_colors = tuple(selected_codes)
    grid_size = st.selectbox("Format", [24, 30, 48, 60], index=2,
                             format_func=lambda x: f"{x}×{x} studs" + (f" (4 tiles of {x // 2}×{x // 2})" if x in (48, 60) else " (1 plate)"))
    reserve = st.number_input("Reserve (%)", 0.0, 100.0, 5.0, 1.0)
    if palette_mode == "grayscale":
        thickness = st.number_input("Baseplate thickness (mm)", 0.4, 10.0, 1.6, 0.2)
        base = st.selectbox("Baseplate color", [c.code for c in L.GRAYSCALE_PALETTE],
                            format_func=lambda c: next(p.name_en for p in L.GRAYSCALE_PALETTE if p.code == c))
    else:
        thickness, base = 1.6, "BK"
    auto = st.checkbox("Auto-enhance contrast", value=True)
    loose_all = st.checkbox("Include loose studs (needed + reserve)", value=True)

upload = st.file_uploader("Image (JPG/PNG)", type=["jpg", "jpeg", "png"])

if upload is not None:
    try:
        L.load_image(io.BytesIO(upload.getvalue()))
    except L.MosaicError as exc:
        st.error(str(exc))
        st.stop()
    if st.button("Generate mosaic", type="primary"):
        opts = L.Options(grid=grid_size, palette_mode=palette_mode,
                         selected_colors=selected_colors, reserve_pct=reserve,
                         plate_thickness=thickness, base_color=base,
                         dither=False, autocontrast=auto, loose_include_needed=loose_all)
        try:
            with st.spinner("Generating (3D files may take a moment)…"):
                res = L.generate(io.BytesIO(upload.getvalue()), get_output_dir(), options=opts)
        except L.MosaicError as exc:
            st.error(str(exc))
            st.stop()
        except Exception as exc:
            st.error(f"Unexpected error: {exc!r}")
            st.exception(exc)
            st.stop()
        st.session_state["res"] = res
        st.session_state["palette_mode"] = palette_mode

res = st.session_state.get("res")
if res:
    for w in res.warnings:
        st.warning(w)
    st.markdown(f'<div class="result-meta">✓ Mosaic ready&nbsp;&nbsp;·&nbsp;&nbsp;{len(res.all_files())} files</div>', unsafe_allow_html=True)
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
                    f'<td>{row["needed"]}</td><td>{row["reserve_extra"]}</td><td>{row["total_to_print"]}</td>'
                    "</tr>"
                )
            total_needed = sum(row["needed"] for row in res.bom)
            total_reserve = sum(row["reserve_extra"] for row in res.bom)
            table_html = (
                '<table style="width:100%;border-collapse:collapse;font-size:.9rem">'
                '<thead><tr style="color:#9299a6;text-align:left;border-bottom:1px solid #2d313a">'
                '<th style="padding:8px 4px">Color</th><th>Needed</th><th>Reserve</th><th>Total</th></tr></thead>'
                f'<tbody>{"".join(table_rows)}</tbody>'
                '<tfoot><tr style="border-top:1px solid #2d313a;font-weight:600">'
                f'<td style="padding:10px 4px">Total</td><td>{total_needed}</td><td>{total_reserve}</td>'
                f'<td>{total_needed + total_reserve}</td></tr></tfoot></table>'
            )
            st.markdown(table_html, unsafe_allow_html=True)
    with st.expander("Building instructions"):
        st.image(str(res.files["docs"][0]), use_container_width=True)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in res.all_files():
            z.write(p, p.relative_to(res.out_dir))
    st.download_button("⬇️ All files (ZIP)", buf.getvalue(), "lego_mosaic_output.zip", "application/zip")
