#!/usr/bin/env python3
"""Fetch QLDTraffic flood road events and flood cameras, keep those inside any
of the map REGIONS (shared with update_data.py) and write closures.json and
cameras.json.

Standard library only. A failed fetch keeps the previous file (marked stale).
Files are only rewritten when something other than generated_at* changes, so
the workflow doesn't commit on every run.

Data: QLDTraffic (c) State of Queensland, CC BY 4.0 AU.
"""
import concurrent.futures as cf
import datetime as dt
import email.utils
import json
import os
import re
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from update_data import REGIONS, UA, haversine_km

HERE = os.path.dirname(os.path.abspath(__file__))
CLOSURES_FILE = os.path.join(HERE, "closures.json")
CAMERAS_FILE = os.path.join(HERE, "cameras.json")
BNE = ZoneInfo("Australia/Brisbane")

# Public key from the QLDTraffic API specification v1.10, section 2.1.2
# (https://qldtraffic.qld.gov.au/media/moreDevelopers-and-Data/qldtraffic-website-api-specification-v1-10.pdf).
# It is shared by everyone and frequently returns HTTP 429, hence the fallback.
API_KEY = "3e83add325cbb69ac4d8e5bf433d770b"
EVENTS_API = "https://api.qldtraffic.qld.gov.au/v2/events?apikey=" + API_KEY
EVENTS_STATIC = "https://data.qldtraffic.qld.gov.au/events_v2.geojson"
CAMERAS_URL = "https://data.qldtraffic.qld.gov.au/floodcameras.geojson"
QLDTRAFFIC = "https://qldtraffic.qld.gov.au/"
ATTRIBUTION = "Road data \u00a9 State of Queensland (QLDTraffic), CC BY 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"

# Rough Queensland bounding box (lon/lat). Records with any vertex outside it
# are treated as junk (mis-geocoded) and excluded.
QLD_BBOX = (137.9, -29.3, 153.65, -9.0)
# Camera image older than this is reported with its time ("may be offline").
CAM_STALE_HOURS = 3


def now_bne():
    return dt.datetime.now(BNE)


def fetch_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def parse_time(s):
    """ISO 8601 (any fraction length, Z or offset) -> aware datetime in Brisbane time, or None."""
    if not s or not isinstance(s, str):
        return None
    s = re.sub(r"(\.\d{6})\d+", r"\1", s.strip()).replace("Z", "+00:00")
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=BNE)
    return t.astimezone(BNE)


def iso(t):
    return t.isoformat(timespec="seconds") if t else None


def text(t):
    return t.strftime("%a %d %b %Y %I:%M %p AEST") if t else None


def tidy(s):
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s or None


# Australian road/place names in the feed are plain ASCII; anything else
# (e.g. a Vietnamese street name from a bad reverse geocode) is junk.
NAME_OK = re.compile(r"^[A-Za-z0-9 .,'&()/\-\u2019]+$")


def name_ok(s):
    return bool(s) and bool(NAME_OK.match(s)) and re.search(r"[A-Za-z]{2}", s) is not None


# ---- geometry -------------------------------------------------------------

def parts(g):
    """GeoJSON geometry -> (points, lines) as [lat, lon] lists."""
    pts, lines = [], []
    if not isinstance(g, dict):
        return pts, lines
    t, c = g.get("type"), g.get("coordinates")
    ll = lambda p: [round(float(p[1]), 5), round(float(p[0]), 5)]
    try:
        if t == "GeometryCollection":
            for sub in g.get("geometries") or []:
                p, l = parts(sub)
                pts += p
                lines += l
        elif t == "Point":
            pts.append(ll(c))
        elif t == "MultiPoint":
            pts += [ll(p) for p in c]
        elif t == "LineString":
            lines.append([ll(p) for p in c])
        elif t == "MultiLineString":
            lines += [[ll(p) for p in line] for line in c]
        elif t in ("Polygon", "MultiPolygon"):
            rings = c if t == "Polygon" else [r for poly in c for r in poly]
            lines += [[ll(p) for p in ring] for ring in rings]
    except (TypeError, ValueError, IndexError):
        return [], []
    # drop consecutive duplicate vertices and degenerate lines
    clean_lines = []
    for line in lines:
        out = [p for i, p in enumerate(line) if i == 0 or p != line[i - 1]]
        if len(out) >= 2:
            clean_lines.append(out)
        elif out:
            pts.append(out[0])
    return pts, clean_lines


