#!/usr/bin/env python3
"""(Re)build flood_levels.json: official BOM minor/moderate/major levels for
every gauge in data.json, read from each station's BOM plot page.

update_data.py fetches levels for new gauges and re-checks a few old entries
every run, so this is only needed for a full refresh:  python3 build_flood_levels.py
"""
import json
import update_data as u


def main():
    with open(u.DATA_FILE) as f:
        rows = json.load(f)["stations"]
    # Keep maintainer-set community estimates (source=user); refresh everything else.
    kept = {n: e for n, e in u.load_flood_levels().items() if e.get("source") == "user"}
    levels = {}
    u.update_flood_levels(levels, rows, new_limit=10 ** 6, refresh_limit=0)
    levels.update(kept)
    u.save_flood_levels(levels)
    have = sum(1 for e in levels.values() if any(e.get(c) is not None for c in u.FLOOD_CLASSES))
    print(f"{len(levels)} stations checked, {have} with official flood levels")
    for r in rows:
        e = levels.get(r["station_no"]) or {}
        if any(e.get(c) is not None for c in u.FLOOD_CLASSES) and e.get("datum") != r["datum"]:
            print(f"DATUM MISMATCH {r['station_no']} {r['name']}: levels {e.get('datum')} reading {r['datum']}")


if __name__ == "__main__":
    main()
