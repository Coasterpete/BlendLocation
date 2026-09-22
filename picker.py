"""Native 3D View map overlay and temporary sidebar selection controls."""
import queue
import threading
import time

import blf
import bpy
import gpu
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from gpu_extras.batch import batch_for_shader

from .geo import Area
from .map_imagery import ImageryUnavailable, PROVIDERS
from .map_math import MapView, area_from_drag, area_rect, choose_zoom, moved_area, resized_area


ACTIVE_PICKER = None


class BlendLocationPickerState(bpy.types.PropertyGroup):
    latitude: FloatProperty(name="Center latitude", min=-85.0511, max=85.0511, precision=6)
    longitude: FloatProperty(name="Center longitude", min=-180, max=180, precision=6)
    width_m: FloatProperty(name="Width (m)", min=50, max=100000, precision=1)
    height_m: FloatProperty(name="Height (m)", min=50, max=100000, precision=1)
    imagery: EnumProperty(name="Preview", items=[("MAP", "Map · OSM", "OpenStreetMap street map"),
                                                ("AERIAL", "Aerial · USGS", "USGS NAIP Plus natural color")], default="MAP")
    status: StringProperty(name="Map status", default="Loading map…")
    command: StringProperty(options={"HIDDEN"})


def _rect(view, region):
    width = min(768, max(256, region.width - 48))
    height = min(512, max(192, region.height - 140))
    return (region.width - width) / 2, (region.height - height) / 2, width, height


def _box(x0, y0, x1, y1, color, filled=False):
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    vertices = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    batch = batch_for_shader(shader, "TRI_FAN" if filled else "LINE_LOOP", {"pos": vertices})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _text(x, y, value, size=14, color=(1, 1, 1, 1)):
    blf.position(0, x, y, 0)
    blf.size(0, size)
    blf.color(0, *color)
    blf.draw(0, value)


