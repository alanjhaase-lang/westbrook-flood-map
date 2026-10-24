#!/usr/bin/env python3
"""Fetch BOM Queensland river height bulletins, join station coordinates,
keep gauges inside any of the REGIONS (Westbrook/Toowoomba, Ipswich,
Brisbane, Sunshine Coast) and write data.json.

Standard library only.
"""
import datetime as dt
import html
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BOM = "https://www.bom.gov.au"

# Westbrook, QLD (OpenStreetMap Nominatim, relation 11675945)
HOME = {"name": "Westbrook, QLD", "lat": -27.6018, "lon": 151.8723}
RADIUS_KM = 50.0

# Regions are great-circle circles around a centre (same model as the
# original 50 km Westbrook circle). A gauge inside several circles is
# assigned to the one whose centre is nearest, so every gauge appears once.
# Westbrook's circle does not overlap any other, so its behaviour is unchanged.
REGIONS = [
    {"id": "westbrook", "name": "Westbrook / Toowoomba", "short": "Westbrook",
     "lat": HOME["lat"], "lon": HOME["lon"], "radius_km": RADIUS_KM,
     "centre_name": "Westbrook", "color": "#1565c0"},
    {"id": "ipswich", "name": "Ipswich", "short": "Ipswich",
     "lat": -27.6144, "lon": 152.7590, "radius_km": 30.0,
     "centre_name": "Ipswich CBD", "color": "#6a1b9a"},
    {"id": "brisbane", "name": "Brisbane", "short": "Brisbane",
     "lat": -27.4698, "lon": 153.0251, "radius_km": 35.0,
     "centre_name": "Brisbane CBD", "color": "#00838f"},
    {"id": "sunshine", "name": "Sunshine Coast", "short": "Sunshine Coast",
     "lat": -26.6200, "lon": 153.0300, "radius_km": 40.0,
     "centre_name": "Sunshine Coast (between Maroochydore and Nambour)", "color": "#c2185b"},
]

# Bulletins listed on https://www.bom.gov.au/qld/flood/rain_river.shtml that
# contain gauges inside at least one region (see README).
BULLETINS = [
    ("IDQ60293", "Condamine, Myall Creek, Balonne, Maranoa, Wallam/Mungallala Creeks"),
    ("IDQ60286", "Stanley, Brisbane, Bremer, Lockyer, Ipswich/Brisbane Creeks, Pine/Caboolture"),
    ("IDQ60285", "Nerang, Coomera, Pimpama, Logan-Albert, Tingalpa Creek"),
    ("IDQ60287", "Mooloolah, Maroochy, Noosa, Mary"),
]


def assign_region(lat, lon):
    """(region, distance_km) for the nearest region centre whose circle contains
    the point, or (None, None)."""
    best = None
    for reg in REGIONS:
        d = haversine_km(reg["lat"], reg["lon"], lat, lon)
        if d <= reg["radius_km"] and (best is None or d < best[1]):
            best = (reg, d)
    return best if best else (None, None)


STATIONS_FILE = os.path.join(HERE, "stations.json")
DATA_FILE = os.path.join(HERE, "data.json")
SECTION3_URL = BOM + "/qld/flood/networks/section3.shtml"


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def clean(cell):
    text = re.sub(r"<[^>]+>", " ", cell)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_bulletin(page, bulletin_id):
    """Return list of dict rows from a BOM river height bulletin page."""
    rows = []
    section = None
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        th = re.findall(r"<th[^>]*>(.*?)</th>", tr, re.S | re.I)
        if th and len(th) == 1:
            section = clean(th[0])
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(tds) < 9:
            continue
        m = re.search(r'href="([^"]*?\.(\d{6})\.plt\.shtml)"', tr)
        if not m:
            continue
        plot = m.group(1)
        if plot.startswith("/"):
            plot = BOM + plot
        tbl = re.search(r'href="([^"]*?\.tbl\.shtml)"', tr)
        height = clean(tds[3])
        try:
            height_val = float(height)
        except ValueError:
            height_val = None
        rows.append({
            "name": clean(tds[0]),
            "station_type": clean(tds[1]),
            "time": clean(tds[2]),
            "height_m": height_val,
            "height_raw": height,
            "datum": clean(tds[4]),
            "tendency": clean(tds[5]).lower(),
            "crossing": clean(tds[6]),
            "flood_class": clean(tds[7]),
            "station_no": m.group(2),
            "plot_url": plot,
            "table_url": (BOM + tbl.group(1)) if tbl and tbl.group(1).startswith("/") else (tbl.group(1) if tbl else None),
            "bulletin": bulletin_id,
            "section": section,
        })
    return rows


