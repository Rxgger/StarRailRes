#!/usr/bin/env python3
"""
Pulls character data from the private-build API and adds any character
that's missing from this StarRailRes repo's characters.json,
character_promotions.json, and character_skill_trees.json.

Adds every character missing from the local files.

Run this from the StarRailRes repo root (same folder as index_new/).
"""

import io
import json
import os
import sys
import urllib.request

from PIL import Image

from update_config import api_url, begin_tracking, finish_tracking

AVATARS_URL = api_url("avatars.json")
TEXTMAPS_URL = api_url("textmaps.json")

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


def download_png_assets(assets: list[tuple[str, str, str]], overwrite: bool = False) -> None:
    """Download CDN images, convert them to real PNG files, and only write
    them after every required download/conversion has succeeded."""
    png_by_url: dict[str, bytes] = {}
    prepared: list[tuple[str, bytes]] = []

    for label, url, destination in assets:
        if os.path.exists(destination) and not overwrite:
            print(f"Keeping existing {label}: {destination}")
            continue

        if not url:
            raise ValueError(f"Missing CDN URL for {label}")

        if url not in png_by_url:
            print(f"Downloading {label}: {url}")
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req) as response:
                source_bytes = response.read()

            with Image.open(io.BytesIO(source_bytes)) as image:
                output = io.BytesIO()
                image.convert("RGBA").save(output, format="PNG", optimize=True)
                png_by_url[url] = output.getvalue()

        prepared.append((destination, png_by_url[url]))

    for destination, png_bytes in prepared:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        temporary_path = f"{destination}.tmp"
        try:
            with open(temporary_path, "wb") as image_file:
                image_file.write(png_bytes)
            os.replace(temporary_path, destination)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)


def download_character_images(avatar: dict, overwrite: bool = False) -> None:
    character_id = str(avatar["id"])
    download_png_assets(
        [
            ("character icon", avatar.get("icon"), os.path.join("icon", "avatar", f"{character_id}.png")),
            (
                "character preview",
                avatar.get("preview"),
                os.path.join("image", "character_preview", f"{character_id}.png"),
            ),
            (
                "character portrait",
                avatar.get("portrait"),
                os.path.join("image", "character_portrait", f"{character_id}.png"),
            ),
        ],
        overwrite=overwrite,
    )


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



def main():
    avatars = fetch_json(AVATARS_URL)
    textmaps = fetch_json(TEXTMAPS_URL)
    textmap_en = textmaps.get("EN", {})

    characters = load_json(CHARACTERS_PATH)
    promotions = load_json(PROMOTIONS_PATH)
    skill_trees = load_json(SKILL_TREES_PATH)

    target_ids, discovery = begin_tracking("characters", avatars.keys(), characters.keys())
    processed_ids = []
    processed_names = []
    failures = []
    for aid in target_ids:
        if aid not in avatars:
            message = f"Tracked character {aid} is not present in the current API build."
            print(f"ERROR: {message}", file=sys.stderr)
            failures.append(message)
            continue

        avatar = avatars[aid]
        display_name = avatar.get("tag", aid)

        try:
            download_character_images(avatar, overwrite=not discovery)
        except Exception as exc:
            message = f"Could not prepare images for {display_name} ({aid}): {exc}."
            print(f"ERROR: {message}", file=sys.stderr)
            failures.append(message)
            continue

        old_character = characters.get(aid, {})
        for tree_id in old_character.get("skill_trees", []):
            skill_trees.pop(str(tree_id), None)
        characters[aid] = build_character_entry(avatar)
        promotions[aid] = build_promotion_entry(avatar)
        skill_trees.update(build_skill_tree_entries(avatar, textmap_en))

        processed_ids.append(aid)
        processed_names.append(f"{display_name} ({aid})")

    if processed_ids:
        save_json(CHARACTERS_PATH, characters)
        save_json(PROMOTIONS_PATH, promotions)
        save_json(SKILL_TREES_PATH, skill_trees)

    finish_tracking(
        "characters", processed_ids, discovery, completed=not failures
    )

    action = "Discovered" if discovery else "Refreshed"
    if processed_names:
        print(f"{action} {len(processed_names)} character(s): {', '.join(processed_names)}")
    else:
        print(f"{action} 0 characters.")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
