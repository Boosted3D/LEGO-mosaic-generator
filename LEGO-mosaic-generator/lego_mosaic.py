#!/usr/init/env python3
"""
lego_mosaic.py - Image -> LEGO Mosaic (30x30 or 48x48) + 3D Print Files (Bambu Lab)
==================================================================================
"""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

# --------------------------------------------------------------------------- #
# Constants & Palette
# --------------------------------------------------------------------------- #
PITCH_MM = 8.0       # LEGO stud pitch
BED_MM = 256.0       # Bambu Lab print bed (A1/P1/X1: 256 x 256 mm)
EDGE_MARGIN_MM = 5.0 # Keep every plate at least this far from printable-area edges
MIN_STUD_GAP_MM = 2.0 # Minimum clear horizontal space between separate studs
SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png"}


class MosaicError(Exception):
    """User-friendly error (wrong file, invalid setting, etc.)."""


@dataclass(frozen=True)
class LegoColor:
    code: str                 # short code for instructions
    name_nl: str
    name_en: str
    rgb: tuple[int, int, int]

    @property
    def hex(self) -> str:
        return "#%02X%02X%02X" % self.rgb


COLOR_PALETTE: tuple[LegoColor, ...] = (
    LegoColor("BK", "Zwart", "Black", (0, 0, 0)),
    LegoColor("DG", "Donkergrijs", "Dark Gray", (84, 84, 84)),
    LegoColor("JW", "Jadewit", "Jade White", (255, 255, 255)),
    LegoColor("BE", "Beige", "Beige", (247, 230, 222)),
    LegoColor("DT", "Desert Tan", "Desert Tan", (232, 219, 183)),
    LegoColor("BG", "Brons/Goud", "Bronze/Gold", (221, 161, 94)),
    LegoColor("CB", "Cacaobruin", "Cocoa Brown", (111, 80, 52)),
    LegoColor("SP", "Sakura-roze", "Sakura Pink", (232, 162, 168)),
    LegoColor("BL", "Kobaltblauw", "Cobalt Blue", (0, 86, 184)),
    LegoColor("GN", "Bambu groen", "Bambu Green", (0, 174, 66)),
    LegoColor("SY", "Zonnebloemgeel", "Sunflower Yellow", (254, 198, 0)),
    LegoColor("RD", "Rood", "Red", (193, 46, 31)),
)
GRAYSCALE_PALETTE: tuple[LegoColor, ...] = tuple(
    color for color in COLOR_PALETTE if color.code in {"BK", "DG", "JW"}
)
# Keep the full color palette as the default for existing API callers.
PALETTE: tuple[LegoColor, ...] = COLOR_PALETTE


def palette_for_mode(mode: str, selected_colors: tuple[str, ...] | None = None) -> tuple[LegoColor, ...]:
    if mode == "color":
        if selected_colors is None:
            return COLOR_PALETTE
        selected = set(selected_colors)
        return tuple(color for color in COLOR_PALETTE if color.code in selected)
    if mode == "grayscale":
        return GRAYSCALE_PALETTE
    raise MosaicError(f"Unknown palette mode '{mode}'.")


def filament_slot(color_code: str) -> int:
    """Return the stable, 1-based Bambu/Orca filament slot for a palette color."""
    for index, color in enumerate(COLOR_PALETTE, start=1):
        if color.code == color_code:
            return index
    raise MosaicError(f"Unknown filament color '{color_code}'.")


@dataclass
class Options:
    grid: int = 48                     # 24, 30, 48, or 60
    palette_mode: str = "color"        # "color" or "grayscale"
    selected_colors: tuple[str, ...] | None = None  # None means all colors
    pitch: float = PITCH_MM
    bed: float = BED_MM
    reserve_pct: float = 5.0           # extra studs in percentage
    dither: bool = False               # Floyd-Steinberg dithering
    autocontrast: bool = True          # stretch histogram for better results
    loose_include_needed: bool = False  # loose studs: reserve only (False) or all (True)
    loose_spacing: float = 10.0        # preferred center-to-center distance for loose studs (mm)
    bed_margin: float = EDGE_MARGIN_MM # free margin on print bed (mm)
    rotation_degrees: int = 0          # selected plate orientation, applied before fit checks
    scale_to_fit: bool = False         # explicit opt-in; never scale silently


# --------------------------------------------------------------------------- #
# Mesh Data Structure & I/O
# --------------------------------------------------------------------------- #
@dataclass
class Mesh:
    vertices: np.ndarray   # (N, 3) float64
    faces: np.ndarray      # (M, 3) int64

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def translated(self, offset) -> "Mesh":
        return Mesh(self.vertices + np.asarray(offset, dtype=float), self.faces)


def merge_meshes(meshes: list[Mesh]) -> Mesh:
    if not meshes:
        raise MosaicError("No meshes to merge.")
    verts, faces, off = [], [], 0
    for m in meshes:
        verts.append(m.vertices)
        faces.append(m.faces + off)
        off += len(m.vertices)
    return Mesh(np.vstack(verts), np.vstack(faces))


def _weld(triangles: np.ndarray) -> Mesh:
    flat = triangles.reshape(-1, 3)
    keys = np.round(flat, 5)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    faces = inv.reshape(-1, 3)
    ok = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    faces = faces[ok]
    if len(faces) == 0:
        raise MosaicError("The 3D file does not contain valid triangles.")
    return Mesh(uniq.astype(np.float64), faces.astype(np.int64))


def load_stl(path: Path) -> Mesh:
    data = path.read_bytes()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * n == len(data):
            dt = np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")])
            arr = np.frombuffer(data, dtype=dt, count=n, offset=84)
            return _weld(arr["v"].astype(np.float64).reshape(-1, 3, 3))
    text = data.decode("utf-8", errors="ignore")
    nums = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
    if not nums or len(nums) % 3:
        raise MosaicError(f"'{path.name}' is not a valid binary or ASCII STL file.")
    return _weld(np.array(nums, dtype=np.float64).reshape(-1, 3, 3))


def load_obj(path: Path) -> Mesh:
    verts: list[list[float]] = []
    tris: list[list[int]] = []
    for line in path.read_text(errors="ignore").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v" and len(parts) >= 4:
            verts.append([float(p) for p in parts[1:4]])
        elif parts[0] == "f" and len(parts) >= 4:
            idx = []
            for p in parts[1:]:
                i = int(p.split("/")[0])
                idx.append(i - 1 if i > 0 else len(verts) + i)
            for k in range(1, len(idx) - 1):
                tris.append([idx[0], idx[k], idx[k + 1]])
    if not verts or not tris:
        raise MosaicError(f"'{path.name}' contains no usable OBJ geometry.")
    v = np.array(verts, dtype=np.float64)
    return _weld(v[np.array(tris)])


def load_mesh(path: Path) -> Mesh:
    ext = path.suffix.lower()
    try:
        if ext == ".stl":
            return load_stl(path)
        if ext == ".obj":
            return load_obj(path)
    except MosaicError:
        raise
    except Exception as exc:
        raise MosaicError(f"Could not read '{path.name}': {exc}") from exc
    raise MosaicError(f"Unsupported 3D format '{ext}' (use .stl or .obj).")


def find_stud_file(assets_dir: Path) -> Path:
    if not assets_dir.is_dir():
        raise MosaicError(f"Assets directory not found: {assets_dir}")
    files = {p.name.lower(): p for p in assets_dir.iterdir() if p.is_file()}
    for name in ("stud.stl", "stud.obj", "lego-stud.stl", "lego-stud.obj"):
        if name in files:
            return files[name]
    others = sorted(p for n, p in files.items() if n.endswith((".stl", ".obj")))
    if others:
        return others[0]
    raise MosaicError(f"No stud file found in '{assets_dir}'.")


