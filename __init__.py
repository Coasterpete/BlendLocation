"""BlendLocation Blender 5.2 extension."""
from . import operators, picker, ui


def register():
    operators.register()
    picker.register()
    ui.register()


def unregister():
    ui.unregister()
    picker.unregister()
    operators.unregister()
