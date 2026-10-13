"""Streamlit interface for the LEGO mosaic generator."""

import html
import io
import tempfile
from pathlib import Path

import streamlit as st

import lego_mosaic as L


# Session helpers
def set_color_selection(selected: bool) -> None:
    for color in L.COLOR_PALETTE:
        st.session_state[f"use_color_{color.code}"] = selected


def get_output_dir() -> Path:
    """Use a writable, isolated output directory for each browser session."""
    if "output_dir" not in st.session_state:
        st.session_state["output_dir"] = tempfile.mkdtemp(prefix="lego-mosaic-")
    return Path(st.session_state["output_dir"])


st.set_page_config(page_title="LEGO Mosaic → Bambu Lab 3D Print", layout="wide")

# CSS
color_swatch_rules = "\n".join(
    f'''
    :is([data-testid="column"], [data-testid="stColumn"]):has(.st-key-use_color_{color.code}) {{ position: relative; min-height: 32px; }}
    :is([data-testid="column"], [data-testid="stColumn"]):has(.st-key-use_color_{color.code}) [data-testid="stMarkdownContainer"] {{ position: absolute; top: 2px; left: 0; z-index: 0; }}
    :is([data-testid="column"], [data-testid="stColumn"]):has(.st-key-use_color_{color.code}) .st-key-use_color_{color.code} {{ position: absolute; inset: 0; z-index: 1; width: 32px; height: 32px; opacity: 0 !important; }}
    :is([data-testid="column"], [data-testid="stColumn"]):has(.st-key-use_color_{color.code}):has(input:checked) .palette-swatch {{ opacity: 1; outline: 1px solid var(--accent); outline-offset: 2px; }}
    :is([data-testid="column"], [data-testid="stColumn"]):has(.st-key-use_color_{color.code}):has(input:focus-visible) .palette-swatch {{ outline: 2px solid var(--accent); outline-offset: 3px; }}
    :is([data-testid="column"], [data-testid="stColumn"]):has(.st-key-use_color_{color.code}):hover::after {{ content: "{color.name_en} ({color.code})"; position: absolute; top: 36px; left: 0; z-index: 20; padding: 5px 7px; border: 1px solid var(--line); border-radius: 3px; background: var(--surface-raised); color: var(--text); font-size: 11px; white-space: nowrap; pointer-events: none; }}
    '''
    for color in L.COLOR_PALETTE
)
styles = """
<style>
:root {
  color-scheme: dark;
  --page: #0b0c0e;
  --surface: #111316;
  --surface-raised: #15171a;
  --line: #292c30;
  --text: #f3f4f6;
  --muted: #92969d;
  --accent: #22c55e;
}
html, body, [class*="css"], button, input, select, textarea {
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.stApp { background: var(--page); color: var(--text); }
.block-container { max-width: 1440px; padding: 32px 32px 48px; }
[data-testid="stSidebar"] { background: var(--surface); border-right: 1px solid var(--line); }
[data-testid="stSidebar"] > div:first-child { padding: 24px 16px; }
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }
[data-testid="stToolbar"], [data-testid="stStatusWidget"] { visibility: hidden; }

h1, h2, h3 { color: var(--text); letter-spacing: -0.035em; }
h1 { font-size: clamp(1.75rem, 3vw, 2.25rem) !important; line-height: 1.2 !important; margin: 0 0 8px !important; }
h2 { font-size: 1.15rem !important; margin: 0 0 16px !important; }
p, [data-testid="stCaptionContainer"] { color: var(--muted); }
.app-subtitle { color: var(--muted); font-size: .9rem; margin: 0 0 24px; }
.section-label { color: var(--muted); font-size: .68rem; font-weight: 600; letter-spacing: .09em; text-transform: uppercase; }
.result-meta { color: var(--muted); font-size: .85rem; margin: 8px 0 16px; }

button, [data-testid="stBaseButton-secondary"], [data-testid="stDownloadButton"] button,
[data-testid="stFileUploaderDropzone"] button, div[data-baseweb="select"] > div,
input, [data-testid="stNumberInput"] button {
  border-radius: 4px !important;
  box-shadow: none !important;
}
div[data-baseweb="select"] > div, [data-testid="stNumberInput"] input {
  min-height: 40px; background: var(--surface-raised); border-color: var(--line);
}
[data-testid="stBaseButton-primary"] {
  background: var(--accent); border: 1px solid var(--accent); color: #07110a;
  font-weight: 600; min-height: 42px;
}
[data-testid="stBaseButton-primary"]:hover { background: #16a34a; border-color: #16a34a; color: #07110a; }
[data-testid="stFileUploader"] section {
  min-height: 76px; padding: 12px 16px; background: var(--surface);
  border: 1px dashed #3a3d42; border-radius: 4px;
}
[data-testid="stFileUploader"] section:hover { border-color: #5a5f66; }
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] { color: var(--muted); }
[data-testid="stFileUploader"] button { min-height: 32px; }

[data-testid="stSidebar"] [data-testid="stExpander"] {
  border: 0; border-top: 1px solid var(--line); border-radius: 0; background: transparent;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
  padding: 12px 0; color: var(--text); font-size: .78rem; font-weight: 600;
}
[data-testid="stSidebar"] [data-testid="stExpander"] details > div { padding: 0 0 16px; }
[data-testid="stSidebar"] [data-testid="stRadio"] label,
[data-testid="stSidebar"] [data-testid="stCheckbox"] label { font-size: .85rem; }
.palette-swatch {
  display: block; width: 28px; height: 28px; box-sizing: border-box;
  border: 1px solid #ffffff35; border-radius: 2px; opacity: .4;
}
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] button {
  min-height: 28px; padding: 0 4px; border: 0; background: transparent;
  color: var(--muted); font-size: .76rem;
}
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] button:hover {
  color: var(--text); background: transparent;
}

[data-testid="stVerticalBlockBorderWrapper"] {
  height: 100%; border: 1px solid var(--line); border-radius: 4px; background: var(--surface);
}
[data-testid="stImage"] img { border: 1px solid var(--line); border-radius: 2px; }
.parts-table { width: 100%; border-collapse: collapse; font-size: .86rem; }
.parts-table th { padding: 8px 4px; color: var(--muted); font-size: .74rem; font-weight: 500; text-align: left; border-bottom: 1px solid var(--line); }
.parts-table td { padding: 10px 4px; border-bottom: 1px solid var(--line); }
.parts-table th.num, .parts-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
.parts-table tfoot td { border-top: 1px solid #3a3d42; border-bottom: 0; font-weight: 600; }
.swatch-dot { display: inline-block; width: 12px; height: 12px; margin-right: 8px; vertical-align: -2px; border: 1px solid #ffffff30; border-radius: 2px; }
@media (max-width: 700px) { .block-container { padding: 24px 16px 32px; } }
</style>
""".replace("</style>", f"{color_swatch_rules}</style>")
st.markdown(styles, unsafe_allow_html=True)