def dms(s):
    """'281960S' / '1521900E' -> signed decimal degrees."""
    s = s.strip()
    hemi, digits = s[-1], s[:-1]
    deg, mins, secs = int(digits[:-4]), int(digits[-4:-2]), int(digits[-2:])
    val = deg + mins / 60 + secs / 3600
    return -val if hemi in "SW" else val


def parse_section3(page):
    """BOM 'Index of Queensland river height stations' -> {station_no: info}."""
    out = {}
    pat = re.compile(r"^\s*(\d{6})\s+(\d{6})?\s+(.{30})\s+(.{23})\s+(.{20})\s+(\d{6,7}[NS])\s+(\d{7,8}[EW])",
                     re.M)
    for m in pat.finditer(html.unescape(page)):
        out[m.group(1)] = {
            "bom_name": m.group(3).strip(),
            "stream": m.group(4).strip(),
            "basin": m.group(5).strip(),
            "lat": round(dms(m.group(6)), 5),
            "lon": round(dms(m.group(7)), 5),
        }
    return out


NFGN_URL = ("https://hosting.wsapi.cloud.bom.gov.au/arcgis/rest/services/flood/"
            "National_Flood_Gauge_Network/FeatureServer/5/query")


def lookup_nfgn(station_nos):
    """BOM National Flood Gauge Network feature service -> {station_no: attrs}."""
    out = {}
    nums = sorted({int(n) for n in station_nos})
    for i in range(0, len(nums), 100):
        chunk = ",".join(str(n) for n in nums[i:i + 100])
        q = urllib.parse.urlencode({
            "where": f"bom_stn_num IN ({chunk})",
            "outFields": "bom_stn_num,awrc_stateid,name,lat,long,state,basin,agency",
            "returnGeometry": "false", "f": "json"})
        data = json.loads(fetch(NFGN_URL + "?" + q))
        for f in data.get("features", []):
            a = f["attributes"]
            if a.get("lat") is not None and a.get("long") is not None:
                out[str(a["bom_stn_num"]).zfill(6)] = a
    return out


def lookup_authoritative(station_nos, names):
    """Coordinates from BOM NFGN, then BOM Qld section-3 station index."""
    found = {}
    try:
        nf = lookup_nfgn(station_nos)
    except Exception as e:
        print(f"WARN: NFGN lookup failed: {e}", file=sys.stderr)
        nf = {}
    for no, a in nf.items():
        found[no] = {"station_no": no, "name": names.get(no), "bom_name": a.get("name"),
                     "awrc": a.get("awrc_stateid"), "lat": round(a["lat"], 5),
                     "lon": round(a["long"], 5), "source": "bom_nfgn", "geocoded": False}
    rest = [n for n in station_nos if n not in found]
    if rest:
        try:
            idx = parse_section3(fetch(SECTION3_URL))
        except Exception as e:
            print(f"WARN: section3 lookup failed: {e}", file=sys.stderr)
            idx = {}
        for no in rest:
            if no in idx:
                i = idx[no]
                found[no] = {"station_no": no, "name": names.get(no), "bom_name": i["bom_name"],
                             "awrc": None, "lat": i["lat"], "lon": i["lon"],
                             "source": "bom_section3", "geocoded": False}
    return found