def load_stud(assets_dir: Path, pitch: float) -> tuple[Mesh, Path, list[str]]:
    path = find_stud_file(assets_dir)
    mesh = load_mesh(path)
    lo, hi = mesh.bounds()
    centre = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    mesh = mesh.translated(-centre)
    size = hi - lo
    warnings: list[str] = []
    if max(size[0], size[1]) > pitch:
        raise MosaicError(f"The stud is wider than the pitch ({pitch} mm).")
    return mesh, path, warnings


def tile_mesh(template: Mesh, positions: np.ndarray) -> Mesh:
    positions = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    k, nv = len(positions), len(template.vertices)
    verts = (template.vertices[None, :, :] + positions[:, None, :]).reshape(-1, 3)
    faces = (template.faces[None, :, :] + (np.arange(k) * nv)[:, None, None]).reshape(-1, 3)
    return Mesh(verts, faces)


def write_stl(mesh: Mesh, path: Path) -> None:
    tri = mesh.vertices[mesh.faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)
    dt = np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")])
    out = np.zeros(len(tri), dtype=dt)
    out["n"], out["v"] = n, tri.reshape(-1, 9)
    with open(path, "wb") as fh:
        fh.write(b"lego_mosaic.py".ljust(80, b"\0"))
        fh.write(struct.pack("<I", len(tri)))
        fh.write(out.tobytes())


@dataclass
class PrintObject:
    name: str
    mesh: Mesh
    rgb: tuple[int, int, int]
    extruder: int
    stud_centers: np.ndarray | None = None
    stud_cells: list[tuple[int, int]] | None = None


