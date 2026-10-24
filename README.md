# River gauges near Westbrook, QLD

A self-updating static web map (Leaflet + OpenStreetMap) of Bureau of Meteorology
river-height gauges within **50 km** (great-circle) of Westbrook, Queensland
(-27.6018, 151.8723; OpenStreetMap Nominatim).

- `update_data.py` – stdlib-only Python 3.9+ script. Fetches the BOM river height
  bulletins, parses every row, joins coordinates from `stations.json`, keeps
  gauges within 50 km and writes `data.json` (timestamp in Australia/Brisbane).
  If only the timestamp would change, `data.json` is left untouched so the
  workflow doesn't make empty commits.
- `stations.json` – cached station-number → lat/lon lookup. New station numbers
  that appear in a bulletin are looked up automatically (BOM sources only) and
  added.
- `build_stations.py` – one-off rebuild of `stations.json` across candidate
  bulletins, including a flagged Nominatim geocode fallback.
- `index.html` – the map. Re-fetches `data.json` every 5 minutes.
- `.github/workflows/update.yml` – runs every 30 minutes (and manually) and
  commits `data.json` when it changes.

## Data sources

Bulletins (configured in `BULLETINS` in `update_data.py`):

| Bulletin | Coverage | Why |
|---|---|---|
| [IDQ60293](https://www.bom.gov.au/fwo/IDQ60293.html) (primary) | Upper Condamine, Condamine, Balonne, Maranoa | Westbrook / Toowoomba area |
| [IDQ60286](https://www.bom.gov.au/fwo/IDQ60286.html) | Stanley, Brisbane, Bremer, Lockyer, Ipswich/Brisbane Creeks, Pine/Caboolture | Lockyer Valley gauges east of Toowoomba are within 50 km |

Also checked and excluded because they have no gauges within 50 km:
IDQ60285 (Logan–Albert, Gold Coast), IDQ60287 (Mary), IDQ60292 (Macintyre, Dumaresq, Weir, Moonie).

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
