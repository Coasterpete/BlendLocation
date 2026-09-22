"""Executed by tools/blender.py inside a clean Blender 5.2 user profile."""
import addon_utils
import bpy

assert bpy.app.version[:2] == (5, 2), bpy.app.version_string
module_name = "bl_ext.blendlocation_test.blendlocation"
assert module_name in bpy.context.preferences.addons, "Extension was not installed and enabled"
assert hasattr(bpy.types.Scene, "blendlocation")
assert hasattr(bpy.types.WindowManager, "blendlocation_picker")
assert bpy.context.window_manager.blendlocation_picker.imagery == "MAP"
assert not bpy.ops.blendlocation.add_location.poll(), "Picker should require a 3D View"
settings = bpy.context.scene.blendlocation
settings.latitude = 40.7
settings.longitude = -74.0
settings.width = 1.0
settings.height = 1.0
settings.unit = "KM"
settings.provider = "FIXTURE"
assert bpy.ops.blendlocation.import_terrain() == {"FINISHED"}
sites = [c for c in bpy.data.collections if c.get("blendlocation_schema") == 1]
assert len(sites) == 1
site = sites[0]
assert abs(site["origin_latitude_deg"] - 40.7) < 1e-5
assert site["horizontal_crs"] == "EPSG:4326 (WGS84)"
terrain = site.children[0].objects[0]
assert len(terrain.data.vertices) == 16
assert len(terrain.data.polygons) == 9
assert max(v.co.z for v in terrain.data.vertices) == 115
assert terrain.location.length == 0
addon_utils.disable(module_name, default_set=True)
assert not hasattr(bpy.types.Scene, "blendlocation")
assert not hasattr(bpy.types.WindowManager, "blendlocation_picker")
try:
    bpy.ops.blendlocation.import_terrain.get_rna_type()
except (AttributeError, KeyError):
    pass
else:
    raise AssertionError("Terrain operator remained registered")
print("BLENDLOCATION_SMOKE_OK")