def write_3mf(path: Path, objects: list[PrintObject], title: str = "LEGO mosaic") -> None:
    if not objects:
        raise MosaicError("No objects to export to 3MF.")
    mats: list[tuple[str, tuple[int, int, int]]] = []
    for o in objects:
        if (o.name, o.rgb) not in mats:
            mats.append((o.name, o.rgb))

    xml: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n',
        f' <metadata name="Title">{escape(title)}</metadata>\n',
        ' <metadata name="Application">lego_mosaic.py</metadata>\n',
        " <resources>\n",
        '  <basematerials id="1">\n',
    ]
    for name, rgb in mats:
        xml.append('   <base name="%s" displaycolor="#%02X%02X%02XFF"/>\n' % ((escape(name),) + tuple(rgb)))
    xml.append("  </basematerials>\n")

    for i, o in enumerate(objects):
        oid = i + 2
        pidx = mats.index((o.name, o.rgb))
        xml.append(f'  <object id="{oid}" name="{escape(o.name)}" type="model" pid="1" pindex="{pidx}">\n')
        xml.append("   <mesh>\n    <vertices>\n")
        xml.extend(f'     <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>\n' for x, y, z in o.mesh.vertices)
        xml.append("    </vertices>\n    <triangles>\n")
        xml.extend(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>\n' for a, b, c in o.mesh.faces)
        xml.append("    </triangles>\n   </mesh>\n  </object>\n")
    xml.append(" </resources>\n <build>\n")
    for i in range(len(objects)):
        xml.append(f'  <item objectid="{i + 2}"/>\n')
    xml.append(" </build>\n</model>\n")

    cfg = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>\n']
    for i, o in enumerate(objects):
        cfg.append(
            f'  <object id="{i + 2}">\n'
            f'    <metadata key="name" value="{escape(o.name)}"/>\n'
            f'    <metadata key="extruder" value="{o.extruder}"/>\n'
            "  </object>\n"
        )
    cfg.append("</config>\n")

    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        ' <Default Extension="config" ContentType="text/xml"/>\n'
        "</Types>\n"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        "</Relationships>\n"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", "".join(xml))
        z.writestr("Metadata/model_settings.config", "".join(cfg))


def write_bambu_multi_plate_3mf(
    path: Path,
    plates: list[tuple[str, list[PrintObject]]],
    title: str = "LEGO mosaic",
    palette: tuple[LegoColor, ...] = COLOR_PALETTE,
    edge_margin: float = EDGE_MARGIN_MM,
    rotation_degrees: int = 0,
    scale_to_fit: bool = False,
) -> tuple[list[str], float, list[dict]]:
    """Write a Bambu Studio project using the object/plate structure in the
    supplied P1S reference project. Each input plate remains a separate plate;
    its objects keep their palette filament slot and all geometry is retained.
    """
    plates = [(name, objects) for name, objects in plates if objects]
    if not plates:
        raise MosaicError("No print plates were generated.")

    def xml_attr(value: str) -> str:
        return escape(value, {'"': "&quot;"})
    if len(palette) != 12:
        raise MosaicError("The Bambu P1S project requires the complete 12-color palette.")
    profile = _load_bambu_profile()
    bed_min_x, bed_min_y, bed_max_x, bed_max_y = _profile_bounds(profile, "printable_area")

    # Choose rotation before validating the printable-area margin. Current
    # plate contents are preserved as-is; no studs or cells are ever dropped.
    prepared_plates: list[tuple[str, list[PrintObject]]] = []
    bed_center = ((bed_min_x + bed_max_x) / 2.0, (bed_min_y + bed_max_y) / 2.0)
    for source_name, source_objects in plates:
        for source_object in source_objects:
            plate_name = source_name
            if len(source_objects) > 1:
                plate_name = f"{source_name} - {source_object.name.removeprefix('Studs ')}"
            rotated = _transform_print_object_xy(source_object, bed_center, rotation_degrees)
            prepared_plates.append((plate_name, [rotated]))
    plates = prepared_plates
    if not plates:
        raise MosaicError("No print plates were generated.")

    def check_fit(candidate: list[tuple[str, list[PrintObject]]]):
        report: list[dict] = []
        first_problem: tuple[str, str] | None = None
        for plate_name, plate_objects in candidate:
            distances = []
            for obj in plate_objects:
                fits, distance, reason = _plate_fit_report(obj, profile, edge_margin)
                distances.append(distance)
                if not fits and first_problem is None:
                    first_problem = (plate_name, reason or "unknown bed-fit error")
            report.append({"plate": plate_name, "clearance_mm": min(distances) if distances else 0.0})
        return first_problem, report

    problem, edge_clearance = check_fit(plates)
    applied_scale = 1.0
    if problem:
        if not scale_to_fit:
            raise MosaicError(_fit_message(problem[0], problem[1], edge_margin))

        def scaled_plates(factor: float) -> list[tuple[str, list[PrintObject]]]:
            return [
                (name, [_transform_print_object_xy(obj, bed_center, scale=factor) for obj in objects])
                for name, objects in plates
            ]

        low, high = 0.0, 1.0
        if check_fit(scaled_plates(0.001))[0] is not None:
            raise MosaicError(
                "The plates cannot clear this printer profile, even after uniform scaling. "
                "Choose a smaller format or lower the edge margin."
            )
        for _ in range(45):
            mid = (low + high) / 2.0
            if check_fit(scaled_plates(mid))[0] is None:
                low = mid
            else:
                high = mid
        applied_scale = low * (1.0 - 1e-8)
        plates = scaled_plates(applied_scale)
        problem, edge_clearance = check_fit(plates)
        if problem:
            raise MosaicError(_fit_message(problem[0], problem[1], edge_margin))

    # The uploaded, working P1S project supplies the full set of printer,
    # process and filament settings that Bambu Studio expects.
    template_path = Path(__file__).resolve().parent / "assets" / "bambu_p1s_project_settings.json"
    try:
        project_cfg = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MosaicError(f"Could not load the Bambu P1S project profile: {exc}") from exc

    slot_count = len(palette)
    project_cfg["filament_colour"] = [color.hex for color in palette]
    project_cfg["filament_self_index"] = [str(slot) for slot in range(1, slot_count + 1)]
    # The printer has one physical nozzle. Every palette filament maps to it;
    # the user changes filament between the separate color plates.
    project_cfg["filament_map"] = ["1"] * slot_count
    project_cfg["flush_volumes_matrix"] = [
        "0" if row == col else "300"
        for row in range(slot_count) for col in range(slot_count)
    ]
    project_cfg["flush_volumes_vector"] = ["140"] * (slot_count * 2)
    project_cfg["enable_prime_tower"] = "0"
    for key in ("wipe_tower_x", "wipe_tower_y"):
        values = project_cfg.get(key, ["165"] if key.endswith("_x") else ["250"])
        seed = values[-1] if values else ("165" if key.endswith("_x") else "250")
        project_cfg[key] = (values[:len(plates)] + [seed] * len(plates))[:len(plates)]

    wrappers: list[str] = []
    build_items: list[str] = []
    relationships: list[str] = []
    settings_objects: list[str] = []
    plate_configs: list[str] = []
    object_files: list[tuple[str, str]] = []
    wrapper_id = 2
    plate_columns = 3
    plate_stride = (bed_max_x - bed_min_x) * 1.2

    for plate_index, (plate_name, print_objects) in enumerate(plates):
        instance_xml: list[str] = []
        plate_x = (plate_index % plate_columns) * plate_stride
        plate_y = -(plate_index // plate_columns) * plate_stride

        for print_object in print_objects:
            if not 1 <= print_object.extruder <= slot_count:
                raise MosaicError(
                    f"Object '{print_object.name}' references filament slot {print_object.extruder}; "
                    f"the project defines {slot_count} slots."
                )
            if tuple(print_object.rgb) != palette[print_object.extruder - 1].rgb:
                raise MosaicError(
                    f"Object '{print_object.name}' filament slot does not match its palette color."
                )

            wrapper_uuid = str(uuid.uuid4())
            component_uuid = str(uuid.uuid4())
            item_uuid = str(uuid.uuid4())
            inner_id = wrapper_id - 1
            vertices = print_object.mesh.vertices
            faces = print_object.mesh.faces
            lo, hi = print_object.mesh.bounds()
            center_x = float((lo[0] + hi[0]) / 2.0)
            center_y = float((lo[1] + hi[1]) / 2.0)
            source_z = 0.0
            centered_vertices = vertices.copy()
            centered_vertices[:, 0] -= center_x
            centered_vertices[:, 1] -= center_y

            mesh_xml = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<model unit="millimeter" xml:lang="en-US" '
                'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
                'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
                'requiredextensions="p"><resources>',
                f'<object id="{inner_id}" type="model" p:UUID="{uuid.uuid4()}"><mesh><vertices>',
            ]
            mesh_xml.extend(
                f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>'
                for x, y, z in centered_vertices
            )
            mesh_xml.append("</vertices><triangles>")
            mesh_xml.extend(
                f'<triangle v1="{int(a)}" v2="{int(b)}" v3="{int(c)}"/>'
                for a, b, c in faces
            )
            mesh_xml.append("</triangles></mesh></object></resources></model>")
            object_filename = f"3D/Objects/object_{wrapper_id}.model"
            object_files.append((object_filename, "".join(mesh_xml)))

            component_path = f"/3D/Objects/object_{wrapper_id}.model"
            wrappers.append(
                f'<object id="{wrapper_id}" type="model" p:UUID="{wrapper_uuid}">'
                '<components>'
                f'<component p:path="{component_path}" objectid="{inner_id}" '
                f'transform="1 0 0 0 1 0 0 0 1 0 0 0" p:UUID="{component_uuid}"/>'
                '</components></object>'
            )
            relationships.append(
                f'<Relationship Target="/3D/Objects/object_{wrapper_id}.model" '
                f'Id="rel-{wrapper_id}" '
                'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            )
            build_items.append(
                f'<item objectid="{wrapper_id}" p:UUID="{item_uuid}" '
                f'transform="1 0 0 0 1 0 0 0 1 {plate_x + center_x:.6f} '
                f'{plate_y + center_y:.6f} 0" printable="1"/>'
            )

            safe_name = xml_attr(print_object.name)
            face_count = len(faces)
            settings_objects.append(
                f'<object id="{wrapper_id}">'
                f'<metadata key="name" value="{safe_name}"/>'
                f'<metadata key="extruder" value="{print_object.extruder}"/>'
                f'<metadata face_count="{face_count}"/>'
                f'<part id="{inner_id}" subtype="normal_part">'
                f'<metadata key="name" value="{safe_name}"/>'
                '<metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>'
                '<metadata key="source_object_id" value="0"/>'
                '<metadata key="source_volume_id" value="0"/>'
                f'<metadata key="source_offset_x" value="{center_x:.6f}"/>'
                f'<metadata key="source_offset_y" value="{center_y:.6f}"/>'
                f'<metadata key="source_offset_z" value="{source_z:.6f}"/>'
                f'<mesh_stat face_count="{face_count}" edges_fixed="0" '
                'degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>'
                '</part></object>'
            )
            instance_xml.append(
                '<model_instance>'
                f'<metadata key="object_id" value="{wrapper_id}"/>'
                '<metadata key="instance_id" value="0"/>'
                f'<metadata key="identify_id" value="{200 + plate_index * 10}"/>'
                '</model_instance>'
            )
            wrapper_id += 2

        safe_plate_name = re.sub(r'[<>:/\\|?*"]', "-", plate_name).strip() or f"Plate {plate_index + 1}"
        plate_configs.append(
            f'<plate><metadata key="plater_id" value="{plate_index + 1}"/>'
            f'<metadata key="plater_name" value="{xml_attr(safe_plate_name)}"/>'
            '<metadata key="locked" value="false"/>'
            '<metadata key="filament_map_mode" value="Auto For Flush"/>'
            f'<metadata key="filament_maps" value="{" ".join(["1"] * slot_count)}"/>'
            f'{"".join(instance_xml)}</plate>'
        )

    model_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
        'requiredextensions="p">'
        f'<metadata name="Title">{escape(title)}</metadata>'
        '<metadata name="Application">BambuStudio-02.00.03.54</metadata>'
        '<metadata name="BambuStudio:3mfVersion">1</metadata>'
        f'<resources>{"".join(wrappers)}</resources>'
        f'<build p:UUID="{uuid.uuid4()}">{"".join(build_items)}</build></model>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>'
    )
    model_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(relationships)}</Relationships>'
    )
    model_settings = (
        '<?xml version="1.0" encoding="UTF-8"?><config>'
        f'{"".join(settings_objects)}{"".join(plate_configs)}</config>'
    )
    cut_information = (
        '<?xml version="1.0" encoding="UTF-8"?><objects>'
        + "".join(
            f'<object id="{index}"><cut_id id="0" check_sum="1" connectors_cnt="0"/></object>'
            for index in range(1, len(object_files) + 1)
        )
        + '</objects>'
    )
    slice_info = (
        '<?xml version="1.0" encoding="UTF-8"?><config><header>'
        '<header_item key="X-BBL-Client-Type" value="slicer"/>'
        '<header_item key="X-BBL-Client-Version" value="02.00.03.54"/>'
        '</header></config>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Default Extension="gcode" ContentType="text/x.gcode"/>'
        '</Types>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", model_xml)
        archive.writestr("3D/_rels/3dmodel.model.rels", model_rels)
        for filename, model in object_files:
            archive.writestr(filename, model)
        archive.writestr("Metadata/model_settings.config", model_settings)
        archive.writestr(
            "Metadata/project_settings.config",
            json.dumps(project_cfg, ensure_ascii=False, indent=4),
        )
        archive.writestr("Metadata/slice_info.config", slice_info)
        archive.writestr("Metadata/cut_information.xml", cut_information)
    _validate_bambu_3mf(path, profile, edge_margin)
    return [name for name, _ in plates], applied_scale, edge_clearance


# --------------------------------------------------------------------------- #
# Image -> Raster -> Palette
# --------------------------------------------------------------------------- #
def load_image(source) -> Image.Image:
    try:
        if isinstance(source, (str, Path)):
            p = Path(source)
            if not p.is_file():
                raise MosaicError(f"Image not found: {p}")
        img = Image.open(source)
        img.load()
    except MosaicError:
        raise
    except Exception as exc:
        raise MosaicError(f"Could not open image: {exc}") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba)
    img = img.convert("RGB")
    return img


