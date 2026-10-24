#!/usr/bin/env python3
"""One-off (re)builder for stations.json.

Fetches the candidate bulletins, looks every station number up in BOM's
National Flood Gauge Network service, then BOM's Qld section-3 index, and as
a last resort geocodes the place name with OpenStreetMap Nominatim (flagged
geocoded=true). Prints the stations within the radius for each bulletin so you
can decide which bulletins to list in update_data.BULLETINS.
"""
import json
import sys
import time
import urllib.parse

import update_data as u

# Every Qld river height bulletin near SE Qld (from
# https://www.bom.gov.au/qld/flood/rain_river.shtml).
CANDIDATES = ["IDQ60293", "IDQ60286", "IDQ60285", "IDQ60287", "IDQ60292"]


def geocode(name):
    place = name.split(" at ", 1)[-1]
    for junk in (" Alert", " ALERT", " Tm", " TM", " HW", " TW", " HG"):
        place = place.replace(junk, "")
    q = urllib.parse.urlencode({"q": f"{place}, Queensland, Australia", "format": "json", "limit": 1})
    time.sleep(1.1)  # Nominatim usage policy
    res = json.loads(u.fetch("https://nominatim.openstreetmap.org/search?" + q))
    if res:
        return float(res[0]["lat"]), float(res[0]["lon"]), place, res[0]["display_name"]
    return None


def main():
    rows = []
    for bid in CANDIDATES:
        rows += u.parse_bulletin(u.fetch(f"{u.BOM}/fwo/{bid}.html"), bid)
    names = {r["station_no"]: r["name"] for r in rows}
    stations = u.load_stations()
    todo = [n for n in names if n not in stations or stations[n].get("geocoded")]
    stations.update(u.lookup_authoritative(todo, names))
    for no in [n for n in names if n not in stations]:
        g = geocode(names[no])
        if g:
            stations[no] = {"station_no": no, "name": names[no], "bom_name": None, "awrc": None,
                            "lat": round(g[0], 5), "lon": round(g[1], 5),
                            "source": f"geocoded_nominatim: '{g[2]}' -> {g[3]}", "geocoded": True}
            print(f"GEOCODED {no} {names[no]} -> {g[3]}", file=sys.stderr)
        else:
            print(f"NO COORDS {no} {names[no]}", file=sys.stderr)
    u.save_stations(stations)
    for bid in CANDIDATES:
        per = {}
        for r in rows:
            s = stations.get(r["station_no"])
            if r["bulletin"] == bid and s:
                reg, d = u.assign_region(s["lat"], s["lon"])
                if reg:
                    per.setdefault(reg["id"], []).append((round(d, 1), r["name"], s["source"][:20]))
        print(bid, {k: len(v) for k, v in per.items()} or "no gauges in any region")


if __name__ == "__main__":
    main()
