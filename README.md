# River gauges: Westbrook, Ipswich, Brisbane & Sunshine Coast

A self-updating static web map (Leaflet + OpenStreetMap) of Bureau of Meteorology
river-height gauges in four toggleable regions of south-east Queensland.

## Regions

Each region is a great-circle circle around a centre (`REGIONS` in `update_data.py`),
the same model as the original Westbrook 50 km circle. Circles are simple to reason about,
need no external boundary data, and suit gauges, which follow catchments rather than
council (LGA) lines.

| Region | Centre | Radius | Covers |
|---|---|---|---|
| Westbrook / Toowoomba | Westbrook -27.6018, 151.8723 | 50 km | original behaviour (Toowoomba, Oakey, Pittsworth, Lockyer headwaters) |
| Ipswich | Ipswich CBD -27.6144, 152.7590 | 30 km | Bremer, Warrill, lower Lockyer, Brisbane R. Wivenhoe–Moggill |
| Brisbane | Brisbane CBD -27.4698, 153.0251 | 35 km | Brisbane metro creeks, Pine/North Pine, Logan/Albert lower reaches, Tingalpa |
| Sunshine Coast | -26.62, 153.03 (between Maroochydore and Nambour) | 40 km | Caloundra to Noosa plus the Blackall Range / upper Mary hinterland |

A gauge inside more than one circle (only Ipswich/Brisbane overlap) is assigned to the
region whose centre is **nearest**, so every gauge has exactly one marker. Each gauge in
`data.json` has `region`, `region_name`, `distance_km` (to its region centre) and
`distance_from`.

The map has a collapsible panel (top right; collapsed by default on phones) with a
checkbox, gauge count, in-flood count and *Zoom* button per region, an *In flood only*
filter and *Fit on* (fit all enabled regions). Checkbox states persist in `localStorage`.

### Rain radar overlay

The panel also has a **Rain radar** checkbox (off by default; on/off and opacity persist in
`localStorage`). When on it shows the latest frame of the free
[RainViewer Weather Maps API](https://www.rainviewer.com/api/weather-maps-api.html)
(`https://api.rainviewer.com/public/weather-maps.json`), with an opacity slider (default 0.6),
a ▶/⏸ button that loops the past ~2 hours (13 frames, 10-minute steps) and the frame time in
Brisbane time (AEST). The frame list refreshes every 5 minutes along with `data.json`.
Radar tiles sit in their own pane (z-index 350) above the base map but below the region
circles and gauge markers.

RainViewer free-tier limits (since 1 Jan 2026): personal/educational use only, attribution
link to rainviewer.com required (shown in the map attribution), past frames only (no
nowcast), one colour scheme (Universal Blue, scale shown in the panel), max tile zoom 7
(the map upscales z7 tiles when zoomed in, so radar looks blocky at street level) and
100 requests/IP/minute. Availability is not guaranteed.

BOM radar is not used: BOM radar images are restricted content that needs a data licence to
republish, and BOM's radar WMS (GIS2Web) is registered-user only.

- `update_data.py` – stdlib-only Python 3.9+ script. Fetches the BOM river height
  bulletins, parses every row, joins coordinates from `stations.json`, keeps
  gauges in any region and writes `data.json` (timestamp in Australia/Brisbane).
  If only the timestamp would change, `data.json` is left untouched so the
  workflow doesn't make empty commits.
- `stations.json` – cached station-number → lat/lon lookup. New station numbers
  that appear in a bulletin are looked up automatically (BOM sources only) and
  added.
- `build_stations.py` – one-off rebuild of `stations.json` across candidate
  bulletins, including a flagged Nominatim geocode fallback.
- `index.html` – the map. Re-fetches `data.json` (and the radar frame list) every 5 minutes.
- `.github/workflows/update.yml` – runs every 30 minutes (and manually) and
  commits `data.json` when it changes.

## Data sources

Bulletins (configured in `BULLETINS` in `update_data.py`):

| Bulletin | Coverage | Why |
|---|---|---|
| [IDQ60293](https://www.bom.gov.au/fwo/IDQ60293.html) (primary) | Upper Condamine, Condamine, Balonne, Maranoa | Westbrook / Toowoomba area |
| [IDQ60286](https://www.bom.gov.au/fwo/IDQ60286.html) | Stanley, Brisbane, Bremer, Lockyer, Ipswich/Brisbane Creeks, Pine/Caboolture | Lockyer gauges (Westbrook), Ipswich, Brisbane metro creeks |
| [IDQ60285](https://www.bom.gov.au/fwo/IDQ60285.html) | Nerang, Coomera, Pimpama, Logan-Albert, Tingalpa Creek | Logan/Albert and Tingalpa gauges on Brisbane's southern edge |
| [IDQ60287](https://www.bom.gov.au/fwo/IDQ60287.html) | Mooloolah, Maroochy, Noosa, Mary | Sunshine Coast and hinterland (upper Mary) |

Also checked and excluded because they have no gauges in any region:
IDQ60292 (Macintyre, Dumaresq, Weir, Moonie), IDQ60288 (Burnett etc.).
If a bulletin fails to download, the previous readings for that bulletin are kept
(marked `stale` in `bulletins`) rather than dropping a region.

Coordinates, in priority order (`source` field in `stations.json`):

1. `bom_nfgn` – BOM [National Flood Gauge Network](https://hosting.wsapi.cloud.bom.gov.au/arcgis/rest/services/flood/National_Flood_Gauge_Network/FeatureServer/5) feature service, keyed by BOM station number.
2. `bom_section3` – BOM [Index of Queensland River Height Stations](https://www.bom.gov.au/qld/flood/networks/section3.shtml).
3. `geocoded_nominatim` – last-resort geocode of the place name after "at" (`geocoded: true`, approximate; popups say so).

## Setup (GitHub Pages)

1. Create an empty repository on GitHub, e.g. `flood-map` (no README/licence so the first push is clean).
2. Push this folder:
   ```sh
   cd flood-map
   git remote add origin https://github.com/<you>/flood-map.git
   git branch -M main
   git push -u origin main
   ```
3. **Pages**: repo → Settings → Pages → *Build and deployment* → Source: *Deploy from a branch*,
   Branch: `main`, folder `/ (root)` → Save. The site will be at
   `https://<you>.github.io/flood-map/`.
4. **Actions**: repo → Actions tab → enable workflows if prompted. Under Settings → Actions →
   General → *Workflow permissions*, choose **Read and write permissions** (the workflow also
   declares `contents: write`). Run *Update river gauge data* once via *Run workflow* to test.
   Pages will redeploy automatically after each data commit.

Note: GitHub's cron is best-effort (runs can be delayed), and scheduled workflows are
disabled automatically after 60 days without repository activity — data commits count as
activity, but if it stops, re-enable it in the Actions tab.

## Local use

```sh
python3 update_data.py           # writes data.json
python3 -m http.server 8000      # open http://localhost:8000/
```

Data © Commonwealth of Australia, Bureau of Meteorology. Not an official warning service —
always check [BOM warnings](https://www.bom.gov.au/qld/warnings/) in an emergency.