def center_crop_resize(img: Image.Image, n: int) -> Image.Image:
    w, h = img.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    return img.crop((left, top, left + s, top + s)).resize((n, n), Image.Resampling.LANCZOS)


def srgb_to_lab(rgb) -> np.ndarray:
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = (lin @ m.T) / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def _nearest(rgb, palette_lab: np.ndarray) -> np.ndarray:
    lab = srgb_to_lab(rgb)
    return ((lab[..., None, :] - palette_lab) ** 2).sum(-1).argmin(-1)


def quantize(img: Image.Image, dither: bool = False,
             palette: tuple[LegoColor, ...] = PALETTE) -> np.ndarray:
    arr = np.asarray(img, dtype=np.float64)
    palette_rgb = np.array([c.rgb for c in palette], dtype=np.float64)
    palette_lab = srgb_to_lab(palette_rgb)
    if not dither:
        return _nearest(arr, palette_lab).astype(np.int64)
    work = arr.copy()
    h, w, _ = work.shape
    idx = np.zeros((h, w), dtype=np.int64)
    for y in range(h):
        for x in range(w):
            old = np.clip(work[y, x], 0, 255)
            k = int(_nearest(old, palette_lab))
            idx[y, x] = k
            err = old - palette_rgb[k]
            if x + 1 < w:
                work[y, x + 1] += err * 7 / 16
            if y + 1 < h:
                if x > 0:
                    work[y + 1, x - 1] += err * 3 / 16
                work[y + 1, x] += err * 5 / 16
                if x + 1 < w:
                    work[y + 1, x + 1] += err * 1 / 16
    return idx


def count_studs(idx: np.ndarray, palette: tuple[LegoColor, ...] = PALETTE) -> list[int]:
    return [int((idx == i).sum()) for i in range(len(palette))]


def with_reserve(count: int, pct: float) -> int:
    return math.ceil(round(count * (100 + pct) / 100, 9))


# --------------------------------------------------------------------------- #
# 3D Construction
# --------------------------------------------------------------------------- #
def build_mosaic_tile_objects(sub_idx: np.ndarray, stud: Mesh, o: Options,
                             x_off_mm: float, y_off_mm: float, base_z: float,
                             palette: tuple[LegoColor, ...] = PALETTE) -> list[PrintObject]:
    n = sub_idx.shape[0]
    objs: list[PrintObject] = []
    for i, c in enumerate(palette):
        r_sub, c_sub = np.nonzero(sub_idx == i)
        if len(r_sub) > 0:
            x = x_off_mm + (c_sub + 0.5) * o.pitch
            y = y_off_mm + (n - 1 - r_sub + 0.5) * o.pitch
            z = np.full_like(x, base_z, dtype=float)
            pos = np.column_stack([x, y, z])
            objs.append(PrintObject(f"Studs {c.name_en}", tile_mesh(stud, pos), c.rgb,
                                    filament_slot(c.code), pos,
                                    [(int(r) + 1, int(col) + 1) for r, col in zip(r_sub, c_sub)]))
    return objs


