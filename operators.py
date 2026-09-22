"""Blender operator: acquire DEM data and build a local terrain site."""
import bpy
from bpy.props import EnumProperty, FloatProperty, PointerProperty
from datetime import datetime, timezone

from .geo import Area
from .providers import PROVIDERS
from .terrain import mesh_data


class BlendLocationSettings(bpy.types.PropertyGroup):
    latitude: FloatProperty(name="Latitude", default=40.7128, min=-85.0511, max=85.0511,
                            precision=6, description="Site center latitude in WGS84 degrees")
    longitude: FloatProperty(name="Longitude", default=-74.0060, min=-180, max=180,
                             precision=6, description="Site center longitude in WGS84 degrees")
    width: FloatProperty(name="Width", default=1.0, min=0.05, max=100000,
                         description="East–west site dimension")
    height: FloatProperty(name="Height", default=1.0, min=0.05, max=100000,
                          description="North–south site dimension")
    unit: EnumProperty(name="Units", items=[("KM", "Kilometers", ""), ("M", "Meters", "")], default="KM")
    provider: EnumProperty(name="Elevation", items=[
        ("MAPZEN", "Mapzen Terrain Tiles", "Public Terrarium tiles from AWS"),
        ("FIXTURE", "Offline fixture", "Small synthetic terrain for tests")], default="MAPZEN")


class BLENDLOCATION_OT_import_terrain(bpy.types.Operator):
    bl_idname = "blendlocation.import_terrain"
    bl_label = "Import Terrain"
    bl_description = "Download source DEM pixels and create a meter-based terrain mesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.blendlocation
        scale = 1000 if settings.unit == "KM" else 1
        area = Area(settings.latitude, settings.longitude, settings.width * scale, settings.height * scale)
        try:
            area.validate()
            if settings.provider == "MAPZEN" and not bpy.app.online_access:
                raise ValueError("Blender online access is disabled; enable it or use the offline fixture")
            provider = PROVIDERS[settings.provider]()
            wm = context.window_manager
            started = False

            def progress(done, total):
                nonlocal started
                if not started:
                    wm.progress_begin(0, max(total, 1))
                    started = True
                wm.progress_update(done)
                context.workspace.status_text_set(f"BlendLocation: terrain tiles {done}/{total}")

            try:
                grid = provider.fetch(area, progress)
                vertices, faces = mesh_data(grid, area)
            finally:
                if started:
                    wm.progress_end()
                context.workspace.status_text_set(None)
        except (ValueError, RuntimeError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        site = bpy.data.collections.new(f"BlendLocation Site ({area.latitude:.5f}, {area.longitude:.5f})")
        context.scene.collection.children.link(site)
        terrain_collection = bpy.data.collections.new("Terrain")
        site.children.link(terrain_collection)
        mesh = bpy.data.meshes.new("Elevation terrain")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        obj = bpy.data.objects.new("DEM Terrain", mesh)
        terrain_collection.objects.link(obj)
        for polygon in mesh.polygons:
            polygon.use_smooth = True

        site["blendlocation_schema"] = 1
        site["origin_latitude_deg"] = area.latitude
        site["origin_longitude_deg"] = area.longitude
        site["horizontal_crs"] = "EPSG:4326 (WGS84)"
        site["local_coordinates"] = "WGS84 tangent-plane approximation; X east, Y north, meters"
        site["origin_elevation_m"] = 0.0
        site["vertical_datum"] = "Source DEM datum varies; elevations kept in source meters"
        site["width_m"] = area.width_m
        site["height_m"] = area.height_m
        site["dem_provider"] = grid.provider
        site["dem_zoom"] = grid.zoom if grid.zoom is not None else -1
        site["dem_columns"] = len(grid.longitudes)
        site["dem_rows"] = len(grid.latitudes)
        site["dem_attribution"] = "https://github.com/tilezen/joerd/blob/master/docs/attribution.md" if settings.provider == "MAPZEN" else "Synthetic offline fixture"
        if settings.provider == "MAPZEN":
            site["dem_dataset"] = "https://registry.opendata.aws/terrain-tiles/"
            site["dem_accessed_utc"] = datetime.now(timezone.utc).isoformat()
        obj["blendlocation_site"] = site.name
        obj["elevations_m"] = "Unshifted source DEM values; no interpolation"
        if context.view_layer.objects.active:
            context.view_layer.objects.active.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        self.report({"INFO"}, f"Imported {len(vertices)} source elevation samples")
        return {"FINISHED"}


CLASSES = (BlendLocationSettings, BLENDLOCATION_OT_import_terrain)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blendlocation = PointerProperty(type=BlendLocationSettings)


def unregister():
    del bpy.types.Scene.blendlocation
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
