"""Experimental RE2 RT .scn.20 static placement import (no SCN export)"""
import json
import math
import struct
from collections import Counter
from pathlib import Path

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Quaternion, Vector

from .mesh.blender_re_mesh import importREMeshFile

class SceneError(ValueError):
    pass

class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, size):
        if size < 0 or self.pos < 0 or self.pos + size > len(self.data):
            raise SceneError(f"Truncated SCN at {self.pos:#x}")
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def unpack(self, fmt, offset=None):
        if offset is not None:
            self.pos = offset
        return struct.unpack("<" + fmt, self.take(struct.calcsize("<" + fmt)))

    def align(self, alignment):
        if alignment < 1 or alignment & (alignment - 1):
            raise SceneError("Invalid schema alignment")
        self.take((-self.pos) % alignment)

    def field(self, field):
        self.align(field["align"])
        if field["type"] in {"String", "Resource"}:
            length, = self.unpack("I")
            raw = self.take(length * 2)
            if raw and not raw.endswith(b"\0\0"):
                raise SceneError("Unterminated RSZ string")
            return raw.decode("utf-16le").rstrip("\0")
        return self.take(field["size"])

def read_scene(path, schema):
    path = Path(path)
    if not path.name.lower().endswith(".scn.20"):
        raise SceneError("This importer supports RE2 RT .scn.20 only")

    reader = Reader(path.read_bytes())
    h = reader.unpack("6I5Q")
    if h[0] != 0x004E4353:
        raise SceneError("Not an SCN file")
    records = []

    for _ in range(h[1]):
        reader.take(16)
        records.append(reader.unpack("iiHhi"))

    folders = [reader.unpack("ii", h[6] + i * 8) for i in range(h[3])]
    base = h[10]
    r = reader.unpack("6I3Q", base)

    if r[0] != 0x005A5352 or r[1] != 16:
        raise SceneError("Unsupported embedded RSZ version")
    if r[2] > len(reader.data) // 4 or r[3] > len(reader.data) // 8:
        raise SceneError("Invalid RSZ counts")

    table = reader.unpack(f"{r[2]}I", base + 48)
    types = [reader.unpack("II", base + r[6] + i * 8) for i in range(r[3])]
    external = {reader.unpack("IIQ", base + r[8] + i * 16)[0] for i in range(r[4])}

    if not types or types[0] != (0, 0):
        raise SceneError("Invalid null instance")
    if any(i >= len(types) for i in table):
        raise SceneError("Invalid object table")

    reader.pos = base + r[7]
    instances = [("", [])]
    for index, (type_id, crc) in enumerate(types[1:], 1):
        definition = schema.get(f"{type_id:x}")
        if definition is None or int(definition["crc"], 16) != crc:
            raise SceneError(f"Missing/Mismatched RE2 RT schema: {type_id:08x}")

        values = []
        if index not in external:
            for field in definition["fields"]:
                if field["array"]:
                    reader.align(4)
                    count, = reader.unpack("I")
                    if count > len(reader.data) - reader.pos:
                        raise SceneError("Invalid RSZ array length")
                    value = [reader.field(field) for _ in range(count)]
                else:
                    value = reader.field(field)
                values.append(value)
        instances.append((definition["name"], values))
    if reader.pos != len(reader.data):
        raise SceneError(f"Unconsumed RSZ bytes: {len(reader.data) - reader.pos}")

    def instance(index, expected=None):
        if not 0 <= index < len(table):
            raise SceneError("Invalid object/component index")
        name, fields = instances[table[index]]
        if expected and name != expected:
            raise SceneError(f"Expected {expected}, found {name}")
        return name, fields

    nodes, warnings, ignored = {}, [], Counter()
    for index, parent in folders:
        _, fields = instance(index, "via.Folder")
        if len(fields) != 7:
            raise SceneError("Unsupported Folder layout")

        nodes[index] = dict(name=fields[0], parent=parent, draw=bool(fields[3][0]), trs=None, meshes=[])
        if fields[5]:
            warnings.append(f"Linked scene not expanded: {fields[5]}")

    for index, parent, count, _, prefab in records:
        _, fields = instance(index, "via.GameObject")
        if len(fields) != 5 or index in nodes:
            raise SceneError("Unsupported/duplicate GameObject")

        node = dict(name=fields[0], parent=parent, draw=bool(fields[3][0]), trs=None, meshes=[], unsupported=False)
        for component in range(index + 1, index + 1 + count):
            name, values = instance(component)
            if name == "via.Transform":
                if len(values) != 8 or node["trs"] is not None:
                    raise SceneError("Unsupported Transform layout")
                node["trs"] = [struct.unpack("<4f", v) for v in values[:3]]
                if not all(math.isfinite(v) for row in node["trs"] for v in row):
                    raise SceneError("Non-finite transform")
                if sum(v * v for v in node["trs"][1]) < 1e-12:
                    raise SceneError("Zero quaternion")
                node["unsupported"] = bool(values[3]) or any(any(v) for v in values[4:])
                if node["unsupported"]:
                    warnings.append(f"Skipped joint/special transform: {fields[0]}")
            elif name == "via.render.Mesh":
                if len(values) != 59:
                    raise SceneError("Unsupported Mesh layout")
                node["meshes"].append((values[2], values[3]))
            else:
                ignored[name] += 1

        if node["trs"] is None:
            raise SceneError(f"Missing Transform: {fields[0]}")
        nodes[index] = node
    for index in nodes:
        seen, current = set(), index
        while current != -1:
            if current not in nodes or current in seen:
                raise SceneError("Missing parent or cyclic hierachy")
            seen.add(current)
            current = nodes[current]["parent"]

    return nodes, warnings, ignored

