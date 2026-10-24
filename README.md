# River gauges: Westbrook, Ipswich, Brisbane & Sunshine Coast

A self-updating static web map (Leaflet + OpenStreetMap) of Bureau of Meteorology
river-height gauges in four toggleable regions of south-east Queensland.

> **Disclaimer:** Unofficial community map. Data from the Bureau of Meteorology may be delayed or
> contain faulty readings. Do not rely on it for safety decisions. Check
> [BOM warnings (bom.gov.au)](https://www.bom.gov.au/qld/warnings/), your council disaster dashboard,
> and call SES 132 500 or 000 in an emergency.
>
> The map shows this as a short line in the header panel and as a notice on first visit
> (dismissal remembered in `localStorage` key `floodmap.disclaimer.v1`; the *more* link reopens it).

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

### Road closures (flooding) and flood cameras

Two more panel checkboxes, both from [QLDTraffic](https://qldtraffic.qld.gov.au/)
(Road data © State of Queensland (QLDTraffic), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
shown in the map attribution). On/off persists in `localStorage` (`floodmap.closures.v1`, default on;
`floodmap.cameras.v1`, default off). Both respect the region checkboxes (each item belongs to one
region: nearest centre among the circles it touches, same rule as gauges) and are **not** hidden by
*In flood only*, which applies to gauges only. Counts next to the checkboxes cover enabled regions.

- **Road closures** – `closures.json`, built by `update_roads.py` from QLDTraffic events. Source order:
  the official API `https://api.qldtraffic.qld.gov.au/v2/events` with the shared public key from the
  [API spec v1.10](https://qldtraffic.qld.gov.au/media/moreDevelopers-and-Data/qldtraffic-website-api-specification-v1-10.pdf)
  (often HTTP 429 because everyone shares it), falling back to the static feed
  `https://data.qldtraffic.qld.gov.au/events_v2.geojson` (same structure, updated every minute).
  `source.used` records `api` or `fallback`. Kept: `event_type == "Flooding"` or `event_due_to`
  containing "flood" (this includes *Road damage – earlier flooding* hazards), with any vertex inside a
  region circle. Dropped (listed in `excluded` with a reason): any vertex outside a Queensland bounding
  box, implausible road names (non-ASCII/garbage, e.g. a bad reverse geocode), status other than
  Published, or an end time in the past. `severity` is `closed` (road closed to all/through traffic,
  all lanes blocked) or `partial` (lanes affected, 4WD-only, partial closures). Drawn as a red
  "no entry" marker plus solid red line (closed) or amber diamond plus dashed amber line (partial);
  popups show road, locality/LGA, impact, cause, advice, start and last-updated time (AEST) and a
  link to qldtraffic.qld.gov.au. Coordinates in `closures.json` are `[lat, lon]`
  (`marker`, `geometry.points`, `geometry.lines`).
- **Flood cameras** – `cameras.json`, from `https://data.qldtraffic.qld.gov.au/floodcameras.geojson`
  filtered to the regions. The popup loads the **live** image straight from `cameras.qldtraffic.qld.gov.au`
  (https, S3/CloudFront, no hotlink protection) with a `?t=<now>` cache-buster each time it opens; if the
  image fails it shows a link instead. The image server sends no CORS headers, so the browser cannot read
  the image time; instead the update job HEADs each image and, only when it is older than 3 h, records
  `image_time` / `image_stale` (shown in the popup, grey icon). Recording a fresh time would change the
  file, and so commit, every run. Many TMR cameras only update 6am–6pm.

On a fetch failure the previous file is kept with `stale: true`, `stale_since` and `stale_reason`
(the panel shows a warning). Like `data.json`, the files are only rewritten when something other than
`generated_at*` changes. The map re-fetches both every 5 minutes with `data.json`.

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
- `flood_levels.json` – cached official flood classification levels (see above);
  `build_flood_levels.py` rebuilds it.
- `build_stations.py` – one-off rebuild of `stations.json` across candidate
  bulletins, including a flagged Nominatim geocode fallback.
- `update_roads.py` – stdlib-only; writes `closures.json` and `cameras.json` from QLDTraffic
  (see *Road closures* above). Imports `REGIONS` from `update_data.py`.
- `index.html` – the map. Re-fetches `data.json`, `closures.json`, `cameras.json` (and the radar
  frame list) every 5 minutes. It also tries a **live in-browser BOM read** on load and every
  5 minutes: it fetches the same BOM river height bulletins (`https://www.bom.gov.au/fwo/IDQ6028x.html`)
  directly, parses them, and overlays any reading newer than the committed `data.json` (same datum
  only; flood class / metres-to-next are recomputed from the cached levels). The panel line under
  *Last updated* says whether gauges are "live from BOM" or the "GitHub snapshot", and shows the
  latest BOM observation time. BOM currently sends no CORS headers, so browsers block the direct
  read and the page falls back to `data.json` (re-fetched every 5 minutes and whenever the tab
  becomes visible again); each gauge popup shows its BOM reading time and age. Set `LIVE_PROXY` in `index.html` to the URL
  prefix of a CORS proxy you control (e.g. a free Cloudflare Worker; the BOM URL is appended
  URL-encoded) to make the live read work.
- `.github/workflows/update.yml` – runs every 15 minutes (GitHub may delay scheduled runs; and manually), runs both scripts (the road
  step runs even if the BOM step fails) and commits the data files when they change.

### Flood levels and "metres to next class"

Clicking a gauge shows, under *Flood class*, a **Next** line such as
`Minor at 1.70 m, 0.66 m to go` (or `None — above Major by 3.03 m`) and the gauge's official
**Minor / Moderate / Major** levels with the current class highlighted. Gauges for which BOM
publishes no classification show *No official flood levels for this gauge*. The marker hover
tooltip also shows the "Next: …" text. (The popup no longer shows station number, station type,
crossing or region; those fields are still in `data.json`.)

- **Source**: the *Flood Classification Levels* line on each gauge's BOM river height plot page
  (`/fwo/IDQ65xxx/IDQ65xxx.<station>.plt.shtml`, the "BOM plot" link). The BOM National Flood
  Gauge Network service has no level attributes, and the Qld network index pages (section 1–6)
  list stations only. Levels are cached in `flood_levels.json` (`source_url`, `checked` date);
  official values only, `null` when BOM publishes none.
- **Datum**: BOM writes AHD levels as `Minor: 1.70 m AHD` and local gauge height (LGH) levels with no
  suffix. A level set is used only if its datum matches the bulletin's datum column for that gauge;
  otherwise the popup says the levels were not compared (`flood_levels_note`). No mismatches exist today.
- **Fields** added to each gauge in `data.json`: `flood_levels` {minor, moderate, major, datum,
  source_url}, `computed_class` (height ≥ level ⇒ that class), `next_class`, `next_level_m`,
  `delta_m` (= next_level_m − height_m, metres to go), `above_major_m`, `class_check`
  (computed class vs the bulletin's class: `agrees` / `differs (bulletin: …)`), `flood_levels_note`.
- **Updates**: `update_data.py` fetches levels for gauges with no cached entry and re-checks the
  8 oldest entries (older than 30 days) each run. `python3 build_flood_levels.py` does a full refresh.

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
python3 update_roads.py          # writes closures.json, cameras.json
python3 -m http.server 8000      # open http://localhost:8000/
```

Data © Commonwealth of Australia, Bureau of Meteorology. Not an official warning service —
always check [BOM warnings](https://www.bom.gov.au/qld/warnings/) in an emergency.

## Live gauge relay (Cloudflare Worker)

BOM doesn't let github.io pages read its bulletins directly, so live 5-min gauge reads go through one small,
free, locked-down Cloudflare Worker shared with the Twin Waters map. Source, lock list and deploy steps:
[`bom-proxy/` in sunshine-coast-flood-map](https://github.com/alanjhaase-lang/sunshine-coast-flood-map/tree/main/bom-proxy).
It only serves `/fwo/IDQ60285|60286|60287|60293.html` to `https://alanjhaase-lang.github.io` (403 otherwise).
Set its workers.dev URL in `LIVE_PROXY` in `index.html`. If the Worker is down or unset, the map uses the
GitHub Actions `data.json` snapshot (every 15 min) as before.