# Sidebar
with st.sidebar:
    st.markdown('<div class="section-label">Settings</div>', unsafe_allow_html=True)

    with st.expander("Palette", expanded=True):
        mode_label = st.radio("Color mode", ["Color", "Grayscale"], horizontal=True)
        palette_mode = "color" if mode_label == "Color" else "grayscale"
        selected_colors = None
        if palette_mode == "color":
            select_all_col, clear_all_col = st.columns(2)
            select_all_col.button("Select all", on_click=set_color_selection, args=(True,))
            clear_all_col.button("Clear all", on_click=set_color_selection, args=(False,))
            swatch_columns = st.columns(6)
            selected_codes = []
            for index, color in enumerate(L.COLOR_PALETTE):
                with swatch_columns[index % 6]:
                    tooltip = html.escape(f"{color.name_en} ({color.code})", quote=True)
                    st.markdown(
                        f'<span class="palette-swatch" title="{tooltip}" '
                        f'style="background-color: {color.hex} !important"></span>',
                        unsafe_allow_html=True,
                    )
                    checked = st.checkbox(
                        f"{color.name_en} ({color.code})",
                        value=True,
                        key=f"use_color_{color.code}",
                        help=f"{color.name_en} ({color.code})",
                    )
                    if checked:
                        selected_codes.append(color.code)
            selected_colors = tuple(selected_codes)

    with st.expander("Format", expanded=True):
        grid_size = st.selectbox(
            "Format",
            [24, 30, 48, 60],
            index=2,
            format_func=lambda x: f"{x}×{x} studs" + (
                f" (4 tiles of {x // 2}×{x // 2})" if x in (48, 60) else " (1 plate)"
            ),
        )
        if palette_mode == "grayscale":
            thickness = st.number_input("Baseplate thickness (mm)", 0.4, 10.0, 1.6, 0.2)
            base = st.selectbox(
                "Baseplate color",
                [c.code for c in L.GRAYSCALE_PALETTE],
                format_func=lambda c: next(p.name_en for p in L.GRAYSCALE_PALETTE if p.code == c),
            )
        else:
            thickness, base = 1.6, "BK"

    with st.expander("Reserve", expanded=True):
        reserve = st.number_input("Reserve (%)", 0.0, 100.0, 5.0, 1.0)
        auto = st.checkbox("Auto-enhance contrast", value=True)
        loose_all = st.checkbox("Include loose studs (needed + reserve)", value=True)


