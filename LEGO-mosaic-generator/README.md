# LEGO-mozaïek → Bambu Lab 3D-print

## Installatie
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r requirements.txt

## Gebruik
Web-interface:  `streamlit run app.py`
CLI:            `python lego_mosaic.py foto.jpg --out output [--dither] [--reserve 10] [--loose-all]`

De stud wordt automatisch geladen uit `assets/` (`stud.stl`, `stud.obj` of `Lego-Stud.stl`).

## Uitvoer (map `output/`)
- `mosaic_plate.3mf` – 240×240 mm plaat, 1 object per kleur (AMS), extruder-nummers = palet-volgorde
  (1 Zwart, 2 Donkergrijs, 3 Lichtgrijs, 4 Wit, 5 Geel; Bambu AMS heeft 4 slots per unit → 2 units of een wissel nodig)
- `mosaic_plate.stl` – dezelfde plaat als één enkelkleurige mesh
- `spare_studs/` – losse reserve-studs op 256×256 bedden: `spare_multicolor_bedNN.3mf` en `spare_<kleur>_bedNN.stl`
- `building_instructions.png`, `mosaic_preview.png`
- `bill_of_materials.json` / `.txt`