class BLENDLOCATION_OT_add_location(bpy.types.Operator):
    bl_idname = "blendlocation.add_location"
    bl_label = "Add Location"
    bl_description = "Choose a geographic rectangle on a native viewport map"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        global ACTIVE_PICKER
        if ACTIVE_PICKER is not None:
            self.report({"WARNING"}, "Add Location is already open")
            return {"CANCELLED"}
        if not bpy.app.online_access:
            self.report({"ERROR"}, "Blender online access is disabled; enable it for map imagery")
            return {"CANCELLED"}
        region = next((r for r in context.area.regions if r.type == "WINDOW"), None)
        if region is None:
            return {"CANCELLED"}
        settings = context.scene.blendlocation
        scale = 1000 if settings.unit == "KM" else 1
        area = Area(settings.latitude, settings.longitude, settings.width * scale, settings.height * scale)
        try:
            area.validate()
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        state = context.window_manager.blendlocation_picker
        state.latitude, state.longitude = area.latitude, area.longitude
        state.width_m, state.height_m = area.width_m, area.height_m
        state.imagery, state.status, state.command = "MAP", "Loading map…", ""
        _, _, width, height = _rect(None, region)
        self.view = MapView(area.latitude, area.longitude, choose_zoom(area, int(width), int(height)), int(width), int(height))
        self.region = region
        self.area = context.area
        self.scene = context.scene
        self.wm = context.window_manager
        self.results = queue.Queue()
        self.worker = None
        self.stop_worker = None
        self.generation = 0
        self.last_view = None
        self.last_change = 0.0
        self.textures = {}
        self.images = []
        self.drag = None
        self.drag_start = None
        self.drag_area = None
        self.drag_view = None
        self._closed = False
        self._handler = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), "WINDOW", "POST_PIXEL")
        self._timer = self.wm.event_timer_add(.12, window=context.window)
        ACTIVE_PICKER = self
        context.window_manager.modal_handler_add(self)
        self.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _area(self):
        state = self.wm.blendlocation_picker
        return Area(state.latitude, state.longitude, state.width_m, state.height_m)

    def _set_area(self, area):
        state = self.wm.blendlocation_picker
        state.latitude, state.longitude = area.latitude, area.longitude
        state.width_m, state.height_m = area.width_m, area.height_m

    def _view_key(self):
        state = self.wm.blendlocation_picker
        return (state.imagery, round(self.view.latitude, 7), round(self.view.longitude, 7),
                self.view.zoom, self.view.width, self.view.height)

    def _fetch(self, generation, view, provider_id, stop):
        provider = PROVIDERS[provider_id]()
        try:
            for key, path in provider.fetch(view):
                if stop.is_set():
                    return
                self.results.put((generation, "image", (key, str(path))))
            self.results.put((generation, "done", None))
        except (RuntimeError, OSError, ValueError) as exc:
            self.results.put((generation, "error", str(exc)))

    def _tick(self):
        state = self.wm.blendlocation_picker
        if state.command:
            command, state.command = state.command, ""
            if command == "CENTER":
                self.view.latitude, self.view.longitude = state.latitude, state.longitude
            elif command in {"CONFIRM", "IMPORT", "CANCEL"}:
                return command
        _, _, width, height = _rect(None, self.region)
        self.view.width, self.view.height = int(width), int(height)
        key = self._view_key()
        if key != self.last_view:
            self.last_view = key
            self.last_change = time.monotonic()
            if self.stop_worker:
                self.stop_worker.set()
            state.status = "Loading preview…"
            self.textures.clear()
            for image in self.images:
                if image.name in bpy.data.images:
                    bpy.data.images.remove(image)
            self.images.clear()
        if time.monotonic() - self.last_change > .25 and (self.worker is None or not self.worker.is_alive()):
            if getattr(self, "generation_key", None) != key:
                self.generation += 1
                self.generation_key = key
                self.stop_worker = threading.Event()
                view = MapView(self.view.latitude, self.view.longitude, self.view.zoom, self.view.width, self.view.height)
                self.worker = threading.Thread(target=self._fetch, args=(self.generation, view, state.imagery, self.stop_worker), daemon=True)
                self.worker.start()
        while True:
            try:
                generation, kind, payload = self.results.get_nowait()
            except queue.Empty:
                break
            if generation != self.generation or self.generation_key != key:
                continue
            if kind == "image":
                try:
                    image = bpy.data.images.load(payload[1], check_existing=False)
                    self.images.append(image)
                    self.textures[payload[0]] = gpu.texture.from_image(image)
                    state.status = f"Loading preview… {len(self.textures)} image(s)"
                except (RuntimeError, OSError, ValueError) as exc:
                    state.status = f"Preview image failed: {exc}"
            elif kind == "done":
                state.status = "Map ready" if state.imagery == "MAP" else "Aerial preview ready · dates vary"
            elif kind == "error":
                state.status = payload
        self.area.tag_redraw()
        return None

    def _finish(self, context, command):
        global ACTIVE_PICKER
        if self._closed:
            return {"CANCELLED"}
        state = self.wm.blendlocation_picker
        if command != "CANCEL":
            try:
                selected = self._area()
                selected.validate()
            except ValueError as exc:
                state.status = str(exc)
                self.area.tag_redraw()
                return {"RUNNING_MODAL"}
            settings = self.scene.blendlocation
            settings.latitude, settings.longitude = selected.latitude, selected.longitude
            scale = 1000 if settings.unit == "KM" else 1
            settings.width, settings.height = selected.width_m / scale, selected.height_m / scale
        if self.stop_worker:
            self.stop_worker.set()
        self._closed = True
        self.wm.event_timer_remove(self._timer)
        bpy.types.SpaceView3D.draw_handler_remove(self._handler, "WINDOW")
        self.textures.clear()
        for image in self.images:
            if image.name in bpy.data.images:
                bpy.data.images.remove(image)
        self.images.clear()
        ACTIVE_PICKER = None
        self.area.tag_redraw()
        if command == "IMPORT":
            bpy.ops.blendlocation.import_terrain("INVOKE_DEFAULT")
        return {"CANCELLED"} if command == "CANCEL" else {"FINISHED"}

    def modal(self, context, event):
        if self._closed:
            return {"CANCELLED"}
        if ACTIVE_PICKER is not self or not hasattr(self.wm, "blendlocation_picker"):
            return self._finish(context, "CANCEL")
        if event.type == "TIMER":
            command = self._tick()
            return self._finish(context, command) if command else {"PASS_THROUGH"}
        if event.type == "ESC" and event.value == "PRESS":
            return self._finish(context, "CANCEL")
        ox, oy, width, height = _rect(None, self.region)
        x, y = event.mouse_x - self.region.x - ox, event.mouse_y - self.region.y - oy
        inside = 0 <= x <= width and 0 <= y <= height
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and inside:
            self.view.zoom_at(1 if event.type == "WHEELUPMOUSE" else -1, x, y)
            self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type in {"MIDDLEMOUSE", "RIGHTMOUSE", "LEFTMOUSE"} and event.value == "PRESS" and inside:
            rect = area_rect(self.view, self._area())
            near = lambda a, b: abs(x - a) <= 12 and abs(y - b) <= 12
            if event.type != "LEFTMOUSE":
                self.drag = "PAN"
            elif not event.shift and near(rect[0], rect[1]):
                self.drag = "RESIZE_SW"
            elif not event.shift and near(rect[2], rect[1]):
                self.drag = "RESIZE_SE"
            elif not event.shift and near(rect[0], rect[3]):
                self.drag = "RESIZE_NW"
            elif not event.shift and near(rect[2], rect[3]):
                self.drag = "RESIZE_NE"
            elif not event.shift and rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
                self.drag = "MOVE"
            else:
                self.drag = "DRAW"
            self.drag_start = (x, y)
            self.drag_area = self._area()
            self.drag_view = (self.view.latitude, self.view.longitude)
            return {"RUNNING_MODAL"}
        if self.drag and event.type == "MOUSEMOVE":
            dx, dy = x - self.drag_start[0], y - self.drag_start[1]
            try:
                if self.drag == "PAN":
                    self.view.latitude, self.view.longitude = self.drag_view
                    self.view.pan(dx, dy)
                elif self.drag == "MOVE":
                    self._set_area(moved_area(self.view, self.drag_area, dx, dy))
                else:
                    x = max(0, min(width, x))
                    y = max(0, min(height, y))
                    if self.drag == "DRAW":
                        self._set_area(area_from_drag(self.view, *self.drag_start, x, y))
                    else:
                        self._set_area(resized_area(self.view, self.drag_area, self.drag.rsplit("_", 1)[1], x, y))
            except ValueError:
                pass
            self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if self.drag and event.type in {"LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE"} and event.value == "RELEASE":
            self.drag = None
            return {"RUNNING_MODAL"}
        if event.type in {"LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE"} and event.value == "PRESS":
            ui_regions = [r for r in self.area.regions if r.type == "UI"]
            over_ui = any(r.x <= event.mouse_x < r.x + r.width and r.y <= event.mouse_y < r.y + r.height for r in ui_regions)
            over_window = (self.region.x <= event.mouse_x < self.region.x + self.region.width and
                           self.region.y <= event.mouse_y < self.region.y + self.region.height)
            if over_window and not over_ui:
                return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def _draw(self):
        if ACTIVE_PICKER is not self:
            return
        state = self.wm.blendlocation_picker
        ox, oy, width, height = _rect(None, self.region)
        gpu.state.blend_set("ALPHA")
        _box(ox - 8, oy - 52, ox + width + 8, oy + height + 40, (.045, .055, .07, .94), True)
        _box(ox, oy, ox + width, oy + height, (.12, .16, .18, 1), True)
        gpu.state.scissor_test_set(True)
        gpu.state.scissor_set(int(ox), int(oy), int(width), int(height))
        shader = gpu.shader.from_builtin("IMAGE")
        if state.imagery == "MAP":
            for (z, tx, ty), texture in self.textures.items():
                if z != self.view.zoom:
                    continue
                px, py = self.view.tile_origin(tx, ty)
                x0, y0 = ox + px, oy + py
                batch = batch_for_shader(shader, "TRI_FAN", {"pos": [(x0, y0), (x0 + 256, y0), (x0 + 256, y0 + 256), (x0, y0 + 256)],
                    "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]})
                shader.bind()
                shader.uniform_sampler("image", texture)
                batch.draw(shader)
        elif self.textures:
            texture = next(iter(self.textures.values()))
            batch = batch_for_shader(shader, "TRI_FAN", {"pos": [(ox, oy), (ox + width, oy), (ox + width, oy + height), (ox, oy + height)],
                "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]})
            shader.bind()
            shader.uniform_sampler("image", texture)
            batch.draw(shader)
        gpu.state.scissor_test_set(False)
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        original_rect = area_rect(self.view, self._area())
        left, bottom, right, top = original_rect
        left, right = max(0, left), min(width, right)
        bottom, top = max(0, bottom), min(height, top)
        if right > left and top > bottom:
            _box(ox + left, oy + bottom, ox + right, oy + top, (.99, .66, .05, .22), True)
            gpu.state.line_width_set(5)
            _box(ox + left, oy + bottom, ox + right, oy + top, (.05, .06, .07, 1))
            gpu.state.line_width_set(3)
            _box(ox + left, oy + bottom, ox + right, oy + top, (1, .72, .08, 1))
            gpu.state.line_width_set(1)
            for x in (original_rect[0], original_rect[2]):
                for y in (original_rect[1], original_rect[3]):
                    if 0 <= x <= width and 0 <= y <= height:
                        _box(ox + x - 5, oy + y - 5, ox + x + 5, oy + y + 5, (1, .8, .14, 1), True)
        _box(ox, oy, ox + width, oy + height, (.7, .76, .8, 1))
        _text(ox + 8, oy + height + 15, "Add Location  |  drag to draw · drag rectangle to move · corners to resize · middle drag to pan · wheel to zoom", 13)
        area = self._area()
        _text(ox + 8, oy - 19, f"{area.latitude:.6f}°, {area.longitude:.6f}°   |   {area.width_m:,.0f} × {area.height_m:,.0f} m   |   zoom {self.view.zoom}", 13)
        _text(ox + 8, oy - 39, PROVIDERS[state.imagery].attribution, 12)
        if state.status != "Map ready":
            _box(ox + 8, oy + 8, ox + min(width - 8, 550), oy + 35, (.03, .04, .05, .78), True)
            _text(ox + 16, oy + 16, state.status[:90], 13)
        gpu.state.blend_set("NONE")


class BLENDLOCATION_OT_picker_action(bpy.types.Operator):
    bl_idname = "blendlocation.picker_action"
    bl_label = "Picker action"
    action: EnumProperty(items=[("CENTER", "Center map on coordinates", ""),
                                ("CONFIRM", "Confirm selection", ""),
                                ("IMPORT", "Confirm and import terrain", ""),
                                ("CANCEL", "Cancel", "")])

    def execute(self, context):
        if ACTIVE_PICKER is None:
            return {"CANCELLED"}
        context.window_manager.blendlocation_picker.command = self.action
        return {"FINISHED"}


CLASSES = (BlendLocationPickerState, BLENDLOCATION_OT_add_location, BLENDLOCATION_OT_picker_action)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.blendlocation_picker = PointerProperty(type=BlendLocationPickerState)


def unregister():
    global ACTIVE_PICKER
    if ACTIVE_PICKER is not None:
        ACTIVE_PICKER._finish(bpy.context, "CANCEL")
    del bpy.types.WindowManager.blendlocation_picker
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
