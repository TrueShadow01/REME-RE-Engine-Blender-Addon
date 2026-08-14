# Pragmata mesh support

Retail Pragmata character meshes are **not** Monster Hunter Wilds meshes with a different version number. The blend-shape (`typing` 2) layout, extra-weight stream, and blend-header field order all differ. Using the Wilds packer or Wilds header order on a Pragmata face mesh will boot the title and then destroy the head (hole, giant blob, or GPU validation failure).

This document is the format note for the code under `modules/mesh/`. It is written so a contributor can change the importer/exporter without any external project notes.

## Status

| Area | State |
|---|---|
| Import `.mesh.251121828` | Working. Positions, UVs, 6-bone weights, colors, armature, and `typing` 2 shape keys. |
| Export same-topology round-trip | Working if the mesh was imported with this addon (retail streams persist on the `.blend`). |
| Reorder vertices | Working. `pragmata_src_index` restores retail order on export. |
| Remesh / change vertex count | **Not supported** for faces that use extra-weight + morph aux. Blender cannot invent those tables. |
| Materials / MDF reconstruction | Preliminary (`mdf2.51`). Pink/grey viewport is expected without extracted textures. |
| Export UI | Choose **Pragmata** (`.251121828`). Do not export a Pragmata mesh as RE9 (`.250925211`). |

Worked example: default-outfit head `natives/stm/character/ch/ch01/ch0100/10/ch0100_10.mesh.251121828` (vanilla size 14 923 584 bytes). Eight submeshes; only `Face_mat` (10 982 verts) carries 107 `Neutral_geo_cbs.crct_*` keys.

## Versions

| Field | Value |
|---|---|
| File extension | `.mesh.251121828` |
| Internal header version | `250707828` |
| Addon remap | `VERSION_PRAG = 135` |
| Game name | `PRAG` |
| Blend-shape file-version set | `PRAGMATA_BLEND_SHAPE_FILE_VERSIONS` in `file_re_mesh.py` |
| MDF | `.mdf2.51` |
| TEX | `250813143` |

`250925211` is the **RE9** mesh extension (`VERSION_RE9`). Only `251121828` remaps to `VERSION_PRAG` and is listed in `PRAGMATA_BLEND_SHAPE_FILE_VERSIONS`.

## Do not use the Wilds blend path

| | Monster Hunter Wilds | Pragmata (`typing` 2) |
|---|---|---|
| Blend `typing` | 7 (face) / 3 (armor) | **2** |
| Deltas | 11/10/11 packed in streaming tails | IEEE **float16 xyz**, 8 bytes/vert/shape (4th half unused) |
| Coverage | Per streaming buffer | Dense block for the **morphing submesh only** |
| Prefix in vertex buffer | Geometry after deltas (resident layout) | Declared vertex elements, then **aux + map + deltas** |
| `sunbreakSecondUnknown` | Secondary-weight size on some titles | `(mapOffset, deltaOffset)` as two little-endian u32s |
| Extra-weight type 7 | 7th–12th bone influences | **Second bone-index pack** the face shader fetches; weights in that pack are unused |

Writing Wilds 11/10/11 into the Pragmata delta slot is interpreted as huge f16 values (~100–1000 m) and swallows the camera.

## Vertex-buffer tail (`typing` 2)

Declared elements (retail head): Pos (0) / NorTan (1) / UV (2) / UV2 (3) / Weight (4) / Color (5) / ExtraWeight (7).

Immediately after the last element:

```text
[aux: 16 bytes × nverts] [extra: 896 bytes] [map: u32 × nverts] [f16 xyz deltas]
```

For `ch0100_10`: `nverts = 59280`, aux blob = 1 186 496 bytes, face deltas = `10982 × 107 × 8` = 9 400 592 bytes.

`MeshBufferHeader.sunbreakSecondUnknown`:

- low u32 = offset of the u32 vert map inside the vertex buffer
- high u32 = offset of the float16 delta block

On `ch0100_10` those are **4743296** and **4980416**. Putting the deltas at the geometry end and leaving `sun2` at 0 makes the face shader fail to bind (eyes/teeth still draw because they are not morph targets).

`vertexElementSize` / `unkn1` on the mesh buffer header are also required for a faithful write. Import stores them on the collection (`pragmata_veSize`, `pragmata_unkn1`) and export copies them back. On `ch0100_10` they are `-7168` and `57`.

Parse (`re_mesh_parse.py`) splits that tail when `len(auxBlob) == nverts * 20 + 896` and stashes the pieces on `ParsedREMesh.pragmataBlendAux`. Import then copies them onto the Blender mesh; export must **not** re-read an unpacked game dump.

## Extra-weight (type 7) and the 6-weight pack

Type 7 is **not** “more influences.” The face shader fetches a second 16-byte-per-vert index pack. Encoding it as empty / Wilds extra weights leaves facial bones around the eyes unbound (lumps on the nose and eye sockets).

The main 6-weight pack (type 4) uses pad bits **`0b11`** in the compressed index word (`weightIndexPad = 3` for `VERSION_PRAG`).

Blender vertex groups cannot represent the type-7 pack. Import stores **both** type-4 and type-7 as raw INT attributes (see below) and export **pastes those bytes back** when vertex count still matches. Weight-paint edits to vertex groups are not written; the imported streams win so the face shader keeps the extra index pack. Same-topology sculpt (move verts, keep count and armature) is the supported path.