# Main page
st.title("LEGO Mosaic → Bambu Lab 3D Print")
st.markdown(
    '<p class="app-subtitle">Upload an image, choose a palette and generate a printable mosaic.</p>',
    unsafe_allow_html=True,
)
upload = st.file_uploader(
    "Image (JPG/PNG)",
    type=["jpg", "jpeg", "png"],
    label_visibility="collapsed",
)

if upload is not None:
    try:
        L.load_image(io.BytesIO(upload.getvalue()))
    except L.MosaicError as exc:
        st.error(str(exc))
        st.stop()

    if st.button("Generate mosaic", type="primary"):
        opts = L.Options(
            grid=grid_size,
            palette_mode=palette_mode,
            selected_colors=selected_colors,
            reserve_pct=reserve,
            plate_thickness=thickness,
            base_color=base,
            dither=False,
            autocontrast=auto,
            loose_include_needed=loose_all,
        )
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


# Results
res = st.session_state.get("res")
if res:
    for warning in res.warnings:
        st.warning(warning)

    st.markdown(
        f'<div class="result-meta">Mosaic ready · {len(res.project_plate_names)} print plates</div>',
        unsafe_allow_html=True,
    )
    preview_col, parts_col = st.columns([1.2, 1], gap="large")

    with preview_col:
        with st.container(border=True):
            st.subheader("Mosaic preview")
            st.image(str(res.files["docs"][1]), use_container_width=True)

    with parts_col:
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
                    f'<td class="num">{row["needed"]}</td>'
                    f'<td class="num">{row["reserve_extra"]}</td>'
                    f'<td class="num">{row["total_to_print"]}</td>'
                    "</tr>"
                )
            total_needed = sum(row["needed"] for row in res.bom)
            total_reserve = sum(row["reserve_extra"] for row in res.bom)
            table_html = (
                '<table class="parts-table">'
                '<thead><tr><th>Color</th><th class="num">Needed</th>'
                '<th class="num">Reserve</th><th class="num">Total</th></tr></thead>'
                f'<tbody>{"".join(table_rows)}</tbody>'
                '<tfoot><tr><td>Total</td>'
                f'<td class="num">{total_needed}</td><td class="num">{total_reserve}</td>'
                f'<td class="num">{total_needed + total_reserve}</td></tr></tfoot></table>'
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
    st.download_button(
        "Download Bambu Studio project (.3MF)",
        project_file.read_bytes(),
        "lego_mosaic_bambu_project.3mf",
        "application/vnd.ms-package.3dmanufacturing-3dmodel+zip",
    )
