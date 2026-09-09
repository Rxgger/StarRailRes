#!/usr/bin/env python3
"""
Pulls character data from the private-build API and adds any character
that's missing from this StarRailRes repo's characters.json,
character_promotions.json, and character_skill_trees.json.

Asks for confirmation per missing character before adding it, so the repo
doesn't get cluttered with characters you don't actually want yet.

Run this from the StarRailRes repo root (same folder as index_new/).
"""

import json
import os
import sys
import urllib.request

AVATARS_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/avatars.json"
TEXTMAPS_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/textmaps.json"

CHARACTERS_PATH = os.path.join("index_new", "en", "characters.json")
PROMOTIONS_PATH = os.path.join("index_new", "en", "character_promotions.json")
SKILL_TREES_PATH = os.path.join("index_new", "en", "character_skill_trees.json")

PROMOTION_STATS = ("hp", "atk", "def", "spd", "taunt", "crit_rate", "crit_dmg")


def fetch_json(url: str):
    print(f"Fetching {url} ...")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
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
    """Round away float32->float64 conversion noise (e.g.
    0.031999999890103936 -> 0.032) and turn whole numbers into plain ints,
    matching the existing files' formatting (96, not 96.0)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        rounded = round(float(value), 6)
        return int(rounded) if rounded == int(rounded) else rounded
    return value


def icon_path(url: str, category: str) -> str:
    """Turns a full CDN icon URL into StarRailRes's own relative path
    convention, e.g. '.../IconAttack.webp' -> 'icon/property/IconAttack.png'."""
    stem = os.path.splitext(os.path.basename(url))[0]
    return f"icon/{category}/{stem}.png"


def build_character_entry(avatar: dict) -> dict:
    return {
        "id": str(avatar["id"]),
        "name": avatar["tag"],
        "tag": avatar["tag"],
        "rarity": avatar["rarity"],
        "path": avatar["path"],
        "element": avatar["element"],
        "max_sp": clean_number(avatar["max_sp"]),
        "ranks": list(avatar["ranks"].keys()),
        "skills": list(avatar["skills"].keys()),
        "skill_trees": list(avatar["skill_trees"].keys()),
        "icon": f"icon/character/{avatar['id']}.png",
        "preview": f"image/character_preview/{avatar['id']}.png",
        "portrait": f"image/character_portrait/{avatar['id']}.png",
    }


def build_promotion_entry(avatar: dict) -> dict:
    promotions = avatar["promotions"]
    values = []
    for i in range(7):
        tier = promotions[str(i)]
        values.append(
            {
                stat: {
                    "base": clean_number(tier[stat]["base"]),
                    "step": clean_number(tier[stat]["step"]),
                }
                for stat in PROMOTION_STATS
            }
        )
    # Deliberately no "materials" key — not something this app cares about.
    return {"id": str(avatar["id"]), "values": values}


def build_skill_tree_entries(avatar: dict, textmap_en: dict) -> dict:
    entries = {}
    for tree_id, node in avatar["skill_trees"].items():
        status_add_list = node.get("status_add_list") or []

        name_key = str(node["name"])
        name = textmap_en.get(name_key, name_key)

        params = node["params"][0] if node["params"] else []

        # Combat-skill-unlock nodes have no stat bonus at all, so there's
        # nothing to put under levels/properties — but the entry itself
        # still needs to exist, since everything referencing skill tree ids
        # (characters.json's skill_trees list, calcSmallTraces, etc.) expects
        # every id to be a valid lookup key here.
        levels = (
            [
                {
                    "properties": [
                        {"type": p["type"], "value": clean_number(p["value"])}
                        for p in status_add_list
                    ]
                }
            ]
            if status_add_list
            else []
        )

        entries[tree_id] = {
            "id": tree_id,
            "name": name,
            "max_level": node["max_level"],
            "desc": "",
            "params": [clean_number(p) for p in params],
            "anchor": node["anchor"],
            "pre_points": [str(p) for p in node["pre_points"]],
            "level_up_skills": [str(s) for s in node["level_up_skills"]],
            "levels": levels,
            "icon": icon_path(node["icon"], "property"),
        }
    return entries


def confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def main():
    avatars = fetch_json(AVATARS_URL)
    textmaps = fetch_json(TEXTMAPS_URL)
    textmap_en = textmaps.get("EN", {})

    characters = load_json(CHARACTERS_PATH)
    promotions = load_json(PROMOTIONS_PATH)
    skill_trees = load_json(SKILL_TREES_PATH)

    missing_ids = [aid for aid in avatars if aid not in characters]

    if not missing_ids:
        print("No new characters found — everything in the API is already present.")
        return

    added = []
    for aid in missing_ids:
        avatar = avatars[aid]
        display_name = avatar.get("tag", aid)

        if not confirm(f"Do you wanna update with {display_name} - {aid}?"):
            print(f"Skipping {display_name} ({aid}).")
            continue

        characters[aid] = build_character_entry(avatar)
        promotions[aid] = build_promotion_entry(avatar)
        skill_trees.update(build_skill_tree_entries(avatar, textmap_en))

        added.append(f"{display_name} ({aid})")

    if not added:
        print("No characters were added.")
        return

    save_json(CHARACTERS_PATH, characters)
    save_json(PROMOTIONS_PATH, promotions)
    save_json(SKILL_TREES_PATH, skill_trees)

    print(f"Added {len(added)} character(s): {', '.join(added)}")


if __name__ == "__main__":
    main()