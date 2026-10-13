"""Streamlit interface for the LEGO mosaic generator."""
import io
import zipfile
from pathlib import Path

import streamlit as st

import lego_mosaic as L

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

st.set_page_config(page_title="LEGO Mosaic → 3D Print", page_icon="🧱", layout="wide")
st.title("🧱 LEGO Mosaic → Bambu Lab 3D Print")
st.caption("Upload an image and choose color or grayscale. The default format is 48×48 studs, split into four 24×24 tiles.")

with st.sidebar:
    st.header("Settings")
    mode_label = st.radio("Palette", ["Kleur", "Grijstinten"], horizontal=True)
    palette_mode = "color" if mode_label == "Kleur" else "grayscale"
    grid_size = st.selectbox("Format", [48, 30], index=0,
                             format_func=lambda x: f"{x}×{x} studs" + (" (1 plate)" if x == 30 else " (4 separate tiles of 24×24)"))
    reserve = st.number_input("Reserve (%)", 0.0, 100.0, 5.0, 1.0)
    if palette_mode == "grayscale":
        thickness = st.number_input("Baseplate thickness (mm)", 0.4, 10.0, 1.6, 0.2)
        base = st.selectbox("Baseplate color", [c.code for c in L.GRAYSCALE_PALETTE],
                            format_func=lambda c: next(p.name_en for p in L.GRAYSCALE_PALETTE if p.code == c))
    else:
        thickness, base = 1.6, "BK"
    dither = st.checkbox("Dithering (Floyd-Steinberg)", value=False)
    auto = st.checkbox("Auto-enhance contrast", value=True)
    loose_all = st.checkbox("Loose studs = needed + reserve", value=False)

upload = st.file_uploader("Image (JPG/PNG)", type=["jpg", "jpeg", "png"])

if upload is not None:
    try:
        L.load_image(io.BytesIO(upload.getvalue()))
    except L.MosaicError as exc:
        st.error(str(exc))
        st.stop()
    if st.button("Generate mosaic", type="primary"):
        opts = L.Options(grid=grid_size, palette_mode=palette_mode, reserve_pct=reserve,
                         plate_thickness=thickness, base_color=base,
                         dither=dither, autocontrast=auto, loose_include_needed=loose_all)
        try:
            with st.spinner("Generating (3D files may take a moment)…"):
                res = L.generate(io.BytesIO(upload.getvalue()), OUTPUT_DIR, options=opts)
        except L.MosaicError as exc:
            st.error(str(exc))
            st.stop()
        except Exception as exc:
            st.error(f"Unexpected error: {exc!r}")
            st.stop()
        st.session_state["res"] = res
        st.session_state["palette_mode"] = palette_mode

res = st.session_state.get("res")
if res:
    for w in res.warnings:
        st.warning(w)
    st.success(f"Done! {len(res.all_files())} files saved in `{res.out_dir}`")
    if st.session_state.get("palette_mode") == "color":
        st.caption("Per gebruikte kleur is een aparte printplaat gemaakt met precies het benodigde aantal studs. In kleurmodus wordt de baseplate niet meegeleverd.")
    else:
        st.caption("De mozaïekplaat gebruikt grijstinten en bevat de gekozen baseplatekleur.")
    c1, c2 = st.columns([1, 1])
    c1.image(str(res.files["docs"][1]), caption="Mosaic preview", use_container_width=True)
    c2.dataframe(
        [{"Code": r["code"], "Color": r["name_en"], "Needed": r["needed"],
          "Reserve": r["reserve_extra"], "Total": r["total_to_print"]} for r in res.bom],
        hide_index=True, use_container_width=True)
    st.image(str(res.files["docs"][0]), caption="Building instructions", use_container_width=True)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in res.all_files():
            z.write(p, p.relative_to(res.out_dir))
    st.download_button("⬇️ All files (ZIP)", buf.getvalue(), "lego_mosaic_output.zip", "application/zip")
