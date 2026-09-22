"""Run with python -m unittest discover -s tests."""
import importlib
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
import zlib

# Load the pure Python modules without requiring bpy on the developer Python.
PACKAGE = "blendlocation_test_core"
module = types.ModuleType(PACKAGE)
module.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules[PACKAGE] = module
geo = importlib.import_module(f"{PACKAGE}.geo")
terrain = importlib.import_module(f"{PACKAGE}.terrain")
terrarium = importlib.import_module(f"{PACKAGE}.terrarium")
providers = importlib.import_module(f"{PACKAGE}.providers")
map_math = importlib.import_module(f"{PACKAGE}.map_math")
map_imagery = importlib.import_module(f"{PACKAGE}.map_imagery")


class GeographicTests(unittest.TestCase):
    def test_local_round_trip_and_meter_scale(self):
        area = geo.Area(40.7, -74.0, 1000, 800)
        area.validate()
        for x, y in [(-500, -400), (0, 0), (500, 400)]:
            self.assertEqual(tuple(round(v, 5) for v in area.geo_to_local(*area.local_to_geo(x, y))), (x, y))
        self.assertEqual(area.geo_to_local(40.7, -74.0), (0.0, 0.0))

    def test_mercator_pixel_round_trip(self):
        for lat, lon in [(0, 0), (40.7, -74), (-45, 170)]:
            self.assertAlmostEqual(geo.pixel_to_lat(geo.lat_to_pixel(lat, 12), 12), lat, places=8)
            self.assertAlmostEqual(geo.pixel_to_lon(geo.lon_to_pixel(lon, 12), 12), lon, places=8)

    def test_invalid_area(self):
        for area in [geo.Area(90, 0, 1000, 1000), geo.Area(0, 180, 1000, 1000),
                     geo.Area(0, 0, 10, 1000)]:
            with self.assertRaises(ValueError):
                area.validate()


