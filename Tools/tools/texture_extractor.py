#!/usr/bin/env python3
"""Extract RRM meshes with UV coordinates and organize with DDS textures.

This tool:
1. Extracts RRM models to OBJ with UV texture coordinates
2. Detects and converts DDS textures to PNG
3. Organizes models into folder structure:
   - Multi-variant models: folder/variant1/, folder/variant2/, etc.
   - Single-variant models: folder/
   Each containing: model.obj, model.mtl, texture.png
"""

import os
import struct
import sys
from pathlib import Path
import shutil
import argparse
import re
import math


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def is_valid_float(v):
    """Check if a float is reasonable (not denormalized/NaN/Inf)"""
    return abs(v) < 1e7 and v == v


def extract_uvs_from_rrm(rrm_path, vertex_count):
    """Extract UV coordinates from RRM file.
    
    RRM format (from header offsets and binary analysis):
    - 0xb0: Index buffer offset
    - 0xb4: Vertex buffer offset (XYZ positions, 12 bytes per vertex)
    - UV/Normal stream: at calculated offset with stride 32
      Format per stride: [normal data (24 bytes) + uv coordinates (8 bytes)]
      UV coordinates are at bytes 24-32 of each 32-byte stride element
    
    Returns: list of (u, v) tuples, one per vertex
    """
    data = read_bytes(rrm_path)
    
    try:
        vert_off = struct.unpack_from("<I", data, 0xb4)[0]
    except struct.error:
        return None
    
    # Calculate expected UV stream location: after all vertex positions
    # Each vertex = 3 floats (XYZ), so vertex data size = vertex_count * 12
    expected_uv_off = vert_off + (vertex_count * 12)
    
    # Preferred: discover UV streams heuristically (handles alternate layouts).
    def find_uv_run():
        # Find contiguous runs of finite floats
        runs = []
        n = len(data)
        off = 0
        while off <= n - 4:
            try:
                val = struct.unpack_from('<f', data, off)[0]
            except struct.error:
                break
            if not is_valid_float(val):
                off += 4
                continue
            start = off
            count = 0
            while off <= n - 4:
                try:
                    v = struct.unpack_from('<f', data, off)[0]
                except struct.error:
                    break
                if not is_valid_float(v):
                    break
                count += 1
                off += 4
            runs.append((start, count))
        
        candidates = []
        for start, count in runs:
            if count >= vertex_count * 4:
                # Evaluate first 40 floats for range
                vals = [struct.unpack_from('<f', data, start + i * 4)[0] for i in range(min(count, 40))]
                rng = max(abs(v) for v in vals)
                if rng < 5.0:  # UV-ish range
                    candidates.append((start, count, rng))
        
        # Pick the closest-to-UV run (lowest range, smallest start)
        if not candidates:
            return None, None
        candidates.sort(key=lambda t: (t[2], t[0]))
        return candidates[0][0], candidates[0][1]
    
    # First try legacy known layout at 0x20c0 (normals+uv in stride 32)
    def read_stream2(uv_off):
        stride = 32
        uv_offset_in_stride = 24
        if uv_off is None:
            return None
        if uv_off + stride * vertex_count > len(data):
            return None
        uvs = []
        for i in range(vertex_count):
            try:
                u = struct.unpack_from('<f', data, uv_off + i * stride + uv_offset_in_stride)[0]
                v = struct.unpack_from('<f', data, uv_off + i * stride + uv_offset_in_stride + 4)[0]
            except Exception:
                return None
            if not (-10.0 < u < 10.0 and -10.0 < v < 10.0):
                return None
            uvs.append((u, v))
        return uvs
    
    uvs = read_stream2(0x20c0)
    if uvs is None:
        uvs = read_stream2(expected_uv_off)
    
    # If no UVs yet, try a packed UV-only run (stride 16, 4 floats per vertex: uv0, uv1?)
    if uvs is None:
        run_start, _ = find_uv_run()
        if run_start is not None:
            try:
                uvs = []
                for i in range(vertex_count):
                    u = struct.unpack_from('<f', data, run_start + i * 16)[0]
                    v = struct.unpack_from('<f', data, run_start + i * 16 + 4)[0]
                    uvs.append((u, v))
            except Exception:
                uvs = None
    
    # Fallback: try hardcoded alternate start at 0x31c0 (observed secondary UV block)
    if uvs is None:
        try:
            uvs = []
            for i in range(vertex_count):
                u = struct.unpack_from('<f', data, 0x31c0 + i * 16)[0]
                v = struct.unpack_from('<f', data, 0x31c0 + i * 16 + 4)[0]
                uvs.append((u, v))
        except Exception:
            uvs = None
    
    return uvs


