"""Provider-neutral terrain sample container and mesh coordinates."""
from dataclasses import dataclass


@dataclass
class ElevationGrid:
    longitudes: list
    latitudes: list  # north to south
    elevations: list  # rows north to south
    provider: str
    zoom: int | None = None

    def validate(self):
        if len(self.longitudes) < 2 or len(self.latitudes) < 2:
            raise ValueError("Requested area contains fewer than two source pixels per axis")
        if len(self.elevations) != len(self.latitudes) or any(
                len(row) != len(self.longitudes) for row in self.elevations):
            raise ValueError("DEM grid dimensions do not match")


def mesh_data(grid, area):
    grid.validate()
    vertices = []
    for latitude, row in zip(grid.latitudes, grid.elevations):
        for longitude, elevation in zip(grid.longitudes, row):
            x, y = area.geo_to_local(latitude, longitude)
            vertices.append((x, y, elevation))
    columns = len(grid.longitudes)
    faces = []
    for j in range(len(grid.latitudes) - 1):
        for i in range(columns - 1):
            a = j * columns + i
            faces.append((a, a + columns, a + columns + 1, a + 1))
    return vertices, faces
