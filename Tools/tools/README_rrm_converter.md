RRM <-> OBJ Converter
=====================

Usage
-----

From the repository root run the script in `tools`:

```bash
python3 tools/rrm_converter.py rrm2obj path/to/model.rrm path/to/output.obj
python3 tools/rrm_converter.py obj2rrm path/to/model.obj path/to/output.rrm
```

Notes and limitations
---------------------
- This tool uses heuristics to extract float triplets from binary `.rrm` files. Many
  game formats are proprietary; this script attempts a best-effort extraction and may
  not produce a complete mesh with faces, UVs or materials.
- The `obj2rrm` writer produces a minimal, custom `.rrm` layout (header + uint32 count
  + float triples) suitable for round-trip with models produced by this tool.
- If you need a precise exporter/importer for a known `.rrm` variant, provide a
  specification or example file and we can adapt the parser.

Contact
-------
If you want me to refine the parser for a specific `.rrm` sample, attach the file
and I'll implement a targeted extractor.
