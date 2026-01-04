#!/usr/bin/env python3
"""Export multiple UV variants for inspection.

Usage:
  python3 tools/uv_export.py cacc/caha000.rrm --out Models_debug/caha000

Exports three OBJ/MTL pairs (if available):
  - <stem>_stream2.obj : UVs from normals+uv stream (offset 0x20c0, stride 32, uv at +24)
  - <stem>_uv0.obj     : UVs from packed block at 0x31c0, floats 0-1
  - <stem>_uv1.obj     : UVs from packed block at 0x31c0, floats 2-3
All reference the same DDS (if found) via map_Kd and copy the DDS beside outputs.
"""
import argparse
import struct
from pathlib import Path
import shutil


def read_vertices(data: bytes, vert_off: int, count: int):
    verts = []
    for i in range(count):
        base = vert_off + i * 12
        if base + 12 > len(data):
            break
        verts.append(struct.unpack_from('<3f', data, base))
    return verts


def read_indices(data: bytes, idx_off: int):
    vals = []
    off = idx_off
    while off + 4 <= len(data):
        v = struct.unpack_from('<I', data, off)[0]
        if v > 100000:  # heuristic end
            break
        vals.append(v)
        off += 4
    # trim to triangles
    tri_len = (len(vals) // 3) * 3
    return vals[:tri_len]


def write_obj(path: Path, verts, uvs, faces, mtl_name: str):
    lines = [f"mtllib {mtl_name}\n", "usemtl material0\n"]
    for x, y, z in verts:
        lines.append(f"v {x:.6f} {y:.6f} {z:.6f}\n")
    if uvs:
        for u, v in uvs:
            lines.append(f"vt {u:.6f} {v:.6f}\n")
    for a, b, c in faces:
        if uvs:
            lines.append(f"f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}\n")
        else:
            lines.append(f"f {a+1} {b+1} {c+1}\n")
    path.write_text("".join(lines))


def write_mtl(path: Path, texture_name: str | None):
    content = [
        "newmtl material0\n",
        "Ka 1.000 1.000 1.000\n",
        "Kd 1.000 1.000 1.000\n",
        "Ks 0.000 0.000 0.000\n",
        "d 1.0\n",
        "illum 1\n",
    ]
    if texture_name:
        content.append(f"map_Kd {texture_name}\n")
    path.write_text("".join(content))


def extract_uv_stream2(data: bytes, vertex_count: int):
    uv_off = 0x20C0
    stride = 32
    off_in = 24
    if uv_off + stride * vertex_count > len(data):
        return None
    uvs = []
    for i in range(vertex_count):
        u = struct.unpack_from('<f', data, uv_off + i * stride + off_in)[0]
        v = struct.unpack_from('<f', data, uv_off + i * stride + off_in + 4)[0]
        uvs.append((u, v))
    return uvs


def extract_uv_packed(data: bytes, vertex_count: int, set_idx: int):
    # set_idx 0 uses floats 0-1, set_idx 1 uses floats 2-3
    start = 0x31C0
    stride = 16
    off_u = 0 if set_idx == 0 else 8
    off_v = 4 if set_idx == 0 else 12
    if start + stride * vertex_count > len(data):
        return None
    uvs = []
    for i in range(vertex_count):
        u = struct.unpack_from('<f', data, start + i * stride + off_u)[0]
        v = struct.unpack_from('<f', data, start + i * stride + off_v)[0]
        uvs.append((u, v))
    return uvs


def find_dds(base_stem: str):
    cacc_dir = Path(__file__).resolve().parent.parent / 'cacc'
    # Prefer exact stem.dds
    exact = cacc_dir / f"{base_stem}.dds"
    if exact.exists():
        return exact
    # Fallback: any matching prefix
    matches = sorted(cacc_dir.glob(f"{base_stem}*.dds"))
    return matches[0] if matches else None


def main():
    ap = argparse.ArgumentParser(description="Export UV variants for inspection")
    ap.add_argument("rrm", help="Path to .rrm file")
    ap.add_argument("--out", required=True, help="Output directory for variants")
    args = ap.parse_args()

    rrm_path = Path(args.rrm)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = rrm_path.read_bytes()
    idx_off = struct.unpack_from('<I', data, 0xB0)[0]
    vert_off = struct.unpack_from('<I', data, 0xB4)[0]

    idx_vals = read_indices(data, idx_off)
    if not idx_vals:
        raise SystemExit("No indices found")
    max_idx = max(idx_vals)
    vcount = max_idx + 1

    verts = read_vertices(data, vert_off, vcount)
    faces = [(idx_vals[i], idx_vals[i+1], idx_vals[i+2]) for i in range(0, len(idx_vals), 3)]

    # UV sets
    uv_stream2 = extract_uv_stream2(data, vcount)
    uv0 = extract_uv_packed(data, vcount, 0)
    uv1 = extract_uv_packed(data, vcount, 1)

    stem = rrm_path.stem
    dds = find_dds(stem)
    tex_name = None
    if dds:
        tex_name = dds.name
        shutil.copy2(dds, out_dir / dds.name)

    # Export each available UV set
    variants = [
        ("stream2", uv_stream2),
        ("uv0", uv0),
        ("uv1", uv1),
    ]
    for label, uvset in variants:
        if uvset is None:
            continue
        obj_name = f"{stem}_{label}.obj"
        mtl_name = f"{stem}_{label}.mtl"
        write_obj(out_dir / obj_name, verts, uvset, faces, mtl_name)
        write_mtl(out_dir / mtl_name, tex_name)

    print("Exported variants to", out_dir)


if __name__ == "__main__":
    main()