# ---------------------------------------------------------------------------
# Official flood classification levels (minor / moderate / major)
# ---------------------------------------------------------------------------
FLOOD_LEVELS_FILE = os.path.join(HERE, "flood_levels.json")
FLOOD_CLASSES = ("minor", "moderate", "major")
LEVELS_NEW_PER_RUN = 60       # stations with no cached entry fetched per run
LEVELS_REFRESH_PER_RUN = 8    # oldest cached entries re-checked per run ...
LEVELS_MAX_AGE_DAYS = 30      # ... once they are older than this


def parse_flood_levels(page):
    """'Flood Classification Levels' block of a BOM station plot/table page.

    Returns {"minor", "moderate", "major", "datum", "raw"}; levels are floats or
    None. BOM prints AHD levels as e.g. 'Minor: 2.50 m AHD' and local gauge
    height (LGH) levels with no suffix, so datum is 'AHD', 'LGH' or None (no
    levels / mixed). Returns None if the page has no classification block."""
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
    m = re.search(r"Flood Classification Levels:(.*?)(?:Crossing Levels|Data from|Data as Table|$)", text)
    if not m:
        return None
    block = m.group(1)
    out = {"minor": None, "moderate": None, "major": None, "datum": None,
           "raw": "Flood Classification Levels:" + block.rstrip()}
    datums = set()
    for cls, val, ahd in re.findall(r"\b(Minor|Moderate|Major)\s*:\s*(-?\d+(?:\.\d+)?)\s*m\b(\s*AHD)?",
                                    block, re.I):
        out[cls.lower()] = float(val)
        datums.add("AHD" if ahd.strip() else "LGH")
    out["datum"] = datums.pop() if len(datums) == 1 else None
    return out


def load_flood_levels():
    if os.path.exists(FLOOD_LEVELS_FILE):
        with open(FLOOD_LEVELS_FILE) as f:
            return json.load(f).get("levels", {})
    return {}


def save_flood_levels(levels):
    payload = {
        "note": "Official BOM flood classification levels (metres) keyed by BOM station number, "
                "scraped from the 'Flood Classification Levels' line of each station's BOM river "
                "height plot page (source_url). datum='AHD' when BOM prints 'm AHD', otherwise "
                "'LGH' (local gauge height, the same gauge datum as the bulletin reading). "
                "Levels are null where BOM publishes none. checked = date last fetched (AEST).",
        "levels": dict(sorted(levels.items())),
    }
    with open(FLOOD_LEVELS_FILE, "w") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
        f.write("\n")


def fetch_flood_levels(station_no, plot_url):
    lv = parse_flood_levels(fetch(plot_url))
    today = dt.datetime.now(ZoneInfo("Australia/Brisbane")).date().isoformat()
    entry = {"minor": None, "moderate": None, "major": None, "datum": None}
    if lv:
        entry.update({k: lv[k] for k in ("minor", "moderate", "major", "datum")})
    entry.update(source="bom_station_plot_page", source_url=plot_url, checked=today)
    return entry


def update_flood_levels(levels, rows, new_limit=LEVELS_NEW_PER_RUN,
                        refresh_limit=LEVELS_REFRESH_PER_RUN, workers=6):
    """Fetch levels for stations without a cached entry, plus a few stale ones.
    Returns True if anything changed. Failures keep the old entry."""
    from concurrent.futures import ThreadPoolExecutor
    urls = {}
    for r in rows:
        urls.setdefault(r["station_no"], r["plot_url"])
    new = [n for n in sorted(urls) if n not in levels][:new_limit]
    today = dt.datetime.now(ZoneInfo("Australia/Brisbane")).date()
    def age(n):
        try:
            return (today - dt.date.fromisoformat(levels[n].get("checked", ""))).days
        except ValueError:
            return 10 ** 6
    old = sorted((n for n in urls if n in levels and age(n) > LEVELS_MAX_AGE_DAYS),
                 key=age, reverse=True)[:refresh_limit]
    todo = new + old
    if not todo:
        return False
    def one(n):
        try:
            return n, fetch_flood_levels(n, urls[n])
        except Exception as e:
            print(f"WARN: flood levels {n} failed: {e}", file=sys.stderr)
            return n, None
    changed = False
    with ThreadPoolExecutor(workers) as ex:
        for n, entry in ex.map(one, todo):
            if entry is None:
                continue
            prev = levels.get(n)
            strip = lambda e: {k: v for k, v in (e or {}).items() if k != "checked"}
            if prev is None or strip(prev) != strip(entry):
                print(f"flood levels {n}: {strip(prev) or None} -> {strip(entry)}")
            levels[n] = entry
            changed = True
    return changed


