#!/usr/bin/env python3
"""
Pulls relic set and relic piece data from the private-build API and adds
any relic set that's missing from this StarRailRes repo's relic_sets.json,
along with all of its 5-star pieces in relics.json.

Asks for confirmation per missing relic set before adding it.

Run this from the StarRailRes repo root (same folder as index_new/).
"""

import json
import os
import sys
import urllib.request
import re

RELIC_SETS_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/relic-sets.json"
RELICS_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/relics.json"
TEXTMAPS_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/textmaps.json"

RELIC_SETS_PATH = os.path.join("index_new", "en", "relic_sets.json")
RELICS_PATH = os.path.join("index_new", "en", "relics.json")

TARGET_RARITY = 5


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

def format_value(val: float, is_percent: bool) -> str:
    if is_percent:
        # Convert decimal ratio to percentage (e.g., 0.06 -> 6%)
        num = clean_number(val * 100)
        return f"{num}%"
    return str(clean_number(val))

def format_description(text: str, props: list) -> str:
    # Match patterns like <unbreak>#1[i]%</unbreak> or <unbreak>#2[i]</unbreak>
    pattern = r'<unbreak>#(\d+)(?:\[i\])?(%)?</unbreak>'

    def replace_match(match):
        index = int(match.group(1)) - 1  # #1 maps to index 0
        has_percent = match.group(2) == '%'

        if 0 <= index < len(props):
            val = props[index]["value"]
            return format_value(val, has_percent)
        return match.group(0)

    return re.sub(pattern, replace_match, text)

def resolve_text(hash_value, textmap_en: dict) -> str:
    key = str(hash_value)
    return textmap_en.get(key, key)


def build_relic_set_entry(api_set: dict, textmap_en: dict) -> dict:
    set_bonus = api_set["set_bonus"]
    tiers = sorted(set_bonus.keys(), key=int)

    properties = [
        [
            {"type": p["type"], "value": clean_number(p["value"])}
            for p in set_bonus[tier]["properties"]
        ]
        for tier in tiers
    ]

    desc = []
    for idx, tier in enumerate(tiers):
        raw_text = resolve_text(set_bonus[tier]["desc"], textmap_en)
        # Format the description using the property values corresponding to this tier
        formatted_desc = format_description(raw_text, properties[idx])
        desc.append(formatted_desc)

    return {
        "id": str(api_set["id"]),
        "name": resolve_text(api_set["name"], textmap_en),
        "desc": desc,
        "properties": properties,
        "icon": f"icon/relic/{api_set['id']}.png",
    }


def build_relic_piece_entries(set_id: str, relics_api: dict, textmap_en: dict) -> dict:
    """All rarity-5 pieces belonging to this set — 4 for a cavern set
    (HEAD/HAND/BODY/FOOT), 2 for a planar set (NECK/OBJECT)."""
    entries = {}
    for piece_id, piece in relics_api.items():
        if str(piece["set_id"]) != set_id or piece["rarity"] != TARGET_RARITY:
            continue

        entries[piece_id] = {
            "id": str(piece["id"]),
            "set_id": str(piece["set_id"]),
            "name": resolve_text(piece["name"], textmap_en),
            "rarity": piece["rarity"],
            "type": piece["type"],
            "max_level": piece["max_level"],
            "main_affix_id": str(piece["main_affix_id"]),
            "sub_affix_id": str(piece["sub_affix_id"]),
            # Left blank — not something this app cares about for relics.
            "icon": "",
        }
    return entries


def confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def main():
    relic_sets_api = fetch_json(RELIC_SETS_URL)
    relics_api = fetch_json(RELICS_URL)
    textmaps = fetch_json(TEXTMAPS_URL)
    textmap_en = textmaps.get("EN", {})

    relic_sets = load_json(RELIC_SETS_PATH)
    relics = load_json(RELICS_PATH)

    missing_ids = [sid for sid in relic_sets_api if sid not in relic_sets]

    if not missing_ids:
        print("No new relic sets found — everything in the API is already present.")
        return

    added = []
    for sid in missing_ids:
        api_set = relic_sets_api[sid]
        display_name = resolve_text(api_set["name"], textmap_en)

        if not confirm(f"Do you wanna update with {display_name} - {sid}?"):
            print(f"Skipping {display_name} ({sid}).")
            continue

        relic_sets[sid] = build_relic_set_entry(api_set, textmap_en)
        relics.update(build_relic_piece_entries(sid, relics_api, textmap_en))

        added.append(f"{display_name} ({sid})")

    if not added:
        print("No relic sets were added.")
        return

    save_json(RELIC_SETS_PATH, relic_sets)
    save_json(RELICS_PATH, relics)

    print(f"Added {len(added)} relic set(s): {', '.join(added)}")


if __name__ == "__main__":
    main()