"""Run with python -m unittest discover -s tests."""
import importlib
from pathlib import Path
import struct
import sys
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


if __name__ == "__main__":
    unittest.main()
