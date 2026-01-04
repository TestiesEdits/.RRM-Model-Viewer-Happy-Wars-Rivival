# RRM Batch Runner (C++ Wrapper)

This folder contains a small C++ CLI that wraps the existing Python converters.
It supports two modes (a simple toggle):
- `to-obj`  : Convert all `.rrm` files in an input folder to `.obj` in an output folder.
- `to-rrm`  : Convert all `.obj` files in an input folder back to `.rrm` in an output folder.

Textures: if a `.dds` with the same stem exists alongside the source file, it is copied to the output folder. MTL/PNG generation is not performed here; it delegates geometry conversion to the existing Python scripts.

## Requirements (dependencies)
- Python 3 available as `python3` (runtime for the underlying converters).
- Repo Python tools: `tools/rrm_converter.py`.
- C++17 compiler (tested with `g++`) to build the wrapper binary.

## Build
From repo root:
```bash
cd tools/runner
g++ -std=c++17 -O2 -o rrm_batch main.cpp
```

## Usage
Run from repo root so the relative path to `tools/rrm_converter.py` resolves correctly.
```bash
./tools/runner/rrm_batch --mode to-obj --input cacc --output out_objs
./tools/runner/rrm_batch --mode to-rrm --input custom_objs --output out_rrm
```

### Mode toggle
- `--mode to-obj`  (light switch ON for export)
- `--mode to-rrm`  (light switch ON for import/back-convert)

### Notes
- Conversion uses `tools/rrm_converter.py autoextract` for RRM→OBJ and `obj2rrm` for OBJ→RRM.
- Missing meshes/UV issues from the Python tool remain; this wrapper only automates batch processing.
- Place matching `.dds` next to your source files; they will be copied with the same stem.
- Output folders are created if missing.
