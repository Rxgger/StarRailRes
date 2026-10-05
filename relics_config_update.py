#!/usr/bin/env python3
"""
Pulls relic set and relic piece data from the private-build API and adds
any relic set that's missing from this StarRailRes repo's relic_sets.json,
along with all of its 5-star pieces in relics.json.

Adds every relic set missing from the local files.

Run this from the StarRailRes repo root (same folder as index_new/).
"""

import io
import json
import os
import re
import sys
import urllib.request

from PIL import Image

from update_config import api_url, begin_tracking, finish_tracking

RELIC_SETS_URL = api_url("relic-sets.json")
RELICS_URL = api_url("relics.json")
TEXTMAPS_URL = api_url("textmaps.json")

RELIC_SETS_PATH = os.path.join("index_new", "en", "relic_sets.json")
RELICS_PATH = os.path.join("index_new", "en", "relics.json")

TARGET_RARITY = 5

RELIC_ICON_SUFFIX = {
    "HEAD": 0,
    "HAND": 1,
    "BODY": 2,
    "FOOT": 3,
    "NECK": 0,
    "OBJECT": 1,
}


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


def relic_piece_icon_path(set_id: str, relic_type: str) -> str:
    try:
        suffix = RELIC_ICON_SUFFIX[relic_type]
    except KeyError as exc:
        raise ValueError(f"Unknown relic type: {relic_type}") from exc
    return f"icon/relic/{set_id}_{suffix}.png"


def download_relic_set_images(
    api_set: dict, relics_api: dict, overwrite: bool = False
) -> None:
    set_id = str(api_set["id"])
    assets = [
        (
            "relic set icon",
            api_set.get("icon"),
            os.path.join("icon", "relic", f"{set_id}.png"),
        )
    ]

    for piece in relics_api.values():
        if str(piece["set_id"]) != set_id or piece["rarity"] != TARGET_RARITY:
            continue

        relic_type = piece["type"]
        icon_path = relic_piece_icon_path(set_id, relic_type)
        assets.append(
            (
                f"{relic_type.lower()} relic icon",
                piece.get("icon"),
                icon_path.replace("/", os.sep),
            )
        )

    if len(assets) == 1:
        raise ValueError(f"No rarity-{TARGET_RARITY} relic pieces found")

    download_png_assets(assets, overwrite=overwrite)


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
            "icon": relic_piece_icon_path(set_id, piece["type"]),
        }
    return entries



def main():
    relic_sets_api = fetch_json(RELIC_SETS_URL)
    relics_api = fetch_json(RELICS_URL)
    textmaps = fetch_json(TEXTMAPS_URL)
    textmap_en = textmaps.get("EN", {})

    relic_sets = load_json(RELIC_SETS_PATH)
    relics = load_json(RELICS_PATH)

    target_ids, discovery = begin_tracking(
        "relic_sets", relic_sets_api.keys(), relic_sets.keys()
    )
    processed_ids = []
    processed_names = []
    failures = []
    for sid in target_ids:
        if sid not in relic_sets_api:
            message = f"Tracked relic set {sid} is not present in the current API build."
            print(f"ERROR: {message}", file=sys.stderr)
            failures.append(message)
            continue

        api_set = relic_sets_api[sid]
        display_name = resolve_text(api_set["name"], textmap_en)

        try:
            download_relic_set_images(api_set, relics_api, overwrite=not discovery)
        except Exception as exc:
            message = f"Could not prepare images for {display_name} ({sid}): {exc}."
            print(f"ERROR: {message}", file=sys.stderr)
            failures.append(message)
            continue

        relic_sets[sid] = build_relic_set_entry(api_set, textmap_en)
        relics = {
            piece_id: piece
            for piece_id, piece in relics.items()
            if str(piece.get("set_id")) != sid
        }
        relics.update(build_relic_piece_entries(sid, relics_api, textmap_en))

        processed_ids.append(sid)
        processed_names.append(f"{display_name} ({sid})")

    if processed_ids:
        save_json(RELIC_SETS_PATH, relic_sets)
        save_json(RELICS_PATH, relics)

    finish_tracking(
        "relic_sets", processed_ids, discovery, completed=not failures
    )

    action = "Discovered" if discovery else "Refreshed"
    if processed_names:
        print(f"{action} {len(processed_names)} relic set(s): {', '.join(processed_names)}")
    else:
        print(f"{action} 0 relic sets.")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