def find_dds_variants(base_name):
    """Find DDS textures for a given model.
    
    Faithful rule: only make variants when there are multiple DDS files that
    share the same base stem. We do *not* auto-scan sequential numbers anymore.
    Examples treated as variants:
      - caha000.dds, caha000_alt.dds, caha000_v2.dds
      - caha000.dds, caha000-1.dds, caha000-2.dds
    If only one DDS is found for the stem, no variants are created.
    """
    script_dir = Path(__file__).resolve().parent
    repo_dir = script_dir.parent
    cacc_dir = repo_dir / "cacc"

    stem = base_name
    patterns = [
        f"{stem}.dds",
        f"{stem}_*.dds",
        f"{stem}-*.dds",
    ]

    candidates = []
    for pat in patterns:
        candidates.extend(sorted(cacc_dir.glob(pat)))

    # Deduplicate while preserving order
    seen = set()
    variants = []
    for p in candidates:
        if p not in seen:
            variants.append(p)
            seen.add(p)

    return variants


def dds_to_png(dds_path, output_path, model_name="texture"):
    """Convert DDS to PNG; fallback to copying DDS if conversion fails."""
    png_path = output_path / f"{model_name}.png"
    try:
        from PIL import Image
    except ImportError:
        Image = None
        try:
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "pillow", "-q"], check=False, timeout=30)
            from PIL import Image  # type: ignore
        except Exception:
            Image = None
    if Image is not None:
        try:
            with Image.open(dds_path) as img:
                img.save(png_path, "PNG")
            return f"{model_name}.png"
        except Exception:
            pass
    try:
        dds_out = output_path / f"{model_name}.dds"
        shutil.copy2(dds_path, dds_out)
        return f"{model_name}.dds"
    except Exception:
        return None


def create_mtl_file(mtl_path, texture_name):
    """Create a basic MTL file referencing the texture.
    
    texture_name can be "texture.png", "texture.dds", or "" for no texture.
    """
    mtl_content = f"""newmtl material0
Ka 1.000 1.000 1.000
Kd 1.000 1.000 1.000
Ks 0.000 0.000 0.000
d 1.0
illum 1"""
    
    if texture_name:
        mtl_content += f"\nmap_Kd {texture_name}\n"
    else:
        mtl_content += "\n"
    
    mtl_path.write_text(mtl_content)