class TerrainTests(unittest.TestCase):
    def test_png_filters_and_fractional_elevation(self):
        first = bytes([128, 0, 0, 128, 0, 0])
        second = bytes([127, 254, 192, 128, 12, 128])  # -1.25 m, 12.5 m

        def chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

        for filter_type in range(5):
            encoded = bytearray()
            for i, value in enumerate(second):
                a = second[i - 3] if i >= 3 else 0
                b = first[i]
                c = first[i - 3] if i >= 3 else 0
                if filter_type == 0:
                    predictor = 0
                elif filter_type == 1:
                    predictor = a
                elif filter_type == 2:
                    predictor = b
                elif filter_type == 3:
                    predictor = (a + b) // 2
                else:
                    p = a + b - c
                    candidates = (a, b, c)
                    predictor = candidates[min(range(3), key=lambda j: abs(p - candidates[j]))]
                encoded.append((value - predictor) & 255)
            raw = b"\0" + first + bytes([filter_type]) + encoded
            png = terrarium.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            png += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
            self.assertEqual(terrarium.decode_terrarium(png)[1], [-1.25, 12.5])

    def test_fixture_decode_and_mesh(self):
        data = (Path(__file__).resolve().parents[1] / "fixtures" / "hill.png").read_bytes()
        values = terrarium.decode_terrarium(data)
        self.assertEqual(values[0], [100, 101, 102, 103])
        self.assertEqual(values[2][2], 115)
        area = geo.Area(40, -74, 1000, 1000)
        grid = providers.FixtureProvider().fetch(area)
        vertices, faces = terrain.mesh_data(grid, area)
        self.assertEqual(len(vertices), 16)
        self.assertEqual(len(faces), 9)
        self.assertEqual(vertices[10][2], 115)
        self.assertAlmostEqual(vertices[0][0], -500, places=5)
        self.assertAlmostEqual(vertices[0][1], 500, places=5)

    def test_corrupt_png_rejected(self):
        data = bytearray((Path(__file__).resolve().parents[1] / "fixtures" / "hill.png").read_bytes())
        data[-8] ^= 1
        with self.assertRaises(ValueError):
            terrarium.decode_terrarium(bytes(data))

    def test_mapzen_crop_limits(self):
        provider = providers.MapzenTerrariumProvider()
        for width in (500, 1000, 100000):
            zoom, (x0, x1, y0, y1) = provider._choose_zoom(geo.Area(40, -74, width, width))
            self.assertLessEqual((x1 - x0 + 1) * (y1 - y0 + 1), providers.MAX_PIXELS)
            self.assertLessEqual((x1 // 256 - x0 // 256 + 1) * (y1 // 256 - y0 // 256 + 1), providers.MAX_TILES)


class PickerTests(unittest.TestCase):
    def test_drag_move_resize_and_terrain_alignment(self):
        original = geo.Area(40.7, -74, 1000, 800)
        view = map_math.MapView(original.latitude, original.longitude, 14, 768, 512)
        rect = map_math.area_rect(view, original)
        dragged = map_math.area_from_drag(view, rect[0], rect[1], rect[2], rect[3])
        self.assertAlmostEqual(dragged.latitude, original.latitude, places=5)
        self.assertAlmostEqual(dragged.longitude, original.longitude, places=5)
        self.assertAlmostEqual(dragged.width_m, original.width_m, delta=.2)
        self.assertAlmostEqual(dragged.height_m, original.height_m, delta=.2)
        moved = map_math.moved_area(view, dragged, 30, -20)
        self.assertAlmostEqual(moved.width_m, dragged.width_m)
        resized = map_math.area_from_drag(view, rect[0], rect[1], rect[2] + 40, rect[3] + 25)
        self.assertGreater(resized.width_m, original.width_m)
        self.assertGreater(resized.height_m, original.height_m)
        grid = providers.FixtureProvider().fetch(resized)
        vertices, _ = terrain.mesh_data(grid, resized)
        self.assertAlmostEqual(vertices[0][0], -resized.width_m / 2, places=5)
        self.assertAlmostEqual(vertices[0][1], resized.height_m / 2, places=5)
        self.assertAlmostEqual(vertices[-1][0], resized.width_m / 2, places=5)
        self.assertAlmostEqual(vertices[-1][1], -resized.height_m / 2, places=5)

    def test_view_zoom_anchor_and_visible_tiles(self):
        view = map_math.MapView(40.7, -74, 11, 768, 512)
        anchor = view.screen_to_geo(220, 180)
        view.zoom_at(1, 220, 180)
        actual = view.screen_to_geo(220, 180)
        self.assertAlmostEqual(actual[0], anchor[0], places=8)
        self.assertAlmostEqual(actual[1], anchor[1], places=8)
        self.assertLessEqual(len(view.tiles()), 20)

    def test_corner_resize_keeps_opposite_corner(self):
        area = geo.Area(40.7, -74, 1000, 800)
        view = map_math.MapView(area.latitude, area.longitude, 15, 768, 512)
        left, bottom, right, top = map_math.area_rect(view, area)
        for handle, start, delta, fixed in (
            ("NW", (left, top), (-30, 20), (right, bottom)),
            ("NE", (right, top), (30, 20), (left, bottom)),
            ("SW", (left, bottom), (-30, -20), (right, top)),
            ("SE", (right, bottom), (30, -20), (left, top)),
        ):
            resized = map_math.resized_area(view, area, handle, start[0] + delta[0], start[1] + delta[1])
            self.assertGreater(resized.width_m, area.width_m)
            self.assertGreater(resized.height_m, area.height_m)
            bounds = map_math.area_rect(view, resized)
            actual = (bounds[2] if handle.endswith("W") else bounds[0],
                      bounds[3] if handle.startswith("S") else bounds[1])
            self.assertAlmostEqual(actual[0], fixed[0], delta=.1)
            self.assertAlmostEqual(actual[1], fixed[1], delta=.1)

    def test_offline_map_tile_cache_and_failure(self):
        data = (Path(__file__).parent / "fixtures" / "map_tile.png").read_bytes()

        class Response:
            headers = {"Cache-Control": "max-age=604800", "ETag": '"fixture"'}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return data

        calls = []
        def opener(request, timeout):
            calls.append(request)
            return Response()

        with tempfile.TemporaryDirectory() as root:
            source = map_imagery.OpenStreetMapProvider(root, opener)
            path = source._tile(11, 600, 700)
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(source._tile(11, 600, 700), path)
            self.assertEqual(len(calls), 1)
            self.assertIn("BlendLocation", calls[0].get_header("User-agent"))
            self.assertTrue((path.with_suffix(".json")).is_file())
            failed = map_imagery.OpenStreetMapProvider(Path(root) / "fail", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
            with self.assertRaisesRegex(RuntimeError, "offline"):
                failed._tile(11, 600, 700)

    def test_aerial_unavailable_and_export(self):
        view = map_math.MapView(40.7, -74, 12, 512, 384)
        png = (Path(__file__).parent / "fixtures" / "map_tile.png").read_bytes()

        class Response:
            headers = {}
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return self.data

        urls = []
        def unavailable(request, timeout):
            urls.append(request.full_url)
            return Response(b'{"count":0}')

        with tempfile.TemporaryDirectory() as root:
            provider = map_imagery.USGSNAIPProvider(root, unavailable)
            with self.assertRaises(map_imagery.ImageryUnavailable):
                list(provider.fetch(view))
            self.assertEqual(len(urls), 1)
            def available(request, timeout):
                urls.append(request.full_url)
                return Response(b'{"count":1}' if "/query?" in request.full_url else png)
            provider = map_imagery.USGSNAIPProvider(root, available)
            result = list(provider.fetch(view))
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0][1].read_bytes(), png)
            self.assertIn("renderingRule=", urls[-1])
            request_count = len(urls)
            self.assertEqual(list(provider.fetch(view)), result)
            self.assertEqual(len(urls), request_count, "A valid cached aerial view should make no request")


if __name__ == "__main__":
    unittest.main()
