"""Preview imagery providers. No elevation data is sourced here."""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USER_AGENT = "BlendLocation/0.2 (+https://github.com/Coasterpete/BlendLocation)"
OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
NAIP_URL = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer"
MAX_BYTES = 4_000_000


def cache_root():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) if os.name == "nt" else Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "BlendLocation" / "map"


def _write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as temp:
        temp.write(data)
        temporary = Path(temp.name)
    temporary.replace(path)


def _expiry(headers):
    now = datetime.now(timezone.utc)
    directive = headers.get("Cache-Control", "")
    for part in directive.split(","):
        part = part.strip().lower()
        if part.startswith("max-age="):
            try:
                return (now + timedelta(seconds=max(0, int(part[8:])))).timestamp()
            except ValueError:
                pass
    if headers.get("Expires"):
        try:
            return parsedate_to_datetime(headers["Expires"]).timestamp()
        except (ValueError, TypeError):
            pass
    return (now + timedelta(days=7)).timestamp()


class ImageryUnavailable(RuntimeError):
    pass


class PreviewProvider(ABC):
    id = ""
    attribution = ""

    @abstractmethod
    def fetch(self, view):
        """Yield (cache key, path) for only the currently viewed map extent."""


class OpenStreetMapProvider(PreviewProvider):
    id = "MAP"
    attribution = "© OpenStreetMap contributors · openstreetmap.org/copyright"

    def __init__(self, root=None, opener=urlopen):
        self.root = Path(root) if root else cache_root() / "osm"
        self.opener = opener

    def _tile(self, z, x, y):
        path = self.root / str(z) / str(x) / f"{y}.png"
        meta_path = path.with_suffix(".json")
        meta = {}
        if path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf8"))
            except (OSError, ValueError):
                pass
            if meta.get("expires", 0) > datetime.now(timezone.utc).timestamp():
                return path
        headers = {"User-Agent": USER_AGENT}
        if path.is_file():
            if meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = meta["last_modified"]
        try:
            with self.opener(Request(OSM_URL.format(z=z, x=x, y=y), headers=headers), timeout=10) as response:
                data = response.read(MAX_BYTES + 1)
                response_headers = response.headers
            if len(data) > MAX_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError("Invalid or oversized OpenStreetMap tile")
            _write_atomic(path, data)
            _write_atomic(meta_path, json.dumps({"expires": _expiry(response_headers),
                "etag": response_headers.get("ETag"), "last_modified": response_headers.get("Last-Modified")}).encode("utf8"))
            return path
        except HTTPError as exc:
            if exc.code == 304 and path.is_file():
                meta["expires"] = _expiry(exc.headers)
                _write_atomic(meta_path, json.dumps(meta).encode("utf8"))
                return path
            raise RuntimeError(f"OpenStreetMap tile request failed: HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"OpenStreetMap tile request failed: {exc}") from exc

    def fetch(self, view):
        keys = view.tiles()
        if len(keys) > 20:
            raise RuntimeError("Map viewport exceeds the tile request limit")
        for key in keys:
            yield key, self._tile(*key)


class USGSNAIPProvider(PreviewProvider):
    id = "AERIAL"
    attribution = "USGS, USDA, The National Map · NAIP Plus orthoimagery (acquisition dates vary)"

    def __init__(self, root=None, opener=urlopen):
        self.root = Path(root) if root else cache_root() / "naip"
        self.opener = opener

    def _get(self, url, limit=MAX_BYTES):
        try:
            with self.opener(Request(url, headers={"User-Agent": USER_AGENT}), timeout=15) as response:
                data = response.read(limit + 1)
            if len(data) > limit:
                raise RuntimeError("USGS response exceeds preview limit")
            return data
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"USGS imagery request failed: {exc}") from exc

    def fetch(self, view):
        west, south, east, north = view.bounds()
        if not (west >= -180 and east <= 180 and -85 < south < north < 85):
            raise ImageryUnavailable("Aerial preview is unavailable at this map extent; switch to Map")
        from .geo import lat_to_pixel, lon_to_pixel
        from math import pi
        scale = 2 * pi * 6378137 / (256 * 2 ** view.zoom)
        cx = (lon_to_pixel(view.longitude, view.zoom) - 128 * 2 ** view.zoom) * scale
        cy = (128 * 2 ** view.zoom - lat_to_pixel(view.latitude, view.zoom)) * scale
        bbox = f"{cx-view.width*scale/2:.2f},{cy-view.height*scale/2:.2f},{cx+view.width*scale/2:.2f},{cy+view.height*scale/2:.2f}"
        params = urlencode({"bbox": bbox, "bboxSR": 3857, "imageSR": 3857,
            "size": f"{view.width},{view.height}", "format": "png32", "transparent": "true",
            "renderingRule": json.dumps({"rasterFunction": "NaturalColor"}), "f": "image"})
        key = hashlib.sha256(params.encode("utf8")).hexdigest()
        path = self.root / f"{key}.png"
        if path.is_file() and datetime.now(timezone.utc).timestamp() - path.stat().st_mtime <= 7 * 86400:
            yield key, path
            return
        # A catalog query checks actual raster coverage, rather than the broad service extent.
        coverage = urlencode({"where": "Category=1", "geometry": f"{view.longitude:.7f},{view.latitude:.7f}",
            "geometryType": "esriGeometryPoint", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
            "returnCountOnly": "true", "f": "json"})
        try:
            payload = json.loads(self._get(f"{NAIP_URL}/query?{coverage}", 100_000))
            count = payload["count"]
        except (ValueError, TypeError, KeyError) as exc:
            raise RuntimeError("USGS coverage check returned invalid data") from exc
        if not isinstance(count, int):
            raise RuntimeError("USGS coverage check returned invalid data")
        if count < 1:
            raise ImageryUnavailable("No USGS NAIP Plus aerial coverage at the view center; switch to Map")
        data = self._get(f"{NAIP_URL}/exportImage?{params}")
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("USGS aerial export returned an invalid image")
        _write_atomic(path, data)
        yield key, path


PROVIDERS = {"MAP": OpenStreetMapProvider, "AERIAL": USGSNAIPProvider}