def loose_layout(stud_w: float, o: Options) -> tuple[int, int, float, float]:
    usable = o.bed - 2 * o.bed_margin - stud_w
    if usable < 0:
        raise MosaicError("Print bed too small for the stud.")
    n = int(usable // o.loose_spacing) + 1
    span = (n - 1) * o.loose_spacing
    start = (o.bed - span) / 2
    return n, n, start, start


def loose_positions(count: int, stud_w: float, o: Options) -> list[np.ndarray]:
    cols, rows, x0, y0 = loose_layout(stud_w, o)
    cap = cols * rows
    beds = []
    for first in range(0, count, cap):
        k = min(cap, count - first)
        j = np.arange(k)
        x = x0 + (j % cols) * o.loose_spacing
        y = y0 + (j // cols) * o.loose_spacing
        beds.append(np.column_stack([x, y, np.zeros(k)]))
    return beds


def _profile_points(values) -> list[tuple[float, float]]:
    """Read Bambu's XxY polygon-coordinate lists without assuming a bed size."""
    if isinstance(values, str):
        values = re.split(r"[;,\s]+", values.strip())
    points: list[tuple[float, float]] = []
    for value in values or []:
        match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)x(-?\d+(?:\.\d+)?)\s*", str(value))
        if match:
            points.append((float(match.group(1)), float(match.group(2))))
    return points


def _load_bambu_profile(path: Path | None = None) -> dict:
    profile_path = path or Path(__file__).resolve().parent / "assets" / "bambu_p1s_project_settings.json"
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MosaicError(f"Could not load the Bambu printer profile: {exc}") from exc
    printable = _profile_points(profile.get("printable_area", []))
    if len(printable) < 3:
        raise MosaicError("The selected printer profile has no valid printable_area polygon.")
    return profile


def _profile_bounds(profile: dict, key: str) -> tuple[float, float, float, float]:
    points = _profile_points(profile.get(key, []))
    if not points:
        if key == "bed_exclude_area":
            return (math.inf, math.inf, -math.inf, -math.inf)
        raise MosaicError(f"The printer profile has no valid {key} polygon.")
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Return true for points inside or on the boundary of a profile polygon."""
    inside = False
    count = len(polygon)
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % count]
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) < 1e-8 and min(x1, x2) - 1e-8 <= x <= max(x1, x2) + 1e-8 and min(y1, y2) - 1e-8 <= y <= max(y1, y2) + 1e-8:
            return True
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
    return inside


def _point_segment_distance(
    x: float, y: float, start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(x - start[0], y - start[1])
    t = max(0.0, min(1.0, ((x - start[0]) * dx + (y - start[1]) * dy) / length_sq))
    return math.hypot(x - (start[0] + t * dx), y - (start[1] + t * dy))


def _distance_to_polygon_edges(x: float, y: float, polygon: list[tuple[float, float]]) -> float:
    return min(
        _point_segment_distance(x, y, start, polygon[(index + 1) % len(polygon)])
        for index, start in enumerate(polygon)
    )


def _profile_safe_positions(
    count: int,
    stud_mesh: Mesh,
    spacing: float,
    profile: dict,
    edge_margin: float = EDGE_MARGIN_MM,
    safety_margin: float = 0.5,
) -> list[tuple[np.ndarray, list[tuple[int, int]]]]:
    """Pack studs into a bed grid while skipping any excluded or out-of-bed cell."""
    if count <= 0:
        return []
    printable_min_x, printable_min_y, printable_max_x, printable_max_y = _profile_bounds(profile, "printable_area")
    printable_polygon = _profile_points(profile.get("printable_area", []))
    exclude_min_x, exclude_min_y, exclude_max_x, exclude_max_y = _profile_bounds(profile, "bed_exclude_area")
    stud_min, stud_max = stud_mesh.bounds()
    half_x = float((stud_max[0] - stud_min[0]) / 2.0)
    half_y = float((stud_max[1] - stud_min[1]) / 2.0)
    # Enforce the requested physical clearance even if a caller passes an old
    # spacing value or uses a stud mesh wider than the bundled 7.62 mm model.
    # A small epsilon avoids rounding the exported coordinates below 2.00 mm.
    spacing = max(
        float(spacing),
        float(max(stud_max[0] - stud_min[0], stud_max[1] - stud_min[1]))
        + MIN_STUD_GAP_MM + 0.02,
    )

    safe_min_x, safe_max_x = printable_min_x + edge_margin, printable_max_x - edge_margin
    safe_min_y, safe_max_y = printable_min_y + edge_margin, printable_max_y - edge_margin
    cols = int(max(0, (safe_max_x - safe_min_x - 2 * half_x) // spacing)) + 1
    rows = int(max(0, (safe_max_y - safe_min_y - 2 * half_y) // spacing)) + 1
    if not cols or not rows:
        raise MosaicError(
            f"No plate fits with an edge margin of {edge_margin:g} mm. Nothing was scaled or removed. "
            "Choose a smaller format/plate, enable uniform scaling, or lower the edge margin."
        )
    span_x, span_y = (cols - 1) * spacing, (rows - 1) * spacing
    x0 = (safe_min_x + safe_max_x - span_x) / 2.0
    y0 = (safe_min_y + safe_max_y - span_y) / 2.0

    safe_slots: list[tuple[float, float, int, int]] = []
    for row in range(rows):
        cy = y0 + row * spacing
        bottom, top = cy + stud_min[1], cy + stud_max[1]
        if bottom < safe_min_y or top > safe_max_y:
            continue
        for col in range(cols):
            cx = x0 + col * spacing
            left, right = cx + stud_min[0], cx + stud_max[0]
            footprint_corners = ((left, bottom), (left, top), (right, bottom), (right, top))
            if (left < safe_min_x or right > safe_max_x
                    or bottom < safe_min_y or top > safe_max_y
                    or any(not _point_in_polygon(px, py, printable_polygon)
                           or _distance_to_polygon_edges(px, py, printable_polygon) < edge_margin
                           for px, py in footprint_corners)):
                continue
            hits_exclusion = (
                left <= exclude_max_x + safety_margin
                and right >= exclude_min_x - safety_margin
                and bottom <= exclude_max_y + safety_margin
                and top >= exclude_min_y - safety_margin
            )
            if not hits_exclusion:
                safe_slots.append((cx, cy, row + 1, col + 1))
    if not safe_slots:
        raise MosaicError(
            f"No stud positions clear the printer exclusion area with a {edge_margin:g} mm edge margin. "
            "Nothing was scaled or removed. Choose a smaller format/plate, enable uniform scaling, or lower the margin."
        )

    capacity = len(safe_slots)
    result: list[tuple[np.ndarray, list[tuple[int, int]]]] = []
    for start in range(0, count, capacity):
        slots = safe_slots[:min(capacity, count - start)]
        positions = np.asarray([(x, y, 0.0) for x, y, _, _ in slots], dtype=np.float64)
        cells = [(row, col) for _, _, row, col in slots]
        result.append((positions, cells))
    return result


def _transform_print_object_xy(
    obj: PrintObject,
    center: tuple[float, float],
    rotation_degrees: int = 0,
    scale: float = 1.0,
) -> PrintObject:
    """Apply the chosen plate rotation and optional uniform XY scale to a copy."""
    angle = math.radians(rotation_degrees % 360)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    rotation = np.asarray(((cos_a, -sin_a), (sin_a, cos_a)), dtype=np.float64)

    def transform(points: np.ndarray) -> np.ndarray:
        out = np.asarray(points, dtype=np.float64).copy()
        out[:, :2] = (out[:, :2] - center) @ rotation.T
        out[:, :2] *= scale
        out[:, :2] += center
        return out

    centers = None if obj.stud_centers is None else transform(obj.stud_centers)
    return PrintObject(
        obj.name,
        Mesh(transform(obj.mesh.vertices), obj.mesh.faces.copy()),
        obj.rgb,
        obj.extruder,
        centers,
        None if obj.stud_cells is None else list(obj.stud_cells),
    )


def _plate_fit_report(
    obj: PrintObject,
    profile: dict,
    edge_margin: float,
    safety_margin: float = 0.5,
) -> tuple[bool, float, str | None]:
    """Validate a whole plate object; never trim studs or cells."""
    if obj.stud_centers is None or len(obj.stud_centers) == 0:
        raise MosaicError(f"Cannot verify bed clearance for '{obj.name}': stud positions are missing.")
    centers = np.asarray(obj.stud_centers, dtype=np.float64).reshape(-1, 3)
    if len(obj.mesh.vertices) % len(centers) or len(obj.mesh.faces) % len(centers):
        raise MosaicError(f"Cannot verify bed clearance for '{obj.name}': mesh is not grouped by stud.")

    vertices_per_stud = len(obj.mesh.vertices) // len(centers)
    if not vertices_per_stud:
        raise MosaicError(f"'{obj.name}' contains incomplete stud geometry.")
    lo, hi = obj.mesh.bounds()
    bed_min_x, bed_min_y, bed_max_x, bed_max_y = _profile_bounds(profile, "printable_area")
    polygon = _profile_points(profile.get("printable_area", []))
    clearance = min(
        _distance_to_polygon_edges(float(x), float(y), polygon)
        for x, y in obj.mesh.vertices[:, :2]
    )
    width, height = float(hi[0] - lo[0]), float(hi[1] - lo[1])
    dimensions_fit = width <= bed_max_x - bed_min_x - 2 * edge_margin + 1e-7
    dimensions_fit &= height <= bed_max_y - bed_min_y - 2 * edge_margin + 1e-7
    boundary_fit = clearance + 1e-7 >= edge_margin
    corners = ((lo[0], lo[1]), (lo[0], hi[1]), (hi[0], lo[1]), (hi[0], hi[1]))
    polygon_fit = all(_point_in_polygon(float(x), float(y), polygon) for x, y in corners)

    excl_min_x, excl_min_y, excl_max_x, excl_max_y = _profile_bounds(profile, "bed_exclude_area")
    intersects_exclusion = False
    for index, center in enumerate(centers):
        stud_vertices = obj.mesh.vertices[index * vertices_per_stud:(index + 1) * vertices_per_stud]
        stud_lo, stud_hi = stud_vertices[:, :2].min(axis=0), stud_vertices[:, :2].max(axis=0)
        if (stud_lo[0] <= excl_max_x + safety_margin and stud_hi[0] >= excl_min_x - safety_margin
                and stud_lo[1] <= excl_max_y + safety_margin and stud_hi[1] >= excl_min_y - safety_margin):
            intersects_exclusion = True
            break

    reasons = []
    if not dimensions_fit:
        reasons.append(f"object size {width:.2f}×{height:.2f} mm exceeds bed size minus two margins")
    if not boundary_fit or not polygon_fit:
        reasons.append(f"smallest edge clearance is {clearance:.2f} mm")
    if intersects_exclusion:
        reasons.append("object intersects the printer exclusion area")
    return not reasons, clearance, "; ".join(reasons) if reasons else None


def _fit_message(plate_name: str, reasons: str, edge_margin: float) -> str:
    return (
        f"Plate '{plate_name}' does not fit the selected printer profile ({reasons}). "
        f"Required edge clearance: at least {edge_margin:g} mm. Nothing was scaled and no studs were removed. "
        "Choose one: (a) reduce the format/number of studs per plate (for example 30×30), "
        "(b) enable 'Uniformly scale plates to fit' to scale all plates together and report the new stud spacing, "
        "or (c) lower 'Edge margin (mm)'."
    )


def _validate_bambu_3mf(path: Path, profile: dict, edge_margin: float = EDGE_MARGIN_MM) -> None:
    """Check the generated package, references, mesh indices, slots and bed bounds."""
    core_ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    p_ns = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
    ns = {"c": core_ns, "p": p_ns}
    with zipfile.ZipFile(path, "r") as archive:
        bad_entry = archive.testzip()
        if bad_entry:
            raise MosaicError(f"The generated 3MF archive is corrupt at {bad_entry}.")
        names = set(archive.namelist())
        required = {
            "[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model",
            "3D/_rels/3dmodel.model.rels", "Metadata/model_settings.config",
            "Metadata/project_settings.config", "Metadata/slice_info.config",
            "Metadata/cut_information.xml",
        }
        if not required.issubset(names):
            raise MosaicError("The generated 3MF is missing required Bambu Studio files.")
        for name in names:
            if name.endswith((".model", ".config", ".xml", ".rels")) and name != "Metadata/project_settings.config":
                try:
                    ET.fromstring(archive.read(name))
                except ET.ParseError as exc:
                    raise MosaicError(f"Invalid XML in {name}: {exc}") from exc
        root = ET.fromstring(archive.read("3D/3dmodel.model"))
        model_rels = ET.fromstring(archive.read("3D/_rels/3dmodel.model.rels"))
        rel_targets = {
            relation.get("Target", "").lstrip("/")
            for relation in model_rels
            if relation.get("Type", "").endswith("/2013/01/3dmodel")
        }
        wrapper_to_mesh: dict[str, tuple[str, str]] = {}
        for wrapper in root.findall("c:resources/c:object", ns):
            wrapper_id = wrapper.get("id", "")
            component = wrapper.find("c:components/c:component", ns)
            if component is None:
                raise MosaicError(f"Wrapper object {wrapper_id} has no mesh component.")
            object_path = component.get(f"{{{p_ns}}}path", "").lstrip("/")
            inner_id = component.get("objectid", "")
            if object_path not in names or object_path not in rel_targets:
                raise MosaicError(f"Wrapper object {wrapper_id} points to a missing mesh file.")
            inner_root = ET.fromstring(archive.read(object_path))
            inner_object = next(
                (obj for obj in inner_root.findall("c:resources/c:object", ns)
                 if obj.get("id") == inner_id),
                None,
            )
            if inner_object is None:
                raise MosaicError(f"Component object {inner_id} is missing from {object_path}.")
            vertices = inner_object.findall("c:mesh/c:vertices/c:vertex", ns)
            triangles = inner_object.findall("c:mesh/c:triangles/c:triangle", ns)
            for triangle in triangles:
                for key in ("v1", "v2", "v3"):
                    vertex_index = int(triangle.get(key, "-1"))
                    if vertex_index < 0 or vertex_index >= len(vertices):
                        raise MosaicError(f"A mesh index in {object_path} exceeds its vertex count.")
            wrapper_to_mesh[wrapper_id] = (object_path, inner_id)

        model_settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
        settings_objects = {
            item.get("id", ""): item for item in model_settings.findall("object")
        }
        plates = model_settings.findall("plate")
        if len(plates) != len(wrapper_to_mesh):
            raise MosaicError("Each Bambu plate must contain exactly one model object.")
        printable_min_x, printable_min_y, printable_max_x, printable_max_y = _profile_bounds(profile, "printable_area")
        printable_polygon = _profile_points(profile.get("printable_area", []))
        exclude_min_x, exclude_min_y, exclude_max_x, exclude_max_y = _profile_bounds(profile, "bed_exclude_area")
        for plate in plates:
            instances = plate.findall("model_instance")
            if len(instances) != 1:
                raise MosaicError("Each Bambu plate must contain exactly one model instance.")
            object_id = next(
                (meta.get("value", "") for meta in instances[0].findall("metadata")
                 if meta.get("key") == "object_id"),
                "",
            )
            if object_id not in wrapper_to_mesh or object_id not in settings_objects:
                raise MosaicError(f"Plate references unknown wrapper object {object_id}.")
            obj_settings = settings_objects[object_id]
            extruder = next(
                (meta.get("value", "") for meta in obj_settings.findall("metadata")
                 if meta.get("key") == "extruder"),
                "",
            )
            if not extruder.isdigit() or not 1 <= int(extruder) <= len(COLOR_PALETTE):
                raise MosaicError(f"Object {object_id} has an invalid filament slot.")
            part = obj_settings.find("part")
            if part is None:
                raise MosaicError(f"Object {object_id} has no part block.")
            source_x = source_y = 0.0
            for meta in part.findall("metadata"):
                if meta.get("key") == "source_offset_x":
                    source_x = float(meta.get("value", "0"))
                elif meta.get("key") == "source_offset_y":
                    source_y = float(meta.get("value", "0"))
            object_path, inner_id = wrapper_to_mesh[object_id]
            inner_root = ET.fromstring(archive.read(object_path))
            inner = next(obj for obj in inner_root.findall("c:resources/c:object", ns) if obj.get("id") == inner_id)
            world_points = []
            for vertex in inner.findall("c:mesh/c:vertices/c:vertex", ns):
                x = float(vertex.get("x", "0")) + source_x
                y = float(vertex.get("y", "0")) + source_y
                world_points.append((x, y))
                if (not printable_min_x <= x <= printable_max_x
                        or not printable_min_y <= y <= printable_max_y
                        or not _point_in_polygon(x, y, printable_polygon)):
                    raise MosaicError(f"Object {object_id} extends outside the selected printable area.")
                if _distance_to_polygon_edges(x, y, printable_polygon) + 1e-7 < edge_margin:
                    raise MosaicError(
                        f"Object {object_id} is less than {edge_margin:g} mm from a printable-area edge."
                    )
                if (exclude_min_x - 0.5 <= x <= exclude_max_x + 0.5
                        and exclude_min_y - 0.5 <= y <= exclude_max_y + 0.5):
                    raise MosaicError(f"Object {object_id} has a vertex in the printer exclusion area.")
            if world_points:
                width = max(x for x, _ in world_points) - min(x for x, _ in world_points)
                height = max(y for _, y in world_points) - min(y for _, y in world_points)
                if (width > printable_max_x - printable_min_x - 2 * edge_margin + 1e-7
                        or height > printable_max_y - printable_min_y - 2 * edge_margin + 1e-7):
                    raise MosaicError(f"Object {object_id} exceeds printable dimensions after applying the edge margin.")

        project_cfg = json.loads(archive.read("Metadata/project_settings.config"))
        slot_count = len(COLOR_PALETTE)
        colors = [color.hex for color in COLOR_PALETTE]
        if project_cfg.get("filament_colour") != colors:
            raise MosaicError("The project profile does not contain the exact 12-color palette.")
        if project_cfg.get("filament_map") != ["1"] * slot_count:
            raise MosaicError("Filament slots must map to the single P1S nozzle.")
        if len(project_cfg.get("flush_volumes_matrix", [])) != slot_count * slot_count:
            raise MosaicError("The filament flush matrix must contain 144 values.")
        if len(project_cfg.get("flush_volumes_vector", [])) != slot_count * 2:
            raise MosaicError("The filament flush vector must contain 24 values.")
        if len(project_cfg.get("wipe_tower_x", [])) != len(plates) or len(project_cfg.get("wipe_tower_y", [])) != len(plates):
            raise MosaicError("Wipe tower coordinates must have one value per plate.")

        cut_info = ET.fromstring(archive.read("Metadata/cut_information.xml"))
        if len(cut_info.findall("object")) != len(wrapper_to_mesh):
            raise MosaicError("Cut information must contain one entry per exported object.")


# --------------------------------------------------------------------------- #
# Instructions, Preview & BOM
# --------------------------------------------------------------------------- #
def _font(size: int):
    for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "Arial.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _text_color(rgb) -> tuple[int, int, int]:
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return (0, 0, 0) if lum > 140 else (255, 255, 255)


def render_instructions(idx: np.ndarray, bom: list[dict], path: Path, cell: int = 34,
                        palette: tuple[LegoColor, ...] = PALETTE) -> None:
    n = idx.shape[0]
    m = 48
    legend_h = 70 + len(palette) * 36
    w, h = 2 * m + n * cell, 2 * m + n * cell + legend_h
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    f_small, f_cell, f_head = _font(14), _font(13), _font(20)

    for r in range(n):
        for c in range(n):
            col = palette[idx[r, c]]
            x, y = m + c * cell, m + r * cell
            d.rectangle([x, y, x + cell, y + cell], fill=col.rgb)
            d.text((x + cell / 2, y + cell / 2), col.code, font=f_cell,
                   fill=_text_color(col.rgb), anchor="mm")
    for i in range(n + 1):
        wd = 3 if i % 5 == 0 else 1
        d.line([m + i * cell, m, m + i * cell, m + n * cell], fill=(60, 60, 60), width=wd)
        d.line([m, m + i * cell, m + n * cell, m + i * cell], fill=(60, 60, 60), width=wd)
    for i in range(n):
        lbl = str(i + 1)
        p = m + i * cell + cell / 2
        d.text((p, m / 2), lbl, font=f_small, fill="black", anchor="mm")
        d.text((p, m + n * cell + m / 2), lbl, font=f_small, fill="black", anchor="mm")
        d.text((m / 2, p), lbl, font=f_small, fill="black", anchor="mm")
        d.text((m + n * cell + m / 2, p), lbl, font=f_small, fill="black", anchor="mm")

    y0 = 2 * m + n * cell + 6
    d.text((m, y0), f"Building Instructions ({n}x{n})", font=f_head, fill="black")
    y = y0 + 40
    d.text((m + 50, y), "Color", font=f_small, fill="black")
    for x, t in ((m + 330, "Needed"), (m + 430, "Reserve"), (m + 540, "Total to print")):
        d.text((x, y), t, font=f_small, fill="black")
    y += 26
    for row, col in zip(bom, palette):
        d.rectangle([m, y, m + 36, y + 26], fill=col.rgb, outline="black")
        d.text((m + 18, y + 13), col.code, font=f_cell, fill=_text_color(col.rgb), anchor="mm")
        d.text((m + 50, y + 5), f"{col.name_en}", font=f_small, fill="black")
        d.text((m + 330, y + 5), str(row["needed"]), font=f_small, fill="black")
        d.text((m + 430, y + 5), f"+{row['reserve_extra']}", font=f_small, fill="black")
        d.text((m + 540, y + 5), str(row["total_to_print"]), font=f_small, fill="black")
        y += 36
    img.save(path)


def render_preview(idx: np.ndarray, path: Path, cell: int = 20,
                   palette: tuple[LegoColor, ...] = PALETTE) -> None:
    n = idx.shape[0]
    img = Image.new("RGB", (n * cell, n * cell))
    d = ImageDraw.Draw(img)
    for r in range(n):
        for c in range(n):
            x, y = c * cell, r * cell
            d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=palette[idx[r, c]].rgb)
            d.ellipse([x + 3, y + 3, x + cell - 4, y + cell - 4], outline=(0, 0, 0, 60), width=1)
    img.save(path)


def make_bom(counts: list[int], reserve_pct: float,
             palette: tuple[LegoColor, ...] = PALETTE) -> list[dict]:
    rows = []
    for c, cnt in zip(palette, counts):
        total = with_reserve(cnt, reserve_pct)
        rows.append({"code": c.code, "name_nl": c.name_nl, "name_en": c.name_en,
                     "rgb": list(c.rgb), "hex": c.hex, "needed": cnt,
                     "reserve_extra": total - cnt, "total_to_print": total})
    return rows


def write_bom(bom: list[dict], idx: np.ndarray, o: Options, stud_file: str, out: Path,
              palette: tuple[LegoColor, ...] = PALETTE) -> tuple[Path, Path]:
    n = o.grid
    tot_needed = sum(r["needed"] for r in bom)
    tot_extra = sum(r["reserve_extra"] for r in bom)
    data = {
        "grid": f"{n}x{n}", "positions": n * n, "stud_pitch_mm": o.pitch,
        "plate_size_mm": [n * o.pitch, n * o.pitch],
        "reserve_percent": o.reserve_pct, "stud_model": stud_file,
        "colors": bom,
        "totals": {"needed": tot_needed, "reserve_extra": tot_extra,
                   "total_to_print": tot_needed + tot_extra},
        "palette_mode": o.palette_mode,
        "layout_rows_top_to_bottom": ["".join(palette[i].code.ljust(3) for i in row).rstrip() for row in idx],
    }
    jp, tp = out / "bill_of_materials.json", out / "bill_of_materials.txt"
    jp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [f"BILL OF MATERIALS - {n}x{n} LEGO Mosaic ({n * n} positions, +{o.reserve_pct:g}% reserve)",
             "=" * 66,
             f"{'Code':<5}{'Color':<14}{'Needed':>8}{'Reserve':>10}{'Total':>10}", "-" * 66]
    for r in bom:
        lines.append(f"{r['code']:<5}{r['name_en']:<14}{r['needed']:>8}{'+' + str(r['reserve_extra']):>10}{r['total_to_print']:>10}")
    lines += ["-" * 66, f"{'':<19}{tot_needed:>8}{'+' + str(tot_extra):>10}{tot_needed + tot_extra:>10}",
              "", f"Plate: {n * o.pitch:g} x {n * o.pitch:g} mm, pitch {o.pitch:g} mm, stud: {stud_file}"]
    tp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jp, tp


# --------------------------------------------------------------------------- #
# Main Generator
# --------------------------------------------------------------------------- #
@dataclass
class Result:
    out_dir: Path
    idx: np.ndarray
    bom: list[dict]
    files: dict[str, list[Path]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    project_plate_names: list[str] = field(default_factory=list)
    plate_edge_clearance: list[dict] = field(default_factory=list)
    uniform_scale: float = 1.0

    def all_files(self) -> list[Path]:
        return [p for v in self.files.values() for p in v]


def _validate(o: Options) -> None:
    palette = palette_for_mode(o.palette_mode, o.selected_colors)
    if o.palette_mode == "color" and not palette:
        raise MosaicError("Select at least one color to generate the mosaic.")
    if o.reserve_pct < 0:
        raise MosaicError("Reserve percentage cannot be negative.")
    if o.bed_margin < 0:
        raise MosaicError("Edge margin cannot be negative.")
    if o.rotation_degrees not in {0, 90, 180, 270}:
        raise MosaicError("Plate rotation must be 0°, 90°, 180°, or 270°.")


def _filename_slug(value: str) -> str:
    """Make a readable filename part without path separators or punctuation."""
    return re.sub(r"[^a-z0-9_-]+", "_", value.lower()).strip("_")


def generate(image_source, out_dir: str | Path = "output",
             assets_dir: str | Path | None = None, options: Options | None = None) -> Result:
    o = options or Options()
    here = Path(__file__).resolve().parent
    profile = _load_bambu_profile(here / "assets" / "bambu_p1s_project_settings.json")
    bed_min_x, bed_min_y, bed_max_x, bed_max_y = _profile_bounds(profile, "printable_area")
    o.bed = bed_max_x - bed_min_x
    _validate(o)
    palette = palette_for_mode(o.palette_mode, o.selected_colors)
    assets = Path(assets_dir) if assets_dir else here / "assets"
    out = Path(out_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MosaicError(f"Cannot create output directory '{out}': {exc}") from exc

    res = Result(out, np.zeros((o.grid, o.grid), dtype=int), [])
    project_plates: list[tuple[str, list[PrintObject]]] = []

    img = load_image(image_source)
    small = center_crop_resize(img, o.grid)
    if o.autocontrast:
        small = ImageOps.autocontrast(small, cutoff=1)
    idx = quantize(small, o.dither, palette)
    res.idx = idx

    counts = count_studs(idx, palette)
    res.bom = make_bom(counts, o.reserve_pct, palette)
    stud, stud_path, warns = load_stud(assets, o.pitch)
    res.warnings += warns
    stud_w = float(max(stud.bounds()[1][:2] - stud.bounds()[0][:2]))

    if o.grid in (48, 60):
        half = o.grid // 2
        tile_size_mm = half * o.pitch
        origin_x = (bed_min_x + bed_max_x - tile_size_mm) / 2
        origin_y = (bed_min_y + bed_max_y - tile_size_mm) / 2
        plate_files = []
        tile_names = ("Top-left", "Top-right", "Bottom-left", "Bottom-right")
        for tile_number, (r_idx, c_idx) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1)), start=1):
            if o.palette_mode == "grayscale":
                sub = idx[r_idx*half:(r_idx+1)*half, c_idx*half:(c_idx+1)*half]
                tile_objs = build_mosaic_tile_objects(sub, stud, o, origin_x, origin_y, 0.0, palette)
                for tobj in tile_objs:
                    tobj.name = f"{tile_names[tile_number - 1]} - {tobj.name}"
                project_plates.append((f"Mosaic - {tile_names[tile_number - 1]}", tile_objs))
                p3mf = out / f"mosaic_plate_{o.grid}x{o.grid}_tile_{tile_number}.3mf"
                pstl = out / f"mosaic_plate_{o.grid}x{o.grid}_tile_{tile_number}.stl"
                write_3mf(p3mf, tile_objs, f"LEGO mosaic {o.grid}x{o.grid} tile {tile_number}")
                write_stl(merge_meshes([ob.mesh for ob in tile_objs]), pstl)
                plate_files.extend([p3mf, pstl])

        if o.palette_mode == "grayscale":
            res.files["plate"] = plate_files
    else:
        if o.palette_mode == "grayscale":
            size = o.grid * o.pitch
            origin_x = (bed_min_x + bed_max_x - size) / 2
            origin_y = (bed_min_y + bed_max_y - size) / 2
            tile_objs = build_mosaic_tile_objects(idx, stud, o, origin_x, origin_y, 0.0, palette)
            project_plates.append((f"Mosaic {o.grid}x{o.grid}", tile_objs))
            p3mf, pstl = out / f"mosaic_plate_{o.grid}x{o.grid}.3mf", out / f"mosaic_plate_{o.grid}x{o.grid}.stl"
            write_3mf(p3mf, tile_objs, f"LEGO mosaic {o.grid}x{o.grid}")
            write_stl(merge_meshes([ob.mesh for ob in tile_objs]), pstl)
            res.files["plate"] = [p3mf, pstl]

    spare_dir = out / "spare_studs"
    spare_dir.mkdir(exist_ok=True)
    for old in spare_dir.glob("spare_*"):
        old.unlink()
    per_color = [(r["total_to_print"] if o.loose_include_needed else r["reserve_extra"]) for r in res.bom]

    stl_files = []
    for i, (c, k) in enumerate(zip(palette, per_color)):
        safe_beds = _profile_safe_positions(k, stud, o.loose_spacing, profile, o.bed_margin)
        for b, (pos, _) in enumerate(safe_beds, start=1):
            fp = spare_dir / f"spare_{c.code}_{_filename_slug(c.name_en)}_bed{b:02d}.stl"
            write_stl(tile_mesh(stud, pos), fp)
            stl_files.append(fp)

    seq = [(i, k) for i, k in enumerate(per_color) if k > 0]
    total = sum(k for _, k in seq)
    mc_files = []
    if total:
        beds = [positions for positions, _ in _profile_safe_positions(
            total, stud, o.loose_spacing, profile, o.bed_margin
        )]
        color_of = np.concatenate([np.full(k, i) for i, k in seq])
        cursor = 0
        for b, pos in enumerate(beds, start=1):
            cols_here = color_of[cursor:cursor + len(pos)]
            cursor += len(pos)
            bed_objs = []
            for i in np.unique(cols_here):
                c = palette[i]
                bed_objs.append(PrintObject(f"Studs {c.name_en}",
                                            tile_mesh(stud, pos[cols_here == i]), c.rgb,
                                            filament_slot(c.code)))
            fp = spare_dir / f"spare_multicolor_bed{b:02d}.3mf"
            write_3mf(fp, bed_objs, f"Loose studs bed {b}")
            mc_files.append(fp)
    res.files["spare_3mf"] = mc_files
    res.files["spare_stl"] = stl_files

    # Build the Bambu project as color-sorted plates. Reserve studs are added
    # to the same color's needed quantity, never put on separate reserve plates.
    # No baseplate meshes are included; every exported mesh is a stud.
    project_plates = []
    for color_index, (color, row) in enumerate(zip(palette, res.bom)):
        needed = int(row["needed"])
        reserve = int(row["reserve_extra"]) if o.loose_include_needed else 0
        count = needed + reserve
        if count == 0:
            continue
        positions_by_plate = _profile_safe_positions(
            count, stud, o.loose_spacing, profile, o.bed_margin
        )
        for plate_index, (positions, cells) in enumerate(positions_by_plate, start=1):
            stud_object = PrintObject(
                f"Studs {color.name_en}",
                tile_mesh(stud, positions),
                color.rgb,
                filament_slot(color.code),
                positions,
                cells,
            )
            project_plates.append(
                (f"{color.name_en} - Plate {plate_index}", [stud_object])
            )

    # Export color counts as separate auxiliary files for users who want them.
    color_plate_files: list[Path] = []
    for i, (c, row) in enumerate(zip(palette, res.bom)):
        needed = row["needed"]
        beds = _profile_safe_positions(needed, stud, o.loose_spacing, profile, o.bed_margin)
        for b, (pos, _) in enumerate(beds, start=1):
            name = f"plate_{c.code}_{_filename_slug(c.name_en)}_bed{b:02d}"
            obj = PrintObject(f"Studs {c.name_en}", tile_mesh(stud, pos), c.rgb,
                              filament_slot(c.code))
            p3mf, pstl = out / f"{name}.3mf", out / f"{name}.stl"
            write_3mf(p3mf, [obj], f"{c.name_en} plate ({len(pos)} studs)")
            write_stl(obj.mesh, pstl)
            color_plate_files.extend([p3mf, pstl])
    res.files["color_plates"] = color_plate_files

    project_path = out / "lego_mosaic_bambu_project.3mf"
    exported_plate_names, applied_scale, edge_clearance = write_bambu_multi_plate_3mf(
        project_path,
        project_plates,
        f"LEGO Mosaic {o.grid}x{o.grid}",
        palette=COLOR_PALETTE,
        edge_margin=o.bed_margin,
        rotation_degrees=o.rotation_degrees,
        scale_to_fit=o.scale_to_fit,
    )
    res.files["bambu_project"] = [project_path]
    res.project_plate_names = exported_plate_names
    res.plate_edge_clearance = edge_clearance
    res.uniform_scale = applied_scale
    if applied_scale < 1.0:
        res.warnings.append(
            f"All plates were uniformly scaled to {applied_scale * 100:.2f}%. "
            f"New mosaic stud spacing: {o.pitch * applied_scale:.2f} mm; "
            f"loose reserve stud spacing: {o.loose_spacing * applied_scale:.2f} mm."
        )

    pi, pp = out / "building_instructions.png", out / "mosaic_preview.png"
    render_instructions(idx, res.bom, pi, palette=palette)
    pdf = out / "building_instructions.pdf"
    with Image.open(pi) as instruction_image:
        instruction_image.convert("RGB").save(pdf, "PDF", resolution=150.0)
    render_preview(idx, pp, palette=palette)
    jp, tp = write_bom(res.bom, idx, o, stud_path.name, out, palette=palette)
    res.files["docs"] = [pi, pp, pdf, jp, tp]
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Image -> LEGO Mosaic + 3D print files.")
    ap.add_argument("image", help="JPG/PNG image")
    ap.add_argument("--grid", type=int, default=48, choices=[24, 30, 48, 60])
    ap.add_argument("--mode", choices=["color", "grayscale"], default="color",
                    help="palette mode (default: color)")
    ap.add_argument("--out", default="output", help="output directory")
    ap.add_argument("--assets", default=None, help="directory with stud.stl")
    ap.add_argument("--reserve", type=float, default=5.0, help="reserve in %%")
    ap.add_argument("--dither", action="store_true")
    ap.add_argument("--no-autocontrast", action="store_true")
    ap.add_argument("--loose-all", action="store_true")
    a = ap.parse_args(argv)
    opts = Options(grid=a.grid, palette_mode=a.mode, reserve_pct=a.reserve,
                   dither=a.dither, autocontrast=not a.no_autocontrast, loose_include_needed=a.loose_all)
    try:
        r = generate(a.image, a.out, a.assets, opts)
    except MosaicError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print((r.out_dir / "bill_of_materials.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