def bulletin_class(fc):
    k = (fc or "").strip().lower()
    if k.startswith("below"):
        return "Below Flood Level"
    for c in FLOOD_CLASSES:
        if k.startswith(c):
            return c.capitalize()
    return None


def flood_status(row, lv):
    """Flood-class fields for one bulletin row given its cached levels entry.

    delta_m = next_level_m - height_m (positive = metres still to go)."""
    out = {"flood_levels": None, "computed_class": None, "next_class": None,
           "next_level_m": None, "delta_m": None, "above_major_m": None,
           "class_check": None, "flood_levels_note": None}
    have = lv and any(lv.get(c) is not None for c in FLOOD_CLASSES)
    if not have:
        out["flood_levels_note"] = "no official flood levels published by BOM for this gauge"
        return out
    if lv.get("datum") != row.get("datum"):
        # e.g. levels in AHD but bulletin height in local gauge height: a
        # delta would be meaningless, so show nothing rather than a wrong number.
        out["flood_levels_note"] = (f"datum mismatch: levels {lv.get('datum') or 'unknown'}, "
                                    f"reading {row.get('datum') or 'unknown'}; not compared")
        return out
    out["flood_levels"] = {c: lv.get(c) for c in FLOOD_CLASSES}
    out["flood_levels"].update(datum=lv["datum"], source_url=lv.get("source_url"))
    h = row.get("height_m")
    if h is None:
        return out
    known = [(c, lv[c]) for c in FLOOD_CLASSES if lv.get(c) is not None]
    current = "Below Flood Level"
    for c, level in known:
        if round(h - level, 3) >= 0:
            current = c.capitalize()
    out["computed_class"] = current
    nxt = next(((c, level) for c, level in known if round(h - level, 3) < 0), None)
    if nxt:
        out["next_class"] = nxt[0].capitalize()
        out["next_level_m"] = nxt[1]
        out["delta_m"] = round(nxt[1] - h, 2)
    elif lv.get("major") is not None:
        out["above_major_m"] = round(h - lv["major"], 2)
    bc = bulletin_class(row.get("flood_class"))
    if bc is None:
        out["class_check"] = "no bulletin class"
    else:
        out["class_check"] = "agrees" if bc == current else f"differs (bulletin: {bc})"
    return out


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_stations():
    if os.path.exists(STATIONS_FILE):
        with open(STATIONS_FILE) as f:
            return {s["station_no"]: s for s in json.load(f)["stations"]}
    return {}


def save_stations(stations):
    payload = {
        "note": "Station coordinate lookup keyed by BOM station number. "
                "source=bom_nfgn: BOM National Flood Gauge Network feature service (" + NFGN_URL + "). "
                "source=bom_section3: BOM 'Index of Queensland River Height Stations' (" + SECTION3_URL + "). "
                "source=geocoded_*: name-based fallback (OpenStreetMap Nominatim), approximate; geocoded=true.",
        "stations": sorted(stations.values(), key=lambda s: s["station_no"]),
    }
    with open(STATIONS_FILE, "w") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
        f.write("\n")