## Blend-shape header field order

Wilds writes BlendTargets immediately after BlendShapeData. Retail `ch0100_10` stores:

1. Six 16-byte **submesh records** (morphing submesh first, then tooth / eyes / shell / leftover)
2. BlendTarget slots (`targetCount + typing`)
3. AABB, blendS (16-aligned), blendSS

The engine walks that layout. Using the Wilds order makes it read the mesh buffer header as vertex counts and explode the head.

Shape-key names on export are prefixed `Neutral_geo_cbs.` when the Blender key is a bare `crct_*` name (`_pragmataBlendShapeName`).

`serializePragmataBlendShapeRegion` writes the imported BlendTarget grouping when the `.blend` has `pragmata_blend_header` (captured on import: morphing submesh first, then extra records with their retail `param` values and leftover collapse). Without that snapshot, export falls back to one record per non-morphing submesh (`param = materialIndex << 8`) and prints a warning. Re-import the mesh to paste retail grouping; do not reconstruct it from one character's vertex counts.

A 16-byte **normal-recalc stub** is written immediately before the blend header (`fileHeader.normalRecalcOffset`).

## What is stored on the `.blend`

Import writes these so a later export does not need the unpacked `.mesh` on disk.

Per-vertex INT attributes (POINT domain), 4×i32 = 16 bytes where noted:

| Attribute | Content |
|---|---|
| `pragmata_src_index` | Global vertex-buffer index at import (used to restore order) |
| `pragmata_wt_0..3` | Type-4 weight stream |
| `pragmata_ew_0..3` | Type-7 extra-weight stream |
| `pragmata_ax_0..3` | Morph aux 16 bytes/vert |
| `pragmata_map` | u32 vert map |

On the RE mesh collection:

| Property | Content |
|---|---|
| `pragmata_aux_extra` | Base64 of the 896-byte aux extra |
| `pragmata_veSize` | Mesh buffer `vertexElementSize` |
| `pragmata_unkn1` | Mesh buffer `unkn1` |
| `pragmata_nverts` | Vertex count at import |
| `pragmata_blend_header` | JSON snapshot of typing-2 BlendTarget grouping (params, leftover records) |

Export (`assemblePragmataBlendAux`) rebuilds `parsedMesh.pragmataBlendAux` from those properties only. If any submesh is missing `pragmata_wt_*` / `pragmata_ew_*`, retail skinning streams are **not** written. When they are present they replace the buffers built from Blender vertex groups (type 4 and type 7).

`pragmata_src_index` must be a complete `nverts`-long range (a permutation). That is a **reorder**, not a remesh. Changing vertex count, dissolving verts, or adding verts breaks the tables.

Same-topology sculpt (move verts, keep count, keep armature) can keep using the stored tables. Shape-key *deltas* always come from Blender keys (float16 xyz), not from a pasted vanilla tail.

## Code map

| File | Role |
|---|---|
| `modules/mesh/file_re_mesh.py` | Version maps; `buildPragmataBlendShapeExport`; `serializePragmataBlendShapeRegion`; paste weight/extra/aux/`sun2` in `ParsedREMeshToREMesh` |
| `modules/mesh/re_mesh_parse.py` | `_decodePragBlendShapes` (f16 and packed); split aux/map; fill `pragmataBlendAux` |
| `modules/mesh/blender_re_mesh.py` | Import attributes; export permute + `assemblePragmataBlendAux` |

Do not decode the 16-byte aux table as shape-key deltas. That produces ~1 cm per-vert offsets that stack into a giant skin blob.

## Approaches that failed (do not retry)

These were measured against `ch0100_10`. Symptoms are specific; do not “fix” them by switching back to the Wilds packer.

| Approach | Result | Why |
|---|---|---|
| Export without the morph tail (~5.3 MB) | Fatal D3D `E_INVALIDARG` | Face shader still binds the tail |
| Wilds 11/10/11 packer + Pragmata header | Title boots; head is a hole / huge flash | Packed bits read as huge f16 |
| Decode aux as keys, then encode f16 | Giant skin blob | Aux is topology, not deltas |
| Vanilla delta bytes + Wilds **field order** | Giant blob | Engine reads BlendTargets as vert counts |
| Retail field order, deltas at geometry end, `sun2` = 0 | Face missing; eyes/teeth OK | Morph bind uses `sun2` |
| Retail tail + `sun2`, but Blender-empty type 7 | Face present; meat on nose / eye sockets | Extra-weight is a second index pack |
| Splice vanilla nortan only | Same lumps | Normals were not the bug |

A round-trip of an **unsculpted** imported mesh should match vanilla on type-4, type-7, color, and aux bytes. Positions / nortan / UV will differ slightly (Blender float). Float16 shape-key deltas typically match vanilla within one ULP (on `ch0100_10`, 1 of 1 175 074 records).

## Testing

- Export as `*.mesh.251121828`. Console should print `Pragmata streams from Blender:` with `nverts` equal to the imported count, then `Pragmata blend tail:` with the retail `mapOff` / `deltaOff` when those collection props were present.
- Face export **refuses** if morph aux/map/extra are missing (a zeroed tail fails GPU validation). Re-import the mesh; remesh is not supported.
- Prefer a mod manager overlay over dropping files into the game’s `natives\` folder.
- `autoSolveRepeatedUVs` / `preserveSharpEdges` split vertices and will drop the stored attribute tables (vertex count no longer matches).
