# .RRM-Model-Viewer-Happy-Wars-Rivival
.RRM Model Viewer 



# Extraction Findings (Short, Detailed)

## Current State
- OBJ extraction (positions + faces) works via tools/rrm_converter.py autoextract; majority of meshes appear, some meshes may be missing parts due to heuristic runs.
- UV extraction is unresolved: exported textures do not map correctly.
- Texture handling: currently converts DDS -> PNG for MTL references; DDS copies still possible.

## What We Confirmed
- RRM header offsets: indices at 0xB0, positions at 0xB4; positions are 3 floats/vertex, 12-byte stride.
- Actual vertex count should be max(index)+1 (header count can differ).
- Known streams in caha000.rrm:
  - Stream2 at 0x20C0, stride 32: normals (24 bytes) + UV (8 bytes at +24). UVs include tiling values outside [0,1].
  - Packed block at 0x31C0, stride 16: 4 floats/vertex; likely two UV sets (0–1 and 2–3), values ~0–0.6 range.
- Vertex deduplication must be disabled when UVs exist; otherwise distinct UVs collapse to one vertex.

## What Works Reliably
- Geometry extraction to OBJ with faces.
- Batch processing of all 74 RRM files.
- Optional DDS copying or PNG conversion (currently PNG in Models/).

## What Fails / Unknown
- UV mapping correctness: neither Stream2 UVs nor packed UVs have been validated as matching in-game tiling/wrapping.
- Texture wrapping/sampler mode from the game is not recovered; OBJ/MTL cannot express sampler repeat/clamp fully.
- Some meshes reported missing parts (likely heuristic mis-detection of runs or incorrect vertex count in a few files).

## Hypotheses
- Game uses sampler repeat; UVs outside [0,1] should not be wrapped in data. Need the correct UV set (Stream2 vs packed) per model.
- There may be per-material transform/scaling in game code or shaders that we have not located.
<img width="260" height="137" alt="Screenshot 2026-01-04 114701" src="https://github.com/user-attachments/assets/e8380ae7-3c8b-480f-abfb-5908d3dfb025" />

## Next Steps
1) Per-model UV set trial: export three variants (Stream2 UVs, Packed UV0, Packed UV1) and visually verify against textures; adopt the correct source globally.
2) Preserve sampler intent: keep raw UVs; ensure viewers use repeat/wrap. If necessary, generate alternate MTLs with duplicated UV ranges (manual tiling) for viewers that clamp.
3) Mesh completeness: for models with missing parts, scan additional float runs or adjust vertex count detection heuristics.
4) (Optional) Keep DDS alongside PNG to avoid conversion artifacts; switch MTL map_Kd accordingly.

## Files of Interest
- tools/rrm_converter.py — geometry/heuristic extractor.
- tools/texture_extractor.py — current OBJ+UV+texture pipeline (UV heuristic, DDS->PNG).
- tools/uv_export.py — exports multiple UV variants for a single RRM for comparison.
