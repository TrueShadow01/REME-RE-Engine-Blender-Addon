#Author: NSA Cloud
import bpy

result = bpy.ops.re_asset.initialize_library()

if "FINISHED" not in result:
    raise RuntimeError("Asset Library initialization failed")

bpy.ops.wm.save_mainfile()
bpy.ops.wm.quit_blender()