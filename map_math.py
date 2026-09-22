"""Pure geographic-to-screen math for the Add Location viewport picker."""
from dataclasses import dataclass
from math import floor

from .geo import Area, MAX_LAT, lat_to_pixel, lon_to_pixel, pixel_to_lat, pixel_to_lon


@dataclass
class MapView:
    latitude: float
    longitude: float
    zoom: int
    width: int
    height: int

    def screen_to_geo(self, x, y):
        cx, cy = lon_to_pixel(self.longitude, self.zoom), lat_to_pixel(self.latitude, self.zoom)
        return pixel_to_lat(cy + self.height / 2 - y, self.zoom), pixel_to_lon(cx + x - self.width / 2, self.zoom)

    def geo_to_screen(self, latitude, longitude):
        cx, cy = lon_to_pixel(self.longitude, self.zoom), lat_to_pixel(self.latitude, self.zoom)
        return (self.width / 2 + lon_to_pixel(longitude, self.zoom) - cx,
                self.height / 2 + cy - lat_to_pixel(latitude, self.zoom))

    def pan(self, dx, dy):
        self.latitude, self.longitude = self.screen_to_geo(self.width / 2 - dx, self.height / 2 - dy)
        self.latitude = max(-MAX_LAT + .001, min(MAX_LAT - .001, self.latitude))
        self.longitude = max(-179.999, min(179.999, self.longitude))

    def zoom_at(self, step, x, y):
        anchor = self.screen_to_geo(x, y)
        self.zoom = max(2, min(19, self.zoom + step))
        self.latitude, self.longitude = anchor
        center = self.screen_to_geo(self.width - x, self.height - y)
        self.latitude, self.longitude = center

    def tiles(self):
        cx, cy = lon_to_pixel(self.longitude, self.zoom), lat_to_pixel(self.latitude, self.zoom)
        x0 = floor((cx - self.width / 2) / 256)
        x1 = floor((cx + self.width / 2 - .001) / 256)
        y0 = floor((cy - self.height / 2) / 256)
        y1 = floor((cy + self.height / 2 - .001) / 256)
        limit = 2 ** self.zoom
        return [(self.zoom, x, y) for y in range(max(0, y0), min(limit - 1, y1) + 1)
                for x in range(max(0, x0), min(limit - 1, x1) + 1) if 0 <= x < limit]

    def tile_origin(self, x, y):
        cx, cy = lon_to_pixel(self.longitude, self.zoom), lat_to_pixel(self.latitude, self.zoom)
        return self.width / 2 + x * 256 - cx, self.height / 2 + cy - (y + 1) * 256

    def bounds(self):
        nw = self.screen_to_geo(0, self.height)
        se = self.screen_to_geo(self.width, 0)
        return nw[1], se[0], se[1], nw[0]


def area_rect(view, area):
    west, south, east, north = area.bounds
    left, bottom = view.geo_to_screen(south, west)
    right, top = view.geo_to_screen(north, east)
    return left, bottom, right, top


def area_from_drag(view, x0, y0, x1, y1):
    lat0, lon0 = view.screen_to_geo(x0, y0)
    lat1, lon1 = view.screen_to_geo(x1, y1)
    center = Area((lat0 + lat1) / 2, (lon0 + lon1) / 2, 1000, 1000)
    width = abs(center.geo_to_local(center.latitude, lon1)[0] - center.geo_to_local(center.latitude, lon0)[0])
    height = abs(center.geo_to_local(lat1, center.longitude)[1] - center.geo_to_local(lat0, center.longitude)[1])
    result = Area(center.latitude, center.longitude, max(50, width), max(50, height))
    result.validate()
    return result


def moved_area(view, area, dx, dy):
    x, y = view.geo_to_screen(area.latitude, area.longitude)
    lat, lon = view.screen_to_geo(x + dx, y + dy)
    result = Area(lat, lon, area.width_m, area.height_m)
    result.validate()
    return result


def resized_area(view, area, handle, x, y):
    """Move one named corner while keeping its opposite corner fixed."""
    if handle not in {"SW", "SE", "NW", "NE"}:
        raise ValueError("Unknown selection handle")
    left, bottom, right, top = area_rect(view, area)
    fixed_x = right if handle.endswith("W") else left
    fixed_y = top if handle.startswith("S") else bottom
    return area_from_drag(view, fixed_x, fixed_y, x, y)


def choose_zoom(area, width, height):
    for zoom in range(19, 1, -1):
        view = MapView(area.latitude, area.longitude, zoom, width, height)
        left, bottom, right, top = area_rect(view, area)
        if right - left <= width * .65 and top - bottom <= height * .65:
            return zoom
    return 2