def extract_rrm_to_obj_with_uvs(rrm_path, obj_path, mtl_name="model.mtl"):
    """Extract RRM to OBJ with UV coordinates.
    
    This is an extended version of auto_extract_rrm that includes:
    - UV texture coordinates (vt lines)
    - Normal indices in face definitions (v/vt/vn format)
    - MTL file reference
    """
    data = read_bytes(rrm_path)
    
    # Read header offsets
    try:
        idx_off = struct.unpack_from("<I", data, 0xb0)[0]
        vert_off = struct.unpack_from("<I", data, 0xb4)[0]
    except struct.error:
        raise RuntimeError("Failed to read header offsets (0xb0/0xb4)")
    
    # Read indices
    idx_vals = []
    off = idx_off
    while off < len(data) - 3:
        try:
            val = struct.unpack_from("<I", data, off)[0]
            if val > 100000:
                break
            idx_vals.append(val)
            off += 4
        except struct.error:
            break
    
    # Ensure divisible by 3
    if len(idx_vals) % 3 != 0:
        idx_vals = idx_vals[:((len(idx_vals) // 3) * 3)]
    
    if not idx_vals:
        raise RuntimeError("No index data found")
    
    max_index = max(idx_vals) if idx_vals else 0
    required_vcount = max_index + 1
    
    # Read vertices using fixed stride (12 bytes per vertex) based on required_vcount
    V = []
    for i in range(required_vcount):
        base = vert_off + i * 12
        if base + 12 > len(data):
            break
        try:
            x, y, z = struct.unpack_from("<3f", data, base)
        except struct.error:
            break
        V.append((x, y, z))
    
    # Extract UVs
    uvs = extract_uvs_from_rrm(rrm_path, len(V))
    
    # Build faces
    faces = []
    for i in range(0, len(idx_vals), 3):
        a, b, c = idx_vals[i], idx_vals[i+1], idx_vals[i+2]
        if a >= len(V) or b >= len(V) or c >= len(V):
            continue
        faces.append((a, b, c))
    
    # Deduplicate vertices (epsilon-based) — but only when we lack UVs.
    # When UVs exist, positions can share XYZ but differ in UV; keep them separate.
    if uvs:
        V_dedup = V[:]  # preserve 1:1 mapping to keep unique UVs per vertex
        map_old_to_new = list(range(len(V)))
    else:
        eps = 1e-6
        map_old_to_new = [None] * len(V)
        V_dedup = []
        
        for i, (x, y, z) in enumerate(V):
            found = False
            for j, (x2, y2, z2) in enumerate(V_dedup):
                if abs(x - x2) < eps and abs(y - y2) < eps and abs(z - z2) < eps:
                    map_old_to_new[i] = j
                    found = True
                    break
            
            if not found:
                map_old_to_new[i] = len(V_dedup)
                V_dedup.append((x, y, z))
    
    # Remap faces and build final OBJ
    faces_final = []
    for a, b, c in faces:
        a_new = map_old_to_new[a]
        b_new = map_old_to_new[b]
        c_new = map_old_to_new[c]
        if a_new != b_new and b_new != c_new and c_new != a_new:  # non-degenerate
            faces_final.append((a_new, b_new, c_new))
    
    # Write OBJ with MTL reference
    obj_lines = [f"mtllib {mtl_name}\n", "usemtl material0\n"]
    
    # Vertices
    for x, y, z in V_dedup:
        obj_lines.append(f"v {x:.6f} {y:.6f} {z:.6f}\n")
    
    # Texture coordinates (if we have them)
    if uvs:
        # Map UVs to deduplicated vertices
        uvs_dedup = [None] * len(V_dedup)
        for old_i, new_i in enumerate(map_old_to_new):
            if old_i < len(uvs):
                uvs_dedup[new_i] = uvs[old_i]
        
        # Write raw UVs; the game relies on sampler repeat rather than pre-wrapping
        for i, uv in enumerate(uvs_dedup):
            if uv is None:
                uvs_dedup[i] = (0.0, 0.0)
            else:
                u, v = uv
                if not (math.isfinite(u) and math.isfinite(v)):
                    uvs_dedup[i] = (0.0, 0.0)
                else:
                    uvs_dedup[i] = (u, v)

        # Write texture coordinates
        for u, v in uvs_dedup:
            obj_lines.append(f"vt {u:.6f} {v:.6f}\n")
    
    # Faces with texture indices
    for a, b, c in faces_final:
        if uvs:
            # v/vt format (vertex/texture)
            obj_lines.append(f"f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}\n")
        else:
            # v format only
            obj_lines.append(f"f {a+1} {b+1} {c+1}\n")
    
    obj_path.write_text("".join(obj_lines))
    return len(V_dedup), len(faces_final)


def organize_models():
    """Main function: Extract all RRM models and organize with textures."""
    
    # Use absolute path resolution
    script_dir = Path(__file__).resolve().parent
    repo_dir = script_dir.parent
    cacc_dir = repo_dir / "cacc"
    output_dir = repo_dir / "Models"
    
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    
    rrm_files = sorted(cacc_dir.glob("*.rrm"))
    
    print(f"Processing {len(rrm_files)} RRM files...\n")
    
    stats = {"success": 0, "error": 0, "multi": 0, "single": 0}
    
    for rrm_path in rrm_files:
        base_name = rrm_path.stem
        dds_variants = find_dds_variants(base_name)
        
        if not dds_variants:
            # No textures, just extract model
            model_dir = output_dir / base_name
            model_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                obj_path = model_dir / f"{base_name}.obj"
                mtl_path = model_dir / f"{base_name}.mtl"
                
                vcount, fcount = extract_rrm_to_obj_with_uvs(
                    str(rrm_path), obj_path, f"{base_name}.mtl"
                )
                create_mtl_file(mtl_path, "")
                
                shutil.copy(rrm_path, model_dir / rrm_path.name)
                
                print(f"✓ {base_name:20s}: {vcount:4d} verts, {fcount:3d} faces (no texture)")
                stats["success"] += 1
                stats["single"] += 1
            except Exception as e:
                print(f"✗ {base_name:20s}: {e}")
                stats["error"] += 1
        
        elif len(dds_variants) == 1:
            # Single variant
            model_dir = output_dir / base_name
            model_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                obj_path = model_dir / f"{base_name}.obj"
                mtl_path = model_dir / f"{base_name}.mtl"
                
                vcount, fcount = extract_rrm_to_obj_with_uvs(
                    str(rrm_path), obj_path, f"{base_name}.mtl"
                )
                
                # Convert/copy texture, naming it after the DDS variant
                dds_path = dds_variants[0]
                dds_base_name = dds_path.stem
                texture_filename = dds_to_png(dds_path, model_dir, dds_base_name)
                
                create_mtl_file(mtl_path, texture_filename)
                shutil.copy(rrm_path, model_dir / rrm_path.name)
                
                print(f"✓ {base_name:20s}: {vcount:4d} verts, {fcount:3d} faces ({texture_filename})")
                stats["success"] += 1
                stats["single"] += 1
            except Exception as e:
                print(f"✗ {base_name:20s}: {e}")
                stats["error"] += 1
        
        else:
            # Multiple variants - create subfolders
            model_base_dir = output_dir / base_name
            
            for variant_idx, dds_path in enumerate(dds_variants):
                variant_name = dds_path.stem  # e.g., "caha000" from caha000.dds
                variant_dir = model_base_dir / f"variant_{variant_idx}"
                variant_dir.mkdir(parents=True, exist_ok=True)
                
                try:
                    obj_path = variant_dir / f"{variant_name}.obj"
                    mtl_path = variant_dir / f"{variant_name}.mtl"
                    
                    vcount, fcount = extract_rrm_to_obj_with_uvs(
                        str(rrm_path), obj_path, f"{variant_name}.mtl"
                    )
                    
                    # Convert/copy texture with the DDS variant name
                    texture_filename = dds_to_png(dds_path, variant_dir, variant_name)
                    
                    create_mtl_file(mtl_path, texture_filename)
                    
                    if variant_idx == 0:  # Only copy RRM once
                        shutil.copy(rrm_path, variant_dir / rrm_path.name)
                    
                except Exception as e:
                    print(f"  ✗ {variant_name}: {e}")
                    stats["error"] += 1
                    continue
            
            print(f"✓ {base_name:20s}: {len(dds_variants)} variants with textures")
            stats["success"] += 1
            stats["multi"] += 1
    
    print(f"\n{'='*60}")
    print(f"Success: {stats['success']}, Errors: {stats['error']}")
    print(f"Single variants: {stats['single']}, Multi variants: {stats['multi']}")
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    organize_models()
