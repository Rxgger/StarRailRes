#!/usr/bin/env python3
"""
Pulls light cone data from the private-build API and adds any light cone
that's missing from this StarRailRes repo's light_cones.json,
light_cone_promotions.json, and light_cone_ranks.json.

Asks for confirmation per missing light cone before adding it.

Run this from the StarRailRes repo root (same folder as index_new/).
"""

import json
import os
import sys
import urllib.request

LIGHTCONES_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/lightcones.json"
TEXTMAPS_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/textmaps.json"

LIGHT_CONES_PATH = os.path.join("index_new", "en", "light_cones.json")
PROMOTIONS_PATH = os.path.join("index_new", "en", "light_cone_promotions.json")
RANKS_PATH = os.path.join("index_new", "en", "light_cone_ranks.json")

PROMOTION_STATS = ("hp", "atk", "def")


def fetch_json(url: str):
    print(f"Fetching {url} ...")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def load_json(path: str):
    if not os.path.exists(path):
        print(
            f"ERROR: {path} does not exist. Run this script from the StarRailRes repo root.",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")


def clean_number(value):
    """Round away float32->float64 conversion noise and turn whole numbers
    into plain ints, matching the existing files' formatting."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        rounded = round(float(value), 6)
        return int(rounded) if rounded == int(rounded) else rounded
    return value


def resolve_text(hash_value, textmap_en: dict) -> str:
    key = str(hash_value)
    return textmap_en.get(key, key)


def build_light_cone_entry(lc: dict, textmap_en: dict) -> dict:
    return {
        "id": str(lc["id"]),
        "name": resolve_text(lc["name"], textmap_en),
        "rarity": lc["rarity"],
        "path": lc["path"],
        # The API's own top-level "desc" field is always 0 (unused). The
        # real description lives at rank.desc instead — the same hash used
        # for the passive's own description in build_rank_entry.
        "desc": resolve_text(lc["rank"]["desc"], textmap_en),
        "icon": f"icon/light_cone/{lc['id']}.png",
        "preview": f"image/light_cone_preview/{lc['id']}.png",
        "portrait": f"image/light_cone_portrait/{lc['id']}.png",
    }


def build_promotion_entry(lc: dict) -> dict:
    values = []
    for tier in lc["promotion"]["values"]:
        values.append(
            {
                stat: {
                    "base": clean_number(tier[stat]["base"]),
                    "step": clean_number(tier[stat]["step"]),
                }
                for stat in PROMOTION_STATS
            }
        )
    # Deliberately no "materials" key.
    return {"id": str(lc["id"]), "values": values}


def build_rank_entry(lc: dict, textmap_en: dict) -> dict:
    rank = lc["rank"]

    params = [[clean_number(p) for p in level] for level in rank["params"]]
    properties = [
        [{"type": p["type"], "value": clean_number(p["value"])} for p in level]
        for level in rank["properties"]
    ]

    return {
        "id": str(lc["id"]),
        "skill": resolve_text(rank["skill"], textmap_en),
        "desc": resolve_text(rank["desc"], textmap_en),
        "params": params,
        "properties": properties,
    }


def confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def main():
    light_cones_api = fetch_json(LIGHTCONES_URL)
    textmaps = fetch_json(TEXTMAPS_URL)
    textmap_en = textmaps.get("EN", {})

    light_cones = load_json(LIGHT_CONES_PATH)
    promotions = load_json(PROMOTIONS_PATH)
    ranks = load_json(RANKS_PATH)

    missing_ids = [lcid for lcid in light_cones_api if lcid not in light_cones]

    if not missing_ids:
        print("No new light cones found — everything in the API is already present.")
        return

    added = []
    for lcid in missing_ids:
        lc = light_cones_api[lcid]
        display_name = resolve_text(lc["name"], textmap_en)

        if not confirm(f"Do you wanna update with {display_name} - {lcid}?"):
            print(f"Skipping {display_name} ({lcid}).")
            continue

        light_cones[lcid] = build_light_cone_entry(lc, textmap_en)
        promotions[lcid] = build_promotion_entry(lc)
        ranks[lcid] = build_rank_entry(lc, textmap_en)

        added.append(f"{display_name} ({lcid})")

    if not added:
        print("No light cones were added.")
        return

    save_json(LIGHT_CONES_PATH, light_cones)
    save_json(PROMOTIONS_PATH, promotions)
    save_json(RANKS_PATH, ranks)

    print(f"Added {len(added)} light cone(s): {', '.join(added)}")


if __name__ == "__main__":
    main()