"""Elevation providers. Add future providers by implementing DEMProvider.fetch."""
from abc import ABC, abstractmethod
from math import ceil, cos, floor, radians
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .geo import lat_to_pixel, lon_to_pixel, pixel_to_lat, pixel_to_lon
from .terrain import ElevationGrid
from .terrarium import decode_terrarium

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
MAX_PIXELS = 512 * 512
MAX_TILES = 16


def default_cache_dir():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "BlendLocation" / "terrarium"


class DEMProvider(ABC):
    id = ""

    @abstractmethod
    def fetch(self, area, progress=lambda done, total: None):
        """Return original elevation samples in geographic grid order."""


class MapzenTerrariumProvider(DEMProvider):
    id = "mapzen_terrarium"

    def __init__(self, cache_dir=None):
        self.cache_dir = Path(cache_dir) if cache_dir else default_cache_dir()

    @staticmethod
    def _extent(area, zoom):
        west, south, east, north = area.bounds
        x0 = ceil(lon_to_pixel(west, zoom) - 0.5)
        x1 = floor(lon_to_pixel(east, zoom) - 0.5)
        y0 = ceil(lat_to_pixel(north, zoom) - 0.5)
        y1 = floor(lat_to_pixel(south, zoom) - 0.5)
        return x0, x1, y0, y1

    def _choose_zoom(self, area):
        # Choose source pixels around 25 m apart, then coarsen for large sites.
        for zoom in range(0, 15):
            meters_per_pixel = 2 * 3.141592653589793 * 6378137 * cos(radians(area.latitude)) / (256 * 2 ** zoom)
            if meters_per_pixel <= 25:
                break
        for candidate in range(zoom, -1, -1):
            x0, x1, y0, y1 = self._extent(area, candidate)
            cols, rows = x1 - x0 + 1, y1 - y0 + 1
            tiles = (x1 // 256 - x0 // 256 + 1) * (y1 // 256 - y0 // 256 + 1)
            if cols >= 2 and rows >= 2 and cols * rows <= MAX_PIXELS and tiles <= MAX_TILES:
                return candidate, (x0, x1, y0, y1)
        raise ValueError("Area is too small for two available source pixels per axis")

    def _tile(self, zoom, x, y):
        path = self.cache_dir / str(zoom) / str(x) / f"{y}.png"
        if path.exists():
            try:
                samples = decode_terrarium(path.read_bytes())
                if len(samples) != 256 or any(len(row) != 256 for row in samples):
                    raise ValueError("Invalid cached tile dimensions")
                return samples
            except (ValueError, OSError):
                # A damaged cache entry is replaced by a fresh download.
                path.unlink(missing_ok=True)
        url = TILE_URL.format(z=zoom, x=x, y=y)
        try:
            with urlopen(Request(url, headers={"User-Agent": "BlendLocation/0.1 (https://github.com/Coasterpete/BlendLocation)"}), timeout=20) as response:
                data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError("Terrain tile exceeds 2 MB limit")
            samples = decode_terrarium(data)
            if len(samples) != 256 or any(len(row) != 256 for row in samples):
                raise ValueError("Expected a 256 × 256 Terrarium tile")
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as temp:
                temp.write(data)
                temporary = Path(temp.name)
            temporary.replace(path)
            return samples
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Could not download terrain tile {zoom}/{x}/{y}: {exc}") from exc

    def fetch(self, area, progress=lambda done, total: None):
        area.validate()
        zoom, (x0, x1, y0, y1) = self._choose_zoom(area)
        tiles = [(x, y) for y in range(y0 // 256, y1 // 256 + 1)
                 for x in range(x0 // 256, x1 // 256 + 1)]
        decoded = {}
        progress(0, len(tiles))
        for index, (x, y) in enumerate(tiles, 1):
            decoded[x, y] = self._tile(zoom, x, y)
            progress(index, len(tiles))
        elevations = [[decoded[x // 256, y // 256][y % 256][x % 256]
                       for x in range(x0, x1 + 1)] for y in range(y0, y1 + 1)]
        return ElevationGrid(
            [pixel_to_lon(x + 0.5, zoom) for x in range(x0, x1 + 1)],
            [pixel_to_lat(y + 0.5, zoom) for y in range(y0, y1 + 1)],
            elevations, self.id, zoom)


class FixtureProvider(DEMProvider):
    id = "offline_fixture"

    def fetch(self, area, progress=lambda done, total: None):
        area.validate()
        data = (Path(__file__).parent / "fixtures" / "hill.png").read_bytes()
        elevations = decode_terrarium(data)
        rows, cols = len(elevations), len(elevations[0])
        west, south, east, north = area.bounds
        progress(1, 1)
        return ElevationGrid(
            [west + (east - west) * i / (cols - 1) for i in range(cols)],
            [north - (north - south) * j / (rows - 1) for j in range(rows)],
            elevations, self.id)


PROVIDERS = {"MAPZEN": MapzenTerrariumProvider, "FIXTURE": FixtureProvider}
