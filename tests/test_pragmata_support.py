import unittest
import struct
import numpy as np

from types import SimpleNamespace

from modules.mdf.file_re_mdf import getMDFVersionToGameName
from modules.mesh.file_re_mesh import (
    AABB,
    SIX_WEIGHT_GAMES,
    VERSION_PRAG,
    internalVersionToMeshFileVersionDict,
    meshFileVersionToGameNameDict,
    meshFileVersionToInternalVersionDict,
    meshFileVersionToNewVersionDict
)
from modules.mesh.re_mesh_parse import _decodePragBlendShapes
from modules.tex.enums.game_version_enum import gameNameToTexVersionDict

def make_pragmata_blend_mesh(payload, padding, target, aabbs=None, names=None):
    names = names or []

    return SimpleNamespace(
        blendShapeHeader=SimpleNamespace(
            blendShapeList=[
                SimpleNamespace(
                    padding1=padding,
                    blendTargetList=[target],
                    aabbList=aabbs or [],
                )
            ]
        ),
        meshBufferHeader=SimpleNamespace(
            vertexBuffer=payload,
            sunbreakSecondUnknown=0,
        ),
        blendShapeNameRemapList=list(range(len(names))),
        rawNameList=names,
        wildsBlendMeta=None,
    )

class PragmataSupportTests(unittest.TestCase):
    def test_retail_mesh_mappings(self):
        self.assertEqual(meshFileVersionToNewVersionDict[251121828], VERSION_PRAG)
        self.assertEqual(meshFileVersionToInternalVersionDict[251121828], 250707828)
        self.assertEqual(internalVersionToMeshFileVersionDict[250707828], 251121828)
        self.assertEqual(meshFileVersionToGameNameDict[251121828], "PRAG")
        self.assertIn(VERSION_PRAG, SIX_WEIGHT_GAMES)

    def test_retail_mdf_mapping(self):
        self.assertEqual(getMDFVersionToGameName("PRAG"), 51)
        self.assertEqual(getMDFVersionToGameName("RE9"), 51)

    def test_pragmata_and_re9_use_distinct_texture_versions(self):
        self.assertEqual(gameNameToTexVersionDict["PRAG"], 251111100)
        self.assertEqual(gameNameToTexVersionDict["RE9"], 250813143)

    def test_float16_blend_shape_decoding(self):
        payload = np.array(
            [
                [
                    [0.25, -0.5, 1.5, 99.0],
                    [1.0, 2.0, 3.0, -7.0],
                ]
            ],
            dtype="<f2"
        ).tobytes()

        target = SimpleNamespace(
            subMeshEntryList=[],
            vertCount=2,
            subMeshVertexStartIndex=12,
            blendShapeNum=1,
            blendSSIndex=0,
        )

        result = _decodePragBlendShapes(
            make_pragmata_blend_mesh(
                payload,
                padding=1,
                target=target,
                names=["Smile"],
            )
        )

        entry = result[0][12][0]

        self.assertEqual(entry.blendShapeName, "Smile")
        np.testing.assert_allclose(
            entry.deltas,
            [
                [0.25, -0.5, 1.5],
                [1.0, 2.0, 3.0],
            ],
            rtol=0,
            atol=1e-3,
        )

    def test_packed_blend_shape_decoding(self):
        x_value = 2047
        y_value = 0
        z_value = 1024

        packed_value = (
            x_value
            | (y_value << 11)
            | (z_value << 21)
        )
        payload = struct.pack("<I", packed_value)

        target = SimpleNamespace(
            subMeshEntryList=[],
            vertCount=1,
            subMeshVertexStartIndex=4,
            blendShapeNum=1,
            blendSSIndex=0,
        )

        aabb = AABB()
        aabb.min.x = -2.0
        aabb.min.y = -4.0
        aabb.min.z = -6.0
        aabb.max.x = 2.0
        aabb.max.y = 4.0
        aabb.max.z = 6.0

        result = _decodePragBlendShapes(
            make_pragmata_blend_mesh(
                payload,
                padding=0,
                target=target,
                aabbs=[aabb],
                names=["Blink"]
            )
        )

        entry = result[0][4][0]
        expected_z = 6.0 * ((2.0 * z_value / 2047.0) - 1.0)

        self.assertEqual(entry.blendShapeName, "Blink")
        np.testing.assert_allclose(
            entry.deltas[0],
            [2.0, -4.0, expected_z],
            rtol=0,
            atol=1e-6,
        )

if __name__ == "__main__":
    unittest.main()