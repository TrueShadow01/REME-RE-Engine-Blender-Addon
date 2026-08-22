# Pragmata mesh support

Pragmata `.mesh.251121828` import is supported. Export is **experimental** and limited to same-topology paste-back of meshes originally imported by this addon.

The implementation targets Pragmata `typing` 2 blend shapes. Its layout differs from Monster Hunter Wilds and must not use the Wilds export path.

## Status

| Area | Status |
|---|---|
| Mesh import | Supported |
| Shape-key import | Supported |
| Same-topology export | Experimental |
| Remeshing or vertex-count changes | Not supported |
| Weight-paint export | Not supported |
| New meshes created in Blender | Not supported |

The exporter preserves imported binary streams that Blender cannot reconstruct. It has not been independently validated across multiple retail assets or game versions.

Contributor-reported test asset:

`natives/stm/character/ch/ch01/ch0100/10/ch0100_10.mesh.251121828`

## Supported workflow

1. Import the original Pragmata mesh.
2. Move existing vertices or edit existing shape-key deltas.
3. Keep the original vertex count, submesh layout, and armature.
4. Export as `.mesh.251121828`.

Vertex reordering is allowed only when `pragmata_src_index` remains a complete permutation of the imported vertex range.

## Unsupported operations

Do not:

- add, delete, dissolve, remesh or split vertices.
- change the number of submeshes containing shape keys.
- weight-paint or modify vertex groups expecting those changes to export.
- remove the stored `pragmata_*` attributes or collection properties.
- enable operations such as `autoSolveRepeatedUVs` or `preserveSharpEdges` when they split vertices.
- export a mesh that was not originally imported through this Pragmata path.

Export supports exactly one morphing submesh. It aborts if the topology or stored source-index mapping is incomplete or corrupt.

## Stored Blender data

Import stores the binary data needed for paste-back.

Per-vertex attributes:

| Attribute | Purpose |
|---|---|
| `pragmata_src_index` | Original global vertex index |
| `pragmata_wt_0..3` | Original type-4 weight stream |
| `pragmata_ew_0..3` | Original type-7 extra-weight stream |
| `pragmata_ax_0..3` | Morph auxiliary data |
| `pragmata_map` | Blend-shape vertex map |

Collection properties:

| Property | Purpose |
|---|---|
| `pragmata_aux_extra` | Encoded auxiliary data |
| `pragmata_veSize` | Original mesh-buffer value |
| `pragmata_unkn1` | Original mesh-buffer value |
| `pragmata_nverts` | Imported vertex count |
| `pragmata_blend_header` | Imported blend-header grouping |

Weight-paint changes are not written. Export restores the imported type-4 and type-7 streams instead.

## Format notes

| Field | Value |
|---|---|
| Mesh extension | `.mesh.251121828` |
| Internal version | `250707828` |
| Addon version mapping | `VERSION_PRAG = 135` |
| Blend-shape typing | `2` |
| Shape-key deltas | Float16 XYZ, 8 bytes per vertex per shape |
| MDF extension | `.mdf2.51` |
| TEX version | `251111100` |

The vertex-buffer tail is arranged as:

```text
[aux data] [896-byte extra block] [u32 vertex map] [float16 XYZ deltas]
```

`MeshBufferHeader.sunbreakSecondUnknown` stores the vertex-map and delta offsets as two little-endian `u32` values.

The type-7 stream is not reconstructed from Blender vertex groups. It is preserved from the imported mesh and pasted back during export.

These details are based on the contributed implementation and observed asset structure. They should not be treated as a complete specification of every Pragmata mesh variant.

## Validation

Before considering an export successful:

1. Run the Pragmata unit tests.
2. Confirm export reports the original vertex count.
3. Re-import the exported mesh.
4. Verify the mesh and shape keys in Blender.
5. Test the result in game.

A passing unit test confirms serialization behavior but does not by itself prove Blender or in-game compatibility.
