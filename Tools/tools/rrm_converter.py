#!/usr/bin/env python3
"""Small best-effort .rrm <-> .obj converter with Texture/UV support.
"""
import argparse
import os
import struct
import sys
import shutil
import math
from math import isfinite
from pathlib import Path

def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()

def is_valid_float(v):
    return abs(v) < 1e7 and v == v

# --- Texture / MTL Helpers ---

def dds_to_png(dds_path, output_dir, stem):
    """Convert DDS to PNG; fallback to copying DDS if conversion fails."""
    if not os.path.exists(dds_path):
        return None

    png_filename = f"{stem}.png"
    png_path = os.path.join(output_dir, png_filename)
    
    # Try using PIL
    try:
        from PIL import Image
        with Image.open(dds_path) as img:
            img.save(png_path, "PNG")
        return png_filename
    except Exception:
        pass

    # Fallback: just copy as .dds if we can't convert
    # But user requested .png. We can try to rename or just copy dds.
    # If we fail to convert, we return the dds filename.
    dds_filename = f"{stem}.dds"
    dds_out = os.path.join(output_dir, dds_filename)
    if os.path.abspath(dds_path) != os.path.abspath(dds_out):
        shutil.copy2(dds_path, dds_out)
    return dds_filename

def png_to_dds(png_path, output_dir, stem):
    """Convert PNG to DDS; fallback to copying."""
    if not os.path.exists(png_path):
        return None

    dds_filename = f"{stem}.dds"
    dds_path = os.path.join(output_dir, dds_filename)

    # Simple copy for now as writing valid DDS is complex without libs
    # In a real scenario, we might use texconv or ImageMagick
    if os.path.abspath(png_path) != os.path.abspath(dds_path):
        shutil.copy2(png_path, dds_path)
    return dds_filename

def create_mtl_file(mtl_path, texture_name):
    content = f"""newmtl material0
Ka 1.000 1.000 1.000
Kd 1.000 1.000 1.000
Ks 0.000 0.000 0.000
d 1.0
illum 1"""
    if texture_name:
        content += f"\nmap_Kd {texture_name}\n"
    else:
        content += "\n"
    
    with open(mtl_path, "w", encoding="utf-8") as f:
        f.write(content)

# --- UV Extraction Logic ---

def extract_uvs_from_rrm(data, vertex_count):
    """Extract UV coordinates from RRM file data."""
    try:
        vert_off = struct.unpack_from("<I", data, 0xb4)[0]
    except struct.error:
        return None
    
    expected_uv_off = vert_off + (vertex_count * 12)
    
    def read_stream2(uv_off):
        stride = 32
        uv_offset_in_stride = 24
        if uv_off is None: return None
        if uv_off + stride * vertex_count > len(data): return None
        uvs = []
        for i in range(vertex_count):
            try:
                u = struct.unpack_from('<f', data, uv_off + i * stride + uv_offset_in_stride)[0]
                v = struct.unpack_from('<f', data, uv_off + i * stride + uv_offset_in_stride + 4)[0]
            except Exception: return None
            if not (-10.0 < u < 10.0 and -10.0 < v < 10.0): return None
            uvs.append((u, v))
        return uvs

    # 1. Try legacy stream at 0x20c0
    uvs = read_stream2(0x20c0)
    
    # 2. Try expected offset
    if uvs is None:
        uvs = read_stream2(expected_uv_off)
        
    # 3. Try packed UV run (stride 16)
    if uvs is None:
        # Scan for float runs
        n = len(data)
        off = 0
        runs = []
        while off <= n - 4:
            try: val = struct.unpack_from('<f', data, off)[0]
            except: break
            if not is_valid_float(val):
                off += 4; continue
            start = off
            count = 0
            while off <= n - 4:
                try: v = struct.unpack_from('<f', data, off)[0]
                except: break
                if not is_valid_float(v): break
                count += 1
                off += 4
            if count >= vertex_count * 4:
                runs.append((start, count))
            # skip ahead? no, loop increments
        
        # Check candidates
        candidates = []
        for start, count in runs:
             vals = [struct.unpack_from('<f', data, start + i * 4)[0] for i in range(min(count, 40))]
             rng = max(abs(v) for v in vals) if vals else 0
             if rng < 5.0: candidates.append((start, count, rng))
        
        if candidates:
            candidates.sort(key=lambda t: (t[2], t[0]))
            run_start = candidates[0][0]
            try:
                uvs = []
                for i in range(vertex_count):
                    u = struct.unpack_from('<f', data, run_start + i * 16)[0]
                    v = struct.unpack_from('<f', data, run_start + i * 16 + 4)[0]
                    uvs.append((u, v))
            except: uvs = None

    # 4. Fallback 0x31c0
    if uvs is None:
        try:
            uvs = []
            for i in range(vertex_count):
                u = struct.unpack_from('<f', data, 0x31c0 + i * 16)[0]
                v = struct.unpack_from('<f', data, 0x31c0 + i * 16 + 4)[0]
                uvs.append((u, v))
        except: uvs = None

    return uvs

