"""3D View sidebar controls."""
import bpy
from . import picker


class BLENDLOCATION_PT_site(bpy.types.Panel):
    bl_label = "BlendLocation"
    bl_idname = "BLENDLOCATION_PT_site"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendLocation"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blendlocation
        layout.operator("blendlocation.add_location", icon="WORLD")
        if picker.ACTIVE_PICKER is not None:
            state = context.window_manager.blendlocation_picker
            box = layout.box()
            box.prop(state, "imagery", expand=True)
            box.label(text="Selection · WGS84")
            box.prop(state, "latitude")
            box.prop(state, "longitude")
            box.prop(state, "width_m")
            box.prop(state, "height_m")
            box.operator("blendlocation.picker_action", text="Center Map Here", icon="PIVOT_CURSOR").action = "CENTER"
            box.label(text=state.status[:68])
            row = box.row(align=True)
            row.operator("blendlocation.picker_action", text="Confirm", icon="CHECKMARK").action = "CONFIRM"
            row.operator("blendlocation.picker_action", text="Import", icon="MESH_GRID").action = "IMPORT"
            box.operator("blendlocation.picker_action", text="Cancel", icon="CANCEL").action = "CANCEL"
            box.label(text="Preview imagery only · DEM below")
            layout.separator()
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