def in_qld(lat, lon):
    return QLD_BBOX[0] <= lon <= QLD_BBOX[2] and QLD_BBOX[1] <= lat <= QLD_BBOX[3]


def region_for(vertices):
    """Nearest-centre region among all regions containing any vertex (same
    rule as gauges), or None."""
    best = None
    for lat, lon in vertices:
        for reg in REGIONS:
            d = haversine_km(reg["lat"], reg["lon"], lat, lon)
            if d <= reg["radius_km"] and (best is None or d < best[1]):
                best = (reg, d)
    return best


def marker_point(pts, lines):
    """A representative [lat, lon]: the vertex nearest the centroid."""
    vs = pts + [p for line in lines for p in line]
    clat = sum(p[0] for p in vs) / len(vs)
    clon = sum(p[1] for p in vs) / len(vs)
    return min(vs, key=lambda p: (p[0] - clat) ** 2 + (p[1] - clon) ** 2)


# ---- closures -------------------------------------------------------------

def is_flood(p):
    return p.get("event_type") == "Flooding" or "flood" in str(p.get("event_due_to") or "").lower()


def severity(impact):
    """'closed' (road closed / all lanes blocked) or 'partial' (lanes affected,
    restricted, partial closures, etc.)."""
    it = (impact.get("impact_type") or "").lower()
    st = (impact.get("impact_subtype") or "").lower()
    if it == "closures" and "partial" not in st:
        return "closed"
    if it == "lanes blocked" and "all" in st:
        return "closed"
    return "partial"


def fetch_events():
    """(features, source dict). Official API first, static feed as fallback."""
    errors = []
    for name, url, shown in (("api", EVENTS_API, "https://api.qldtraffic.qld.gov.au/v2/events"),
                             ("fallback", EVENTS_STATIC, EVENTS_STATIC)):
        try:
            d = fetch_json(url, timeout=60)
            feats = d.get("features") if isinstance(d, dict) else None
            if not isinstance(feats, list) or not feats:
                raise ValueError("no features in response")
            print(f"events: {len(feats)} from {name} ({shown})")
            return feats, {"used": name, "url": shown, "feed_published": iso(parse_time(d.get("published"))),
                           "errors": errors}
        except urllib.error.HTTPError as e:
            errors.append(f"{name}: HTTP {e.code}")
        except Exception as e:  # noqa: BLE001 - any failure -> try the next source
            errors.append(f"{name}: {type(e).__name__}: {e}")
        print(f"WARN: events {errors[-1]}", file=sys.stderr)
    raise RuntimeError("; ".join(errors))


