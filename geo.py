"""WGS84 local east/north coordinates and Web Mercator tile math."""
from dataclasses import dataclass
from math import atan, cos, degrees, log, pi, radians, sin, sinh, sqrt, tan

R = 6378137.0
E2 = 6.69437999014e-3
MAX_LAT = 85.05112878


@dataclass(frozen=True)
class Area:
    latitude: float
    longitude: float
    width_m: float
    height_m: float

    def validate(self):
        if not (-MAX_LAT < self.latitude < MAX_LAT):
            raise ValueError("Latitude must be within Web Mercator coverage (±85.0511°)")
        if not (-180 <= self.longitude <= 180):
            raise ValueError("Longitude must be between -180° and 180°")
        if not (50 <= self.width_m <= 100000 and 50 <= self.height_m <= 100000):
            raise ValueError("Width and height must each be 50–100,000 m")
        west, south = self.local_to_geo(-self.width_m / 2, -self.height_m / 2)
        east, north = self.local_to_geo(self.width_m / 2, self.height_m / 2)
        if west < -180 or east > 180 or south <= -MAX_LAT or north >= MAX_LAT:
            raise ValueError("Area crosses the antimeridian or Web Mercator limit")

    def _radii(self):
        lat = radians(self.latitude)
        w = sqrt(1 - E2 * sin(lat) ** 2)
        return R * (1 - E2) / w ** 3, R / w

    def geo_to_local(self, latitude, longitude):
        meridian, prime_vertical = self._radii()
        x = radians(longitude - self.longitude) * prime_vertical * cos(radians(self.latitude))
        y = radians(latitude - self.latitude) * meridian
        return x, y

    def local_to_geo(self, x, y):
        meridian, prime_vertical = self._radii()
        return (self.latitude + degrees(y / meridian),
                self.longitude + degrees(x / (prime_vertical * cos(radians(self.latitude)))))

    @property
    def bounds(self):
        south, west = self.local_to_geo(-self.width_m / 2, -self.height_m / 2)
        north, east = self.local_to_geo(self.width_m / 2, self.height_m / 2)
        return west, south, east, north


def lon_to_pixel(longitude, zoom):
    return (longitude + 180) / 360 * (2 ** zoom) * 256


def lat_to_pixel(latitude, zoom):
    a = radians(latitude)
    return (1 - log(tan(a) + 1 / cos(a)) / pi) / 2 * (2 ** zoom) * 256


def pixel_to_lon(x, zoom):
    return x / (2 ** zoom * 256) * 360 - 180


def pixel_to_lat(y, zoom):
    return degrees(atan(sinh(pi * (1 - 2 * y / (2 ** zoom * 256)))))