def auto_extract_rrm(in_path, out_path):
    """Extract mesh from .rrm file using header offsets + UVs + Texture handling."""
    data = read_bytes(in_path)
    
    # Header offsets
    try:
        idx_off = struct.unpack_from("<I", data, 0xb0)[0]
        vert_off = struct.unpack_from("<I", data, 0xb4)[0]
    except struct.error:
        raise RuntimeError("Failed to read header offsets (0xb0/0xb4)")
    
    # Indices
    idx_vals = []
    off = idx_off
    while off < len(data) - 3:
        try:
            val = struct.unpack_from("<I", data, off)[0]
            if val > 100000: break
            idx_vals.append(val)
            off += 4
        except struct.error: break
    
    if len(idx_vals) % 3 != 0:
        idx_vals = idx_vals[:((len(idx_vals) // 3) * 3)]
    
    if not idx_vals:
        raise RuntimeError("No index data found")
    
    max_index = max(idx_vals)
    required_vcount = max_index + 1
    
    # Vertices
    V = []
    for i in range(required_vcount):
        base = vert_off + i * 12
        if base + 12 > len(data): break
        try: x, y, z = struct.unpack_from("<3f", data, base)
        except: break
        V.append((x, y, z))
        
    # UVs
    uvs = extract_uvs_from_rrm(data, len(V))
    
    # Faces
    faces = []
    for i in range(0, len(idx_vals), 3):
        a, b, c = idx_vals[i], idx_vals[i+1], idx_vals[i+2]
        if a < len(V) and b < len(V) and c < len(V):
            faces.append((a, b, c))
            
    # Deduplicate only if no UVs
    if uvs:
        V_dedup = V
        map_old_to_new = list(range(len(V)))
        uvs_dedup = uvs
    else:
        # dedup logic
        eps = 1e-6
        map_old_to_new = [None] * len(V)
        V_dedup = []
        for i, (x, y, z) in enumerate(V):
            found = False
            for j, (x2, y2, z2) in enumerate(V_dedup):
                if abs(x-x2)<eps and abs(y-y2)<eps and abs(z-z2)<eps:
                    map_old_to_new[i] = j
                    found = True; break
            if not found:
                map_old_to_new[i] = len(V_dedup)
                V_dedup.append((x, y, z))
        uvs_dedup = None

    # Texture handling
    in_dir = os.path.dirname(in_path)
    in_stem = os.path.splitext(os.path.basename(in_path))[0]
    out_dir = os.path.dirname(out_path)
    
    # Look for .dds
    dds_path = os.path.join(in_dir, in_stem + ".dds")
    texture_file = None
    if os.path.exists(dds_path):
        texture_file = dds_to_png(dds_path, out_dir, in_stem)
    else:
        # Fallback: check if source has .png already
        png_src = os.path.join(in_dir, in_stem + ".png")
        if os.path.exists(png_src):
            shutil.copy2(png_src, os.path.join(out_dir, in_stem + ".png"))
            texture_file = in_stem + ".png"
        
    # Write MTL
    mtl_filename = in_stem + ".mtl"
    mtl_path = os.path.join(out_dir, mtl_filename)
    create_mtl_file(mtl_path, texture_file if texture_file else "")
    
    # Write OBJ
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"mtllib {mtl_filename}\n")
        f.write(f"usemtl material0\n")
        
        for v in V_dedup:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            
        if uvs_dedup:
            for u, v in uvs_dedup:
                # Game uses repeat; we just write raw UVs
                if not (isfinite(u) and isfinite(v)):
                    f.write("vt 0.0 0.0\n")
                else:
                    f.write(f"vt {u:.6f} {v:.6f}\n")
                    
        faces_final = []
        for a, b, c in faces:
            na, nb, nc = map_old_to_new[a], map_old_to_new[b], map_old_to_new[c]
            # skip degenerate if deduplicated
            if not uvs_dedup and (na == nb or nb == nc or nc == na): continue
            faces_final.append((na, nb, nc))
            
        for a, b, c in faces_final:
            if uvs_dedup:
                f.write(f"f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}\n")
            else:
                f.write(f"f {a+1} {b+1} {c+1}\n")

    print(f"Auto-extracted OBJ: {out_path} (verts={len(V_dedup)}, faces={len(faces_final)}, tex={texture_file})")


def obj2rrm(in_path, out_path):
    verts = []
    # Simple parser for vertices only
    with open(in_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    try:
                        x = float(parts[1]); y = float(parts[2]); z = float(parts[3])
                        verts.append((x, y, z))
                    except Exception: continue

    if not verts:
        raise RuntimeError("No vertices found in OBJ file")

    # Write RRM
    with open(out_path, "wb") as f:
        f.write(b"RRMEXTR\0")
        f.write(struct.pack("<I", len(verts)))
        for v in verts:
            f.write(struct.pack("<fff", v[0], v[1], v[2]))

    print(f"Wrote {len(verts)} vertices to {out_path}")
    
    # Texture back-conversion (PNG -> DDS)
    in_dir = os.path.dirname(in_path)
    in_stem = os.path.splitext(os.path.basename(in_path))[0]
    out_dir = os.path.dirname(out_path)
    
    # Check for .png
    png_path = os.path.join(in_dir, in_stem + ".png")
    if os.path.exists(png_path):
        dds_name = png_to_dds(png_path, out_dir, in_stem)
        print(f"  Converted/Copied texture: {dds_name}")
        
    # Also copy MTL if exists
    mtl_path = os.path.join(in_dir, in_stem + ".mtl")
    if os.path.exists(mtl_path):
        shutil.copy2(mtl_path, os.path.join(out_dir, in_stem + ".mtl"))

def clean_obj(in_path, out_path, merge_epsilon=1e-5):
    # Minimal implementation to keep script runnable if called
    pass

def main(argv=None):
    p = argparse.ArgumentParser(description="Best-effort .rrm <-> .obj converter")
    sub = p.add_subparsers(dest="cmd")

    a1 = sub.add_parser("rrm2obj", help="Extract vertices from .rrm to .obj")
    a1.add_argument("infile")
    a1.add_argument("outfile", nargs="?", help="Output .obj path")

    a2 = sub.add_parser("obj2rrm", help="Pack .obj vertices into minimal .rrm")
    a2.add_argument("infile")
    a2.add_argument("outfile", nargs="?", help="Output .rrm path")
    
    a4 = sub.add_parser("autoextract", help="Automatically extract mesh (positions+indices) from .rrm and write OBJ")
    a4.add_argument("infile")
    a4.add_argument("outfile", nargs="?", help="Output .obj path")

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help(); sys.exit(1)

    if args.cmd == "rrm2obj":
        # Legacy placeholder
        infile = args.infile
        outfile = args.outfile or (os.path.splitext(infile)[0] + ".obj")
        # Reuse autoextract logic as it is better now
        auto_extract_rrm(infile, outfile)
    elif args.cmd == "obj2rrm":
        infile = args.infile
        outfile = args.outfile or (os.path.splitext(infile)[0] + ".rrm")
        obj2rrm(infile, outfile)
    elif args.cmd == "autoextract":
        infile = args.infile
        outfile = args.outfile or (os.path.splitext(infile)[0] + ".extracted.obj")
        auto_extract_rrm(infile, outfile)


if __name__ == "__main__":
    main()
