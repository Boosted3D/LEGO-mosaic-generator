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
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

# --------------------------------------------------------------------------- #
# Constants & Palette
# --------------------------------------------------------------------------- #
PITCH_MM = 8.0       # LEGO stud pitch
BED_MM = 256.0       # Bambu Lab print bed (A1/P1/X1: 256 x 256 mm)
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
    plate_thickness: float = 1.6       # baseplate thickness (mm)
    base_color: str = "BK"             # baseplate color code
    dither: bool = False               # Floyd-Steinberg dithering
    autocontrast: bool = True          # stretch histogram for better results
    loose_include_needed: bool = False  # loose studs: reserve only (False) or all (True)
    loose_spacing: float = 9.0         # center-to-center distance loose studs (mm)
    bed_margin: float = 3.0            # free margin on print bed (mm)


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


def box_mesh(x0, y0, z0, dx, dy, dz) -> Mesh:
    v = np.array(
        [[0, 0, 0], [dx, 0, 0], [dx, dy, 0], [0, dy, 0],
         [0, 0, dz], [dx, 0, dz], [dx, dy, dz], [0, dy, dz]], dtype=float
    ) + [x0, y0, z0]
    f = np.array(
        [[0, 3, 2], [0, 2, 1],
         [4, 5, 6], [4, 6, 7],
         [0, 1, 5], [0, 5, 4],
         [1, 2, 6], [1, 6, 5],
         [2, 3, 7], [2, 7, 6],
         [3, 0, 4], [3, 4, 7]],
        dtype=np.int64,
    )
    return Mesh(v, f)


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
    path: Path, plates: list[tuple[str, list[PrintObject]]], title: str = "LEGO mosaic"
) -> None:
    """Write one Bambu Studio project with the supplied objects on named plates."""
    plates = [(name, objects) for name, objects in plates if objects]
    if not plates:
        raise MosaicError("No print plates were generated.")

    def xml_attr(value: str) -> str:
        return escape(value, {'"': "&quot;"})

    plate_cols = max(1, math.floor(math.sqrt(len(plates)) + 0.5))
    if math.sqrt(len(plates)) > plate_cols:
        plate_cols += 1
    plate_stride = BED_MM * 1.2
    materials: list[tuple[str, tuple[int, int, int]]] = []
    objects_xml: list[str] = []
    builds_xml: list[str] = []
    settings_objects: list[str] = []
    plate_xml: list[str] = []
    object_id = 2

    for plate_index, (plate_name, print_objects) in enumerate(plates):
        row, col = divmod(plate_index, plate_cols)
        offset_x, offset_y = col * plate_stride, -row * plate_stride
        instance_xml: list[str] = []
        for print_object in print_objects:
            material = (print_object.name, print_object.rgb)
            if material not in materials:
                materials.append(material)
            material_index = materials.index(material)
            obj_uuid, item_uuid = str(uuid.uuid4()), str(uuid.uuid4())
            vertices = print_object.mesh.vertices
            faces = print_object.mesh.faces
            mesh_xml = ["      <mesh><vertices>"]
            mesh_xml.extend(
                f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>'
                for x, y, z in vertices
            )
            mesh_xml.append("</vertices><triangles>")
            mesh_xml.extend(
                f'<triangle v1="{a}" v2="{b}" v3="{c}"/>'
                for a, b, c in faces
            )
            mesh_xml.append("</triangles></mesh>")
            objects_xml.append(
                f'<object id="{object_id}" name="{escape(print_object.name)}" '
                f'type="model" pid="1" pindex="{material_index}" p:UUID="{obj_uuid}">'
                f'{"".join(mesh_xml)}</object>'
            )
            builds_xml.append(
                f'<item objectid="{object_id}" p:UUID="{item_uuid}" '
                f'transform="1 0 0 0 1 0 0 0 1 {offset_x:.4f} {offset_y:.4f} 0" printable="1"/>'
            )
            settings_objects.append(
                f'<object id="{object_id}"><metadata key="name" value="{xml_attr(print_object.name)}"/>'
                f'<metadata key="extruder" value="{print_object.extruder}"/></object>'
            )
            instance_xml.append(
                '<model_instance>'
                f'<metadata key="object_id" value="{object_id}"/>'
                '<metadata key="instance_id" value="0"/>'
                '</model_instance>'
            )
            object_id += 1

        safe_name = re.sub(r'[<>:/\\|?*"]', "-", plate_name).strip() or f"Plate {plate_index + 1}"
        plate_xml.append(
            f'<plate><metadata key="plater_id" value="{plate_index + 1}"/>'
            f'<metadata key="plater_name" value="{xml_attr(safe_name)}"/>'
            '<metadata key="locked" value="false"/>'
            f'{"".join(instance_xml)}</plate>'
        )

    material_xml = [f'<base name="{escape(name)}" displaycolor="#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}FF"/>'
                    for name, rgb in materials]
    model_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">'
        f'<metadata name="Title">{escape(title)}</metadata>'
        '<metadata name="Application">BambuStudio-02.06.00.51</metadata>'
        '<metadata name="BambuStudio:3mfVersion">1</metadata>'
        f'<resources><basematerials id="1">{"".join(material_xml)}</basematerials>{"".join(objects_xml)}</resources>'
        f'<build p:UUID="{uuid.uuid4()}">{"".join(builds_xml)}</build></model>'
    )
    model_settings = (
        '<?xml version="1.0" encoding="UTF-8"?><config>'
        f'{"".join(settings_objects)}{"".join(plate_xml)}</config>'
    )
    project_settings = json.dumps({
        "from": "project",
        "type": "process",
        "name": title,
        "filament_colour": [color.hex for color in COLOR_PALETTE],
        "filament_type": ["PLA"] * len(COLOR_PALETTE),
        "filament_vendor": ["Generic"] * len(COLOR_PALETTE),
    })
    slice_info = (
        '<?xml version="1.0" encoding="UTF-8"?><config><header>'
        '<header_item key="X-BBL-Client-Type" value="slicer"/>'
        '<header_item key="X-BBL-Client-Version" value="02.06.00.51"/>'
        '</header></config>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="config" ContentType="text/xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", model_xml)
        archive.writestr("Metadata/project_settings.config", project_settings)
        archive.writestr("Metadata/model_settings.config", model_settings)
        archive.writestr("Metadata/slice_info.config", slice_info)


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
                             palette: tuple[LegoColor, ...] = PALETTE,
                             include_baseplate: bool = True) -> list[PrintObject]:
    n = sub_idx.shape[0]
    size = n * o.pitch
    objs: list[PrintObject] = []
    if include_baseplate:
        base = next((c for c in COLOR_PALETTE if c.code == o.base_color), None)
        if base is None:
            raise MosaicError(f"Unknown baseplate color '{o.base_color}'.")
        objs.append(PrintObject(f"Baseplate ({base.name_en})",
                                box_mesh(x_off_mm, y_off_mm, base_z, size, size, o.plate_thickness),
                                base.rgb, filament_slot(base.code)))

    for i, c in enumerate(palette):
        r_sub, c_sub = np.nonzero(sub_idx == i)
        if len(r_sub) > 0:
            x = x_off_mm + (c_sub + 0.5) * o.pitch
            y = y_off_mm + (n - 1 - r_sub + 0.5) * o.pitch
            z = np.full_like(x, base_z + (o.plate_thickness if include_baseplate else 0.0), dtype=float)
            pos = np.column_stack([x, y, z])
            objs.append(PrintObject(f"Studs {c.name_en}", tile_mesh(stud, pos), c.rgb,
                                    filament_slot(c.code)))
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
              palette: tuple[LegoColor, ...] = PALETTE,
              baseplate_count: int = 0) -> tuple[Path, Path]:
    n = o.grid
    tot_needed = sum(r["needed"] for r in bom)
    tot_extra = sum(r["reserve_extra"] for r in bom)
    data = {
        "grid": f"{n}x{n}", "positions": n * n, "stud_pitch_mm": o.pitch,
        "plate_size_mm": [n * o.pitch, n * o.pitch], "plate_thickness_mm": o.plate_thickness,
        "reserve_percent": o.reserve_pct, "stud_model": stud_file,
        "colors": bom,
        "baseplate": {
            "code": o.base_color,
            "name_en": next(c.name_en for c in COLOR_PALETTE if c.code == o.base_color),
            "hex": next(c.hex for c in COLOR_PALETTE if c.code == o.base_color),
            "count": baseplate_count,
        },
        "totals": {"needed": tot_needed, "reserve_extra": tot_extra,
                   "baseplates": baseplate_count,
                   "total_to_print": tot_needed + tot_extra + baseplate_count},
        "palette_mode": o.palette_mode,
        "layout_rows_top_to_bottom": ["".join(palette[i].code.ljust(3) for i in row).rstrip() for row in idx],
    }
    jp, tp = out / "bill_of_materials.json", out / "bill_of_materials.txt"
    jp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    base_color = next(c for c in COLOR_PALETTE if c.code == o.base_color)
    lines = [f"BILL OF MATERIALS - {n}x{n} LEGO Mosaic ({n * n} positions, +{o.reserve_pct:g}% reserve)",
             "=" * 66,
             f"{'Code':<5}{'Color':<14}{'Needed':>8}{'Reserve':>10}{'Total':>10}", "-" * 66]
    lines.append(f"{base_color.code:<5}{('Baseplate - ' + base_color.name_en):<14}{baseplate_count:>8}{0:>10}{baseplate_count:>10}")
    for r in bom:
        lines.append(f"{r['code']:<5}{r['name_en']:<14}{r['needed']:>8}{'+' + str(r['reserve_extra']):>10}{r['total_to_print']:>10}")
    lines += ["-" * 66, f"{'':<19}{tot_needed + baseplate_count:>8}{'+' + str(tot_extra):>10}{tot_needed + tot_extra + baseplate_count:>10}",
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
    baseplate_color: LegoColor | None = None
    baseplate_count: int = 0

    def all_files(self) -> list[Path]:
        return [p for v in self.files.values() for p in v]


def _validate(o: Options) -> None:
    palette = palette_for_mode(o.palette_mode, o.selected_colors)
    if o.palette_mode == "color" and not palette:
        raise MosaicError("Select at least one color to generate the mosaic.")
    if o.base_color not in {c.code for c in COLOR_PALETTE}:
        raise MosaicError(f"Unknown base color '{o.base_color}'.")
    if o.reserve_pct < 0:
        raise MosaicError("Reserve percentage cannot be negative.")
    if o.plate_thickness <= 0:
        raise MosaicError("Plate thickness must be greater than 0.")


def _filename_slug(value: str) -> str:
    """Make a readable filename part without path separators or punctuation."""
    return re.sub(r"[^a-z0-9_-]+", "_", value.lower()).strip("_")


def generate(image_source, out_dir: str | Path = "output",
             assets_dir: str | Path | None = None, options: Options | None = None) -> Result:
    o = options or Options()
    _validate(o)
    palette = palette_for_mode(o.palette_mode, o.selected_colors)
    here = Path(__file__).resolve().parent
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
    res.baseplate_color = next(c for c in COLOR_PALETTE if c.code == o.base_color)
    res.baseplate_count = 4 if o.grid in (48, 60) else 1

    stud, stud_path, warns = load_stud(assets, o.pitch)
    res.warnings += warns
    stud_w = float(max(stud.bounds()[1][:2] - stud.bounds()[0][:2]))

    if o.grid in (48, 60):
        half = o.grid // 2
        tile_size_mm = half * o.pitch
        origin = (o.bed - tile_size_mm) / 2
        plate_files = []
        tile_names = ("Top-left", "Top-right", "Bottom-left", "Bottom-right")
        for tile_number, (r_idx, c_idx) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1)), start=1):
            sub = idx[r_idx*half:(r_idx+1)*half, c_idx*half:(c_idx+1)*half]
            tile_objs = build_mosaic_tile_objects(sub, stud, o, origin, origin, 0.0, palette)
            for tobj in tile_objs:
                tobj.name = f"{tile_names[tile_number - 1]} - {tobj.name}"
            if o.palette_mode == "grayscale":
                project_plates.append((f"Mosaic - {tile_names[tile_number - 1]}", tile_objs))
            if o.palette_mode == "grayscale":
                p3mf = out / f"mosaic_plate_{o.grid}x{o.grid}_tile_{tile_number}.3mf"
                pstl = out / f"mosaic_plate_{o.grid}x{o.grid}_tile_{tile_number}.stl"
                write_3mf(p3mf, tile_objs, f"LEGO mosaic {o.grid}x{o.grid} tile {tile_number}")
                write_stl(merge_meshes([ob.mesh for ob in tile_objs]), pstl)
                plate_files.extend([p3mf, pstl])

        if o.palette_mode == "grayscale":
            res.files["plate"] = plate_files
    else:
        size = o.grid * o.pitch
        origin = (o.bed - size) / 2
        tile_objs = build_mosaic_tile_objects(idx, stud, o, origin, origin, 0.0, palette)
        if o.palette_mode == "grayscale":
            project_plates.append((f"Mosaic {o.grid}x{o.grid}", tile_objs))
        if o.palette_mode == "grayscale":
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
        for b, pos in enumerate(loose_positions(k, stud_w, o), start=1):
            fp = spare_dir / f"spare_{c.code}_{_filename_slug(c.name_en)}_bed{b:02d}.stl"
            write_stl(tile_mesh(stud, pos), fp)
            stl_files.append(fp)

    seq = [(i, k) for i, k in enumerate(per_color) if k > 0]
    total = sum(k for _, k in seq)
    mc_files = []
    if total:
        beds = loose_positions(total, stud_w, o)
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

    # Export studs grouped by color. In color mode, each bed-sized group is a
    # separate named plate in the Bambu project; large color counts are split
    # across as many plates as the printer bed can hold.
    color_plate_files: list[Path] = []
    for i, (c, row) in enumerate(zip(palette, res.bom)):
        needed = row["needed"]
        beds = loose_positions(needed, stud_w, o)
        for b, pos in enumerate(beds, start=1):
            name = f"plate_{c.code}_{_filename_slug(c.name_en)}_bed{b:02d}"
            obj = PrintObject(f"Studs {c.name_en}", tile_mesh(stud, pos), c.rgb,
                              filament_slot(c.code))
            if o.palette_mode == "color":
                plate_name = c.name_en if len(beds) == 1 else f"{c.name_en} - Plate {b}"
                project_plates.append((plate_name, [obj]))
            p3mf, pstl = out / f"{name}.3mf", out / f"{name}.stl"
            write_3mf(p3mf, [obj], f"{c.name_en} plate ({len(pos)} studs)")
            write_stl(obj.mesh, pstl)
            color_plate_files.extend([p3mf, pstl])
    res.files["color_plates"] = color_plate_files

    project_path = out / "lego_mosaic_bambu_project.3mf"
    write_bambu_multi_plate_3mf(project_path, project_plates, f"LEGO Mosaic {o.grid}x{o.grid}")
    res.files["bambu_project"] = [project_path]
    res.project_plate_names = [name for name, objects in project_plates if objects]

    pi, pp = out / "building_instructions.png", out / "mosaic_preview.png"
    render_instructions(idx, res.bom, pi, palette=palette)
    pdf = out / "building_instructions.pdf"
    with Image.open(pi) as instruction_image:
        instruction_image.convert("RGB").save(pdf, "PDF", resolution=150.0)
    render_preview(idx, pp, palette=palette)
    jp, tp = write_bom(res.bom, idx, o, stud_path.name, out, palette=palette,
                       baseplate_count=res.baseplate_count)
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
    ap.add_argument("--thickness", type=float, default=1.6, help="baseplate thickness in mm")
    ap.add_argument("--base-color", default="BK", choices=[c.code for c in PALETTE])
    ap.add_argument("--dither", action="store_true")
    ap.add_argument("--no-autocontrast", action="store_true")
    ap.add_argument("--loose-all", action="store_true")
    a = ap.parse_args(argv)
    opts = Options(grid=a.grid, palette_mode=a.mode, reserve_pct=a.reserve,
                   plate_thickness=a.thickness, base_color=a.base_color,
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