def main():
    stations = load_stations()
    old = None
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                old = json.load(f)
        except (ValueError, OSError):
            old = None
    rows, used, carried, failed = [], [], [], []
    for bid, desc in BULLETINS:
        url = f"{BOM}/fwo/{bid}.html"
        try:
            r = parse_bulletin(fetch(url), bid)
            if not r:
                raise ValueError("no rows parsed")
        except Exception as e:  # keep going if one bulletin fails
            print(f"WARN: {bid} failed: {e}", file=sys.stderr)
            failed.append(bid)
            # Keep the previous readings for this bulletin rather than
            # silently dropping a whole region from the map.
            prev = [x for x in (old or {}).get("stations", []) if x.get("bulletin") == bid]
            if prev:
                carried.extend(prev)
                used.append({"id": bid, "description": desc, "url": url, "rows": len(prev),
                             "stale": True})
            continue
        print(f"{bid}: {len(r)} rows")
        used.append({"id": bid, "description": desc, "url": url, "rows": len(r)})
        rows.extend(r)
    if len(failed) == len(BULLETINS):
        raise SystemExit("all bulletins failed; data.json left untouched")

    # New station numbers we have no coordinates for: look them up in BOM
    # sources (never geocoded automatically) and cache in stations.json.
    missing = sorted({r["station_no"] for r in rows} - set(stations))
    if missing:
        names = {r["station_no"]: r["name"] for r in rows}
        found = lookup_authoritative(missing, names)
        if found:
            stations.update(found)
            save_stations(stations)
            print(f"added {len(found)} new station(s) to stations.json")

    # Official flood classification levels, cached in flood_levels.json.
    flevels = load_flood_levels()
    try:
        mine = [r for r in rows if (stations.get(r["station_no"]) or {}).get("lat") is not None
                and assign_region(stations[r["station_no"]]["lat"],
                                  stations[r["station_no"]]["lon"])[0] is not None]
        if update_flood_levels(flevels, mine):
            save_flood_levels(flevels)
    except Exception as e:  # never let this stop the gauge update
        print(f"WARN: flood level update failed: {e}", file=sys.stderr)

    seen, out, nocoord = set(), [], []
    for r in rows:
        if r["station_no"] in seen:  # same gauge listed in two bulletins
            continue
        seen.add(r["station_no"])
        s = stations.get(r["station_no"])
        if not s or s.get("lat") is None:
            nocoord.append(f'{r["station_no"]} {r["name"]}')
            continue
        reg, d = assign_region(s["lat"], s["lon"])
        if reg is None:
            continue
        r.update(lat=s["lat"], lon=s["lon"], coord_source=s["source"],
                 geocoded=bool(s.get("geocoded")), region=reg["id"],
                 region_name=reg["name"], distance_km=round(d, 1),
                 distance_from=reg["centre_name"])
        r.update(flood_status(r, flevels.get(r["station_no"])))
        out.append(r)
    for r in carried:  # previous readings of a bulletin that failed this run
        if r["station_no"] not in seen:
            seen.add(r["station_no"])
            r.update(flood_status(r, flevels.get(r["station_no"])))
            out.append(r)
    order = {reg["id"]: i for i, reg in enumerate(REGIONS)}
    out.sort(key=lambda x: (order.get(x.get("region"), 99), x["distance_km"]))
    regions = []
    for reg in REGIONS:
        mine = [x for x in out if x.get("region") == reg["id"]]
        flood = sum(1 for x in mine if re.match(r"(minor|moderate|major)", (x.get("flood_class") or "").lower()))
        regions.append(dict(reg, count=len(mine), in_flood=flood))

    now = dt.datetime.now(ZoneInfo("Australia/Brisbane"))
    data = {
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_text": now.strftime("%a %d %b %Y %I:%M %p AEST"),
        "home": HOME,
        "radius_km": RADIUS_KM,
        "regions": regions,
        "bulletins": used,
        "stations_without_coordinates": nocoord,
        "flood_levels_source": "BOM station plot pages ('Flood Classification Levels'), cached in "
                               "flood_levels.json; delta_m = next_level_m - height_m (metres to go)",
        "count": len(out),
        "stations": out,
    }
    # Avoid a commit every run when only the timestamp would change.
    if old is not None:
        strip = lambda d: {k: v for k, v in d.items() if not k.startswith("generated_at")}
        if strip(old) == strip(data):
            print("no change in gauge data; data.json left untouched")
            return
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {DATA_FILE}: {len(out)} stations (" +
          ", ".join(f'{x["id"]}={x["count"]}' for x in regions) + "); "
          f"{len(nocoord)} bulletin stations lacked coordinates")


if __name__ == "__main__":
    main()