def import_scene(path, schema, root, materials=False):
    if bpy.context.mode != "OBJECT":
        raise SceneError("Switch Blender to Object Mode before importing")
    root = Path(root).resolve()
    if not root.is_dir():
        raise SceneError("Choose the extracted natives/stm folder")
    nodes, warnings, ignored = read_scene(path, schema)

    def visible(index):
        while index != -1:
            node = nodes[index]
            if not node["draw"] or node.get("unsupported", False):
                return False
            index = node["parent"]
        return True

    def resolve(resource, version):
        candidate = (root / (resource.replace("\\", "/") + version)).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise SceneError(f"Missing/Invalid resource: {resource}{version}")
        return str(candidate)

    assets, placements = {}, []
    for index, node in nodes.items():
        if not visible(index):
            continue

        for mesh, mdf in node["meshes"]:
            if not mesh:
                continue
            if Path(mesh).stem.lower().endswith("_occ"):
                warnings.append(f"Skipped occlusion mesh: {node['name']}")
                continue
            key = (resolve(mesh, ".2109108288"), resolve(mdf, ".21") if mdf else "")
            assets[key] = None
            placements.append((index, key))

    # Only newly created Blender data is removed if the import fails
    groups = ("objects", "collections", "meshes", "armatures", "materials", "images", "node_groups")
    before = {name: set(getattr(bpy.data, name)) for name in groups}
    try:
        collection = bpy.data.collections.new(Path(path).name)
        bpy.context.scene.collection.children.link(collection)
        scene_root = bpy.data.objects.new(Path(path).stem, None)
        collection.objects.link(scene_root)
        scene_root.rotation_euler.x = math.pi / 2
        scene_root["RE_SCN_SOURCE"] = str(path)
        objects = {}
        for index, node in nodes.items():
            obj = bpy.data.objects.new(node["name"], None)
            collection.objects.link(obj)
            objects[index] = obj
            obj["RE_SCN_INDEX"] = index
            if node["trs"]:
                position, rotation, scale = node["trs"]
                quat = Quaternion((rotation[3], *rotation[:3])).normalized()
                obj.matrix_basis = Matrix.LocRotScale(Vector(position[:3]), quat, Vector(scale[:3]))

        for index, obj in objects.items():
            parent = nodes[index]["parent"]
            obj.parent = objects[parent] if parent != -1 else scene_root
            obj.matrix_parent_inverse.identity()

        options = dict(clearScene=False, loadMaterials=materials, loadMDFData=False,
                       loadShellFur=False, loadUnusedTextures=False, loadUnusedProps=False,
                       useBackfaceCulling=False, reloadCachedTextures=False, createCollections=False,
                       mergeArmature="", importArmatureOnly=False, importAllLODs=False,
                       rotate90=False, importBlendShapes=False, importShadowMeshes=False,
                       importOcclusionMeshes=False, importBoundingBoxes=False, mergeGroups=False)

        for key in assets:
            mesh, mdf = key
            previous = set(bpy.data.objects)
            mesh_warnings, errors = importREMeshFile(mesh, dict(options, mdfPath=mdf))
            warnings.extend(f"{Path(mesh).name}: {w}" for w in mesh_warnings)
            if errors:
                raise SceneError("; ".join(map(str, errors)))
            created = set(bpy.data.objects) - previous

            if not any(obj.type == "MESH" for obj in created):
                raise SceneError(f"No geometry imported: {mesh}")

            prototype = bpy.data.collections.new(Path(mesh).name + " [SCN asset]")
            for obj in created:
                for owner in list(obj.users_collection):
                    owner.objects.unlink(obj)
                prototype.objects.link(obj)
            assets[key] = prototype

        for index, key in placements:
            prototype = assets[key]
            copies = {}
            for source in prototype.objects:
                obj = source.copy()
                obj.name = nodes[index]["name"] + " | " + source.name
                obj["RE_SCN_INDEX"] = index
                collection.objects.link(obj)
                copies[source] = obj

            for source, obj in copies.items():
                if source.parent in copies:
                    obj.parent = copies[source.parent]
                    obj.matrix_parent_inverse = source.matrix_parent_inverse.copy()
                    obj.matrix_basis = source.matrix_basis.copy()
                else:
                    obj.parent = objects[index]
                    obj.matrix_parent_inverse.identity()
                    obj.matrix_basis = source.matrix_world.copy()

                for modifier in obj.modifiers:
                    if modifier.type == "ARMATURE" and modifier.object in copies:
                        modifier.object = copies[modifier.object]

        # Geometry and materials remain shared by placed objects
        # Remvoe only this import's temporary prototype objects/collections
        for prototype in assets.values():
            for source in list(prototype.objects):
                bpy.data.objects.remove(source, do_unlink=True)
            bpy.data.collections.remove(prototype)

        collection["RE_SCN_WARNINGS"] = json.dumps(warnings)
        collection["RE_SCN_IGNORED_COMPONENTS"] = json.dumps(dict(ignored))
        collection["RE_SCN_PLACEMENTS"] = len(placements)
        bpy.context.view_layer.update()

        return collection, warnings, ignored
    except Exception:
        for name in groups:
            data = getattr(bpy.data, name)
            for item in list(data):
                if item not in before[name]:
                    data.remove(item, do_unlink=True)
        raise

class ImportRESCN(bpy.types.Operator, ImportHelper):
    bl_idname = "re_mesh_cm.importscn"
    bl_label = "Import RE2 RT Scene"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".scn.20"
    filter_glob: StringProperty(default="*.scn.20", options={"HIDDEN"})
    schema_path: StringProperty(name="RE2 RT RSZ JSON", default=r"D:\RE2Extract\rszre2rt.json")
    extract_root: StringProperty(name="Extracted natives/stm", default=r"D:\RE2Extract\natives\stm")
    load_materials: BoolProperty(name="Load Materials", default=False, description="Use REME's material importer. Texture conversion may create cache files")

    def execute(self, context):
        try:
            with open(bpy.path.abspath(self.schema_path), encoding="utf-8-sig") as stream:
                schema = json.load(stream)
            collection, warnings, ignored = import_scene(self.filepath, schema, bpy.path.abspath(self.extract_root), self.load_materials)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        for warning in warnings:
            print("[RE SCN]", warning)
        print("[RE SCN] Components not reconstructed:", dict(ignored))
        self.report({"WARNING"} if warnings else {"INFO"}, f"{collection['RE_SCN_PLACEMENTS']} mesh placements. {len(warnings)} warnings. See console.")
        return {"FINISHED"}
