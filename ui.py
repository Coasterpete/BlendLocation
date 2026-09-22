"""3D View sidebar controls."""
import bpy


class BLENDLOCATION_PT_site(bpy.types.Panel):
    bl_label = "BlendLocation"
    bl_idname = "BLENDLOCATION_PT_site"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendLocation"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blendlocation
        layout.prop(settings, "latitude")
        layout.prop(settings, "longitude")
        row = layout.row(align=True)
        row.prop(settings, "width")
        row.prop(settings, "height")
        layout.prop(settings, "unit")
        layout.prop(settings, "provider")
        layout.operator("blendlocation.import_terrain", icon="MESH_GRID")
        layout.label(text="Source elevations in meters")


def register():
    bpy.utils.register_class(BLENDLOCATION_PT_site)


def unregister():
    bpy.utils.unregister_class(BLENDLOCATION_PT_site)
