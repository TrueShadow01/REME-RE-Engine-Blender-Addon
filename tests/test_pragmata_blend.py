import importlib
import struct
import sys
import types
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def _load_mesh_modules():
    if "modules.mesh.file_re_mesh" in sys.modules:
        return sys.modules["modules.mesh.file_re_mesh"], sys.modules[
            "modules.mesh.re_mesh_parse"
        ]
    if "modules" not in sys.modules:
        modules = types.ModuleType("modules")
        modules.__path__ = [str(ROOT / "modules")]
        sys.modules["modules"] = modules
    if "modules.mesh" not in sys.modules:
        mesh = types.ModuleType("modules.mesh")
        mesh.__path__ = [str(ROOT / "modules" / "mesh")]
        sys.modules["modules.mesh"] = mesh
    file_re_mesh = importlib.import_module("modules.mesh.file_re_mesh")
    re_mesh_parse = importlib.import_module("modules.mesh.re_mesh_parse")
    return file_re_mesh, re_mesh_parse


class PragmataBlendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.file_re_mesh, cls.re_mesh_parse = _load_mesh_modules()

    def test_float16_buffer_drops_unused_fourth_half(self):
        rec = np.zeros((4, 4), dtype="<f2")
        rec[0] = (1.0, -2.0, 0.5, 99.0)
        rec[1] = (0.0, 0.0, 0.0, 1.0)
        rec[2] = (-0.125, 8.0, 0.00390625, 0.0)
        rec[3] = (100.0, -100.0, 0.0, 0.0)
        out = self.re_mesh_parse.ReadBlendShapeFloat16Buffer(rec.tobytes(), tags=set())
        self.assertEqual(out.shape, (4, 3))
        self.assertTrue(np.allclose(out[0], (1.0, -2.0, 0.5), atol=1e-3))
        self.assertTrue(np.allclose(out[2], (-0.125, 8.0, 0.00390625), atol=1e-3))

    def test_blend_shape_name_prefix(self):
        name = self.file_re_mesh._pragmataBlendShapeName
        self.assertEqual(name("crct_eye"), "Neutral_geo_cbs.crct_eye")
        self.assertEqual(
            name("Neutral_geo_cbs.crct_eye"), "Neutral_geo_cbs.crct_eye"
        )
        self.assertEqual(name("head.crct_eye"), "head.crct_eye")
        self.assertEqual(name(""), "")

    def test_remap_header_updates_morph_and_keeps_foreign_params(self):
        remap = self.file_re_mesh.remapPragmataBlendHeader
        header = {
            "subTable": [
                [10, 0, 50, 256],
                [60, 0, 7, 99],
                [67, 0, 3, 1],
            ]
        }
        table = remap(header, {10: 0, 60: 50, 67: 57}, morphExportStart=0, morphVertCount=40)
        self.assertEqual(table[0], [0, 0, 40, 256])
        self.assertEqual(table[1], [50, 0, 7, 99])
        self.assertEqual(table[2], [57, 0, 3, 1])

    def test_fallback_does_not_use_diana_vert_counts(self):
        morph, extras, meta = self.file_re_mesh.fallbackPragmataBlendSubs(
            [
                (0, 8, 0, False, None),
                (8, 20, 1, True, None),
                (28, 4, 2, False, None),
            ]
        )
        self.assertEqual(morph, (8, 0, 20, 256))
        self.assertEqual(extras, [(0, 0, 8, 0), (28, 0, 4, 512)])
        self.assertEqual(meta[0]["subCount"], 1)
        self.assertEqual(meta[1]["subCount"], 2)

    def test_serialize_uses_imported_target_grouping(self):
        AABB = self.file_re_mesh.AABB
        aabb = AABB()
        aabb.min.x = aabb.min.y = aabb.min.z = 0.0
        aabb.max.x = aabb.max.y = aabb.max.z = 1.0
        extra = [(10, 0, 8, 99), (18, 0, 4, 7)]
        buf = self.file_re_mesh.serializePragmataBlendShapeRegion(
            [
                {
                    "targets": [
                        {
                            "blendShapeNum": 3,
                            "subEntries3": [(0, 0, 10, 256)],
                            "extraSubs": extra,
                            "aabb": aabb,
                            "blendSSIndex": 0,
                            "targetMeta": [
                                {
                                    "ssIndex": 0,
                                    "nSh": 3,
                                    "unkn0": 0,
                                    "subCount": 1,
                                    "unkn2": 1,
                                    "subStart": 0,
                                },
                                {
                                    "ssIndex": 0,
                                    "nSh": 0,
                                    "unkn0": 0,
                                    "subCount": 2,
                                    "unkn2": 0,
                                    "subStart": 1,
                                },
                            ],
                        }
                    ],
                    "typing": 2,
                    "padding1": 1,
                    "blendS": [0, 0, 0],
                    "targetMeta": [
                        {
                            "ssIndex": 0,
                            "nSh": 3,
                            "unkn0": 0,
                            "subCount": 1,
                            "unkn2": 1,
                            "subStart": 0,
                        },
                        {
                            "ssIndex": 0,
                            "nSh": 0,
                            "unkn0": 0,
                            "subCount": 2,
                            "unkn2": 0,
                            "subStart": 1,
                        },
                    ],
                }
            ],
            baseOffset=0,
        )
        morph = struct.unpack_from("<IIII", buf, 96)
        self.assertEqual(morph, (0, 0, 10, 256))
        extra0 = struct.unpack_from("<IIII", buf, 112)
        self.assertEqual(extra0, (10, 0, 8, 99))
        # 3 sub records → target list at 96 + 48 = 144; slot 1 at 160, subCount at +6
        n_sub = struct.unpack_from("<B", buf, 144 + 16 + 6)[0]
        self.assertEqual(n_sub, 2)

    def test_serialize_puts_morph_submesh_before_targets(self):
        AABB = self.file_re_mesh.AABB
        aabb = AABB()
        aabb.min.x, aabb.min.y, aabb.min.z = -1.0, -2.0, -3.0
        aabb.max.x, aabb.max.y, aabb.max.z = 4.0, 5.0, 6.0
        extra = [
            (100, 0, 2921, 0),
            (3021, 0, 1429, 1280),
            (4450, 0, 1429, 1536),
            (5879, 0, 693, 1792),
            (6572, 0, 50, 1),
        ]
        buf = self.file_re_mesh.serializePragmataBlendShapeRegion(
            [
                {
                    "targets": [
                        {
                            "blendShapeNum": 2,
                            "subEntries3": [(0, 0, 10982, 256)],
                            "extraSubs": extra,
                            "aabb": aabb,
                            "blendSSIndex": 0,
                        }
                    ],
                    "typing": 2,
                    "padding1": 1,
                    "blendS": [0, 0, 0],
                }
            ],
            baseOffset=16,
        )
        n_targets, typing = struct.unpack_from("<HH", buf, 48)
        self.assertEqual((n_targets, typing), (1, 2))
        morph = struct.unpack_from("<IIII", buf, 96)
        self.assertEqual(morph, (0, 0, 10982, 256))
        tooth = struct.unpack_from("<IIII", buf, 112)
        self.assertEqual(tooth, (100, 0, 2921, 0))
        target0_ss, target0_n, _unkn0, sub_count, _unkn2 = struct.unpack_from(
            "<HHHBB", buf, 192
        )
        self.assertEqual((target0_ss, target0_n, sub_count), (0, 2, 1))
        target0_sub_ptr = struct.unpack_from("<Q", buf, 200)[0]
        self.assertEqual(target0_sub_ptr, 16 + 96)

    def test_source_indices_accept_complete_reordered_permutation(self):
        validate = self.file_re_mesh.validatePragmataSourceIndices
        ok, error = validate(
            [
                np.array([2, 0, 1], dtype=np.int32),
                np.array([4, 3], dtype=np.int32),
            ],
            5,
        )

        self.assertTrue(ok, error)

    def test_source_indices_reject_changed_or_corrupt_topology(self):
        validate = self.file_re_mesh.validatePragmataSourceIndices
        invalidCases = [
            ([None], 4),
            ([np.array([0, 1, 2], dtype=np.int32)], 4),
            ([np.array([0, 1, 1, 3], dtype=np.int32)], 4),
            (
                [
                    np.array([0, 2], dtype=np.int32),
                    np.array([1, 3], dtype=np.int32),
                ],
                4,
            ),
            ([np.array([0, 1, 2, 4], dtype=np.int32)], 4),
        ]

        for chunks, storedCount in invalidCases:
            with self.subTest(chunks=chunks, storedCount=storedCount):
                ok, error = validate(chunks, storedCount)
                self.assertFalse(ok)
                self.assertTrue(error)

if __name__ == "__main__":
    unittest.main()
