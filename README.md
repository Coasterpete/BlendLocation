# BlendLocation

BlendLocation is a GPL-3.0 Blender 5.2 extension for selecting a geographic site and importing its elevation terrain. **Add Location** shows an interactive street map or US aerial preview in the 3D View. The selected rectangle drives the existing Mapzen Terrarium DEM import. Preview imagery is never projected onto the terrain.

## Install and use

1. Install `dist/blendlocation-0.2.0.zip` with **Edit → Preferences → Get Extensions → Install from Disk** in Blender 5.2.x. Enable the extension if prompted.
2. Open the 3D View sidebar (**N**) and select **BlendLocation → Add Location**. The map opens at the coordinates and dimensions already entered in the panel.
3. Drag empty map space to draw a new site rectangle. Drag inside it to move it; drag a corner to resize it. Middle or right drag pans the map, and the mouse wheel zooms at the cursor.
4. Choose **Map · OSM** or **Aerial · USGS** in the sidebar. The sidebar and map footer show the selected WGS84 center and width and height in meters. Enter exact values in the sidebar and use **Center Map Here** if you want the view to follow the entered coordinates.
5. Click **Confirm** to copy the selection into the regular latitude, longitude, width, and height settings. **Import** confirms and immediately imports terrain using the selected elevation provider. **Cancel** or **Esc** closes the picker without changing the site settings or scene.

Manual latitude and longitude entry and the original **Import Terrain** button remain available. Select **Offline fixture** as the elevation provider to test terrain import without downloading DEM data. The picker itself needs imagery service access and reports loading, errors, and unavailable aerial coverage in the sidebar and map overlay. You can switch back to Map when aerial coverage is unavailable.

## UI and data architecture

The picker is a Blender `VIEW_3D` modal operator with a `SpaceView3D` `POST_PIXEL` GPU draw handler. It draws a bounded map viewport, selection rectangle, dimensions, status, and attribution. A temporary `WindowManager` property group holds edits until confirmation; it is not stored on the scene. The operator releases its timer, draw handler, images, and GPU textures on confirm, cancel, or extension unregister.

`map_math.py` uses the same WGS84 `Area` and Web Mercator helpers as the DEM pipeline. Map coordinates convert to the site's center and dimensions in meters before import. `map_imagery.py` defines a separate `PreviewProvider` interface; neither preview provider supplies elevation. One background worker performs network and cache I/O, while Blender image loading, GPU creation, and all Blender data changes remain on the main thread. Only the active view is requested; old results are discarded after pan, zoom, or provider changes. No browser, external webview, third-party Python dependency, search autocomplete, or imagery prefetch is used.

`geocoding.py` defines a replaceable `Geocoder` interface returning WGS84 places for a future explicitly submitted named-place query. M1 makes no geocoding requests. Enter coordinates to center a place precisely today.

Each terrain import creates a `BlendLocation Site` collection with a `Terrain` child and `DEM Terrain` mesh. The site stores its WGS84 origin, dimensions, coordinate convention, DEM provider, sample counts, and source attribution. Blender X is east, Y is north, and mesh coordinates and elevations are in meters near the Blender origin. Latitude and longitude are metadata, not object coordinates.

## Imagery sources and request limits

- **Street map:** [OpenStreetMap standard raster tiles](https://operations.osmfoundation.org/policies/tiles/) at `https://tile.openstreetmap.org/{z}/{x}/{y}.png`. The picker displays `© OpenStreetMap contributors` and the copyright URL. Requests identify BlendLocation in the User-Agent, follow cache headers or retain tiles for seven days when headers are absent, and use conditional requests for expired cached tiles. A view is limited to 20 visible tiles. There is no bulk downloading or offline prefetch.
- **Aerial preview:** [USGS NAIP Plus ImageServer](https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer?f=pjson) natural-color `exportImage`, after a catalog coverage query at the view center. One bounded export is requested for the active view, at no more than 768 × 512 pixels; results are cached for seven days. The service includes NAIP and other high resolution orthoimagery, with varying acquisition dates. The overlay credits USGS, USDA, and The National Map. A missing center coverage result shows a message and leaves street map access available. The [ArcGIS export interface](https://developers.arcgis.com/rest/services-reference/enterprise/export-image/) and [USGS National Map usage information](https://www.usgs.gov/programs/national-geospatial-program/national-map) were checked for this implementation. Aerial preview does not imply current imagery.

## Elevation source

The DEM provider reads 256-pixel Terrarium PNG tiles from the [Mapzen Terrain Tiles AWS open-data bucket](https://registry.opendata.aws/terrain-tiles/) using its [documented endpoint](https://github.com/tilezen/joerd/blob/master/docs/use-service.md). The underlying DEM dataset and [attribution](https://github.com/tilezen/joerd/blob/master/docs/attribution.md) vary by region. BlendLocation records the provider and attribution link on each site collection. The offline fixture is synthetic; no third-party terrain or map imagery is bundled.

Terrarium elevation is decoded as `R × 256 + G + B / 256 − 32768` meters. Terrain vertices use original tile pixel centers inside the selected rectangle. The picker does not alter DEM zoom or add elevation detail. The source vertical datum varies; Blender Z keeps source elevations without a datum conversion or zero shift.

## Build and test

Requires Python 3.10+ for the driver and Blender **5.2.x** for extension build and headless smoke tests. The driver searches `PATH`, common standalone installs, and Steam on Windows; override with `BLENDER_EXECUTABLE` or `--blender PATH`.

```sh
python -m unittest discover -s tests -v
python tools/blender.py build
python tools/blender.py test
```

`build` validates the manifest, builds `dist/blendlocation-0.2.0.zip`, and validates the ZIP. `test` installs it into a temporary Blender extension repository, verifies registration, imports the offline DEM fixture, checks geometry and metadata, and verifies clean unregistration. Unit tests use a synthetic map PNG to check visible tile caching and failure handling, aerial coverage failure and export, selection movement and corner resizing, zoom behavior, and map-to-terrain alignment. The native viewport interaction was also checked in Blender 5.2.2.

The default cache is `%LOCALAPPDATA%/BlendLocation` on Windows or `$XDG_CACHE_HOME/BlendLocation` (falling back to `~/.cache`) elsewhere. Map and DEM data use separate subdirectories.

## Limits

- Areas must be 50 m to 100 km along each axis and fit within Web Mercator latitude coverage without crossing the antimeridian. Very small sites need at least two original DEM pixels per axis.
- The DEM provider selects zoom around 25 m pixel spacing where possible and limits imports to 16 tiles and 512 × 512 original samples. This is not a guarantee of underlying DEM accuracy.
- Coordinates use a WGS84 local tangent-plane approximation centered on the site. Large areas are not a surveyed projected CRS. The imported footprint follows source pixel centers and may sit slightly inside the requested rectangle.
- USGS aerial availability is checked at the view center. Coverage may vary within the visible extent or be absent outside supported US areas. Acquisition dates vary. The aerial request uses a single limited-size export, so it can appear softer than the street map at high zoom.
- Map previews require the remote services unless images remain valid in cache. Unavailable services show an error; terrain can still be imported through manual coordinates if its DEM source is available. Terrain downloads are synchronous with tile-count progress, as in M0.
- Blender 5.2.x is the supported version.

## License

Extension source code is [GPL-3.0](LICENSE). Terrain and imagery are supplied by their respective providers under their own attribution terms.