def build_closures(feats):
    now = now_bne()
    out, excluded = [], []
    for f in feats:
        p = (f or {}).get("properties") or {}
        if not is_flood(p):
            continue
        pts, lines = parts(f.get("geometry"))
        verts = pts + [v for line in lines for v in line]
        if not verts:
            continue
        hit = region_for(verts)
        if not hit:
            continue
        rs = p.get("road_summary") or {}
        road = tidy(rs.get("road_name"))
        why = None
        if not all(in_qld(*v) for v in verts):
            why = "geometry outside Queensland"
        elif not name_ok(road):
            why = f"implausible road name {road!r}"
        elif (p.get("status") or "Published") != "Published":
            why = f"status {p.get('status')}"
        else:
            end = parse_time((p.get("duration") or {}).get("end"))
            if end and end < now:
                why = f"ended {iso(end)}"
        if why:
            excluded.append({"id": p.get("id"), "road": road, "locality": tidy(rs.get("locality")),
                             "lga": tidy(rs.get("local_government_area")), "reason": why})
            continue
        reg = hit[0]
        imp = p.get("impact") or {}
        src = p.get("source") or {}
        upd = parse_time(p.get("last_updated"))
        start = parse_time((p.get("duration") or {}).get("start"))
        link = p.get("web_link") if str(p.get("web_link") or "").startswith("https://") else QLDTRAFFIC
        out.append({
            "id": p.get("id"),
            "road": road,
            "description": tidy(p.get("description")),
            "locality": tidy(rs.get("locality")),
            "lga": tidy(rs.get("local_government_area")),
            "event_type": p.get("event_type"),
            "event_subtype": tidy(p.get("event_subtype")),
            "due_to": tidy(p.get("event_due_to")),
            "impact": tidy(imp.get("impact_subtype")) or tidy(imp.get("impact_type")),
            "impact_type": tidy(imp.get("impact_type")),
            "severity": severity(imp),
            "direction": tidy(imp.get("direction")),
            "advice": tidy(p.get("advice")),
            "information": tidy(p.get("information")),
            "status": p.get("status"),
            "start": iso(start),
            "last_updated": iso(upd),
            "last_updated_text": text(upd),
            "provided_by": tidy(src.get("provided_by")),
            "source_link": link,
            "api_url": p.get("url"),
            "region": reg["id"],
            "region_name": reg["name"],
            "marker": marker_point(pts, lines),
            "geometry": {"points": pts, "lines": lines},
        })
    order = {r["id"]: i for i, r in enumerate(REGIONS)}
    out.sort(key=lambda c: (order[c["region"]], c["severity"] != "closed", c["road"] or ""))
    return out, excluded


def region_counts(items, extra=None):
    res = []
    for reg in REGIONS:
        mine = [x for x in items if x["region"] == reg["id"]]
        row = {"id": reg["id"], "name": reg["name"], "count": len(mine)}
        if extra:
            row.update(extra(mine))
        res.append(row)
    return res


# ---- cameras --------------------------------------------------------------

