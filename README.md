# BlendLocation

BlendLocation is a free, GPL-3.0 Blender 5.2 extension for importing real elevation terrain into a local site model. M0 provides a small terrain-only workflow; imagery, buildings, roads, geocoding, and terrain editing are future work.

## Install and use

1. Download the built `blendlocation-0.1.0.zip` from `dist/`, or build it as described below. In Blender 5.2.x, open **Edit → Preferences → Get Extensions → Install from Disk** and select the ZIP. Enable BlendLocation if prompted. The ZIP is a Blender extension, not a legacy add-on ZIP.
2. In the 3D View, open the sidebar with **N** and select **BlendLocation**.
3. Enter the site center in WGS84 latitude and longitude degrees, width and height, and choose meters or kilometers. Choose **Mapzen Terrain Tiles** for real data or **Offline fixture** to test without internet. Click **Import Terrain**.

Each import creates a `BlendLocation Site` collection with a `Terrain` child collection and a `DEM Terrain` mesh. The site collection stores the geographic origin, horizontal coordinate system, requested dimensions, DEM provider, sample counts, and attribution reference. Blender X is east, Y is north, and all coordinates and elevations are meters. The object remains near the Blender origin; longitude and latitude are metadata, never object coordinates.

## Data source and attribution

The real-data provider reads 256-pixel Terrarium PNG tiles from the publicly accessible [Mapzen Terrain Tiles AWS open-data bucket](https://registry.opendata.aws/terrain-tiles/) using the [documented S3 endpoint](https://github.com/tilezen/joerd/blob/master/docs/use-service.md). The endpoint returned HTTP 200 during M0 development on 2026-09-22. It requires no API key. The registry describes the dataset as open data and links to the [source attribution requirements](https://github.com/tilezen/joerd/blob/master/docs/attribution.md). The underlying DEM source and its attribution vary by region; credit the applicable source when publishing terrain derived from these tiles. The registry suggests: “Terrain Tiles was accessed on DATE from https://registry.opendata.aws/terrain-tiles.” BlendLocation records the provider and attribution link on each site collection. No third-party terrain is bundled in the extension; the 4 × 4 offline fixture is synthetic.

Terrarium elevation is decoded as `R × 256 + G + B / 256 − 32768` meters. Terrain vertices represent original tile pixel centers within the requested rectangle. BlendLocation does not interpolate or claim extra source detail. The upstream tiles may themselves combine or resample different DEM datasets. Source vertical datums vary, so Blender Z is the source elevation in meters, with no datum conversion or zero shift.

## Build and test

Requirements: Python 3.10+ for the driver and unit tests, and Blender **5.2.x** for building and headless integration tests. The driver checks the version and searches `PATH`, common standalone installations, and Steam on Windows. Override discovery with `BLENDER_EXECUTABLE` or `--blender PATH`. It does not require Steam.

```sh
python -m unittest discover -s tests -v
python tools/blender.py build
python tools/blender.py test
# Example override:
python tools/blender.py test --blender /path/to/blender
```

`build` validates the manifest, builds `dist/blendlocation-0.1.0.zip`, and validates the ZIP using the selected Blender 5.2 executable. `test` also installs the ZIP into a temporary Blender extension repository, verifies registration, imports the offline fixture, checks terrain geometry and metadata, and verifies clean unregistration. Temporary user resource paths keep the smoke test separate from the developer's Blender profile. The default cache for real tiles is `%LOCALAPPDATA%/BlendLocation/terrarium` on Windows or `$XDG_CACHE_HOME/BlendLocation/terrarium` (falling back to `~/.cache`) elsewhere.

## M0 limits

- Areas must be 50 m to 100 km along each axis and fit within Web Mercator latitude coverage without crossing the antimeridian. Very small sites need at least two original tile pixels per axis.
- The provider selects zoom at roughly 25 m pixel spacing where available, then coarsens large requests to at most 16 tiles and 512 × 512 source samples. Tile pixel spacing is not a guarantee of underlying DEM accuracy.
- Coordinates use a WGS84 local tangent-plane approximation centered on the site. For large areas, this is not a surveyed projected CRS. The imported footprint follows source pixel centers and may sit slightly inside the requested rectangle.
- Downloads run synchronously with tile-count progress in Blender's status area. A failed download or invalid tile cancels the import; cached tiles are reused and damaged cache entries are redownloaded.
- Blender 5.2.x is the only tested version. There is no claim of support for earlier Blender releases.

## License

Extension source code is [GPL-3.0](LICENSE). Terrain data is supplied by its respective providers under their own attribution terms.