def image_info(url):
    """HEAD the image: (ok, last_modified datetime or None, note)."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA,
                                     "Referer": "https://alanjhaase-lang.github.io/"})
        with urllib.request.urlopen(req, timeout=15) as r:
            lm = r.headers.get("Last-Modified")
            t = email.utils.parsedate_to_datetime(lm).astimezone(BNE) if lm else None
            return True, t, None
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}: {e}"


def build_cameras(feats):
    now = now_bne()
    cams = []
    for f in feats:
        p = (f or {}).get("properties") or {}
        pts, _ = parts(f.get("geometry"))
        if not pts or not in_qld(*pts[0]):
            continue
        hit = region_for(pts[:1])
        if not hit:
            continue
        url = str(p.get("image_url") or "").strip()
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        if not url.startswith("https://"):
            continue
        reg = hit[0]
        cams.append({
            "id": p.get("id"),
            "name": tidy(p.get("description")),
            "direction": tidy(p.get("direction")),
            "locality": tidy(p.get("locality")),
            "district": tidy(p.get("district")),
            "image_url": url,
            "image_sourced_from": tidy(p.get("image_sourced_from")),
            "info": tidy(p.get("extra_info")),
            "region": reg["id"],
            "region_name": reg["name"],
            "distance_km": round(hit[1], 1),
            "lat": pts[0][0], "lon": pts[0][1],
        })
    with cf.ThreadPoolExecutor(8) as ex:
        infos = list(ex.map(lambda c: image_info(c["image_url"]), cams))
    for c, (ok, t, note) in zip(cams, infos):
        c["image_ok"] = ok
        if note:
            c["image_error"] = note
        # Only record the image time when it is old: images refresh every
        # 30 min, so a precise time would change (and commit) on every run.
        # The browser always loads the live image.
        if t and now - t > dt.timedelta(hours=CAM_STALE_HOURS):
            c["image_time"] = iso(t.replace(second=0))
            c["image_time_text"] = text(t)
            c["image_stale"] = True
        else:
            c["image_stale"] = False if t else None
    order = {r["id"]: i for i, r in enumerate(REGIONS)}
    cams.sort(key=lambda c: (order[c["region"]], c["distance_km"]))
    return cams


# ---- output ---------------------------------------------------------------

def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def strip(d):
    return {k: v for k, v in (d or {}).items() if not k.startswith("generated_at")}


def write_if_changed(path, data, old):
    if old is not None and strip(old) == strip(data):
        print(f"no change; {os.path.basename(path)} left untouched")
        return False
    with open(path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {os.path.basename(path)}")
    return True


def mark_stale(path, old, err):
    """Keep the previous data but flag it stale (written once, not every run)."""
    if old is None:
        print(f"WARN: no previous {os.path.basename(path)} to keep", file=sys.stderr)
        return
    if old.get("stale"):
        print(f"{os.path.basename(path)} already marked stale")
        return
    old["stale"] = True
    old["stale_since"] = iso(now_bne())
    old["stale_reason"] = err
    with open(path, "w") as f:
        json.dump(old, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"marked {os.path.basename(path)} stale: {err}")


def stamp():
    t = now_bne()
    return {"generated_at": iso(t), "generated_at_text": text(t)}


def update_closures():
    old = load(CLOSURES_FILE)
    try:
        feats, source = fetch_events()
        items, excluded = build_closures(feats)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: closures failed: {e}", file=sys.stderr)
        mark_stale(CLOSURES_FILE, old, str(e))
        return False
    data = dict(stamp(), **{
        "stale": False,
        "source": source,
        "attribution": ATTRIBUTION,
        "licence": LICENCE_URL,
        "filter": "event_type == 'Flooding' or 'flood' in event_due_to (case-insensitive); any vertex inside "
                  "a region circle; region = nearest centre. severity 'closed' = road closed / all lanes "
                  "blocked, 'partial' = lanes affected, restricted or partial closure. Coordinates [lat, lon].",
        "regions": region_counts(items, lambda m: {
            "closed": sum(1 for x in m if x["severity"] == "closed"),
            "partial": sum(1 for x in m if x["severity"] == "partial")}),
        "count": len(items),
        "excluded": excluded,
        "closures": items,
    })
    write_if_changed(CLOSURES_FILE, data, old)
    print("closures: " + ", ".join(f'{r["id"]}={r["closed"]} closed/{r["partial"]} partial'
                                   for r in data["regions"]) + f"; excluded {len(excluded)}")
    return True


def update_cameras():
    old = load(CAMERAS_FILE)
    try:
        d = fetch_json(CAMERAS_URL)
        feats = d.get("features") if isinstance(d, dict) else None
        if not isinstance(feats, list) or not feats:
            raise ValueError("no features in response")
        cams = build_cameras(feats)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: cameras failed: {e}", file=sys.stderr)
        mark_stale(CAMERAS_FILE, old, str(e))
        return False
    data = dict(stamp(), **{
        "stale": False,
        "source": {"url": CAMERAS_URL},
        "attribution": ATTRIBUTION,
        "licence": LICENCE_URL,
        "note": "Images load live from image_url. image_time is only recorded when the image is older than "
                f"{CAM_STALE_HOURS} h at the last check (image_stale=true); image_ok = image URL answered HTTP 200.",
        "regions": region_counts(cams),
        "count": len(cams),
        "cameras": cams,
    })
    write_if_changed(CAMERAS_FILE, data, old)
    print("cameras: " + ", ".join(f'{r["id"]}={r["count"]}' for r in data["regions"]))
    return True


def main():
    ok1 = update_closures()
    ok2 = update_cameras()
    if not (ok1 or ok2):
        raise SystemExit("both QLDTraffic fetches failed; previous files kept")


if __name__ == "__main__":
    main()
