#!/usr/bin/env python3
"""
Pulls light cone data from the private-build API and adds any light cone
that's missing from this StarRailRes repo's light_cones.json,
light_cone_promotions.json, and light_cone_ranks.json.

Adds every light cone missing from the local files.

Run this from the StarRailRes repo root (same folder as index_new/).
"""

import io
import json
import os
import sys
import urllib.request

from PIL import Image

from update_config import api_url, begin_tracking, finish_tracking

LIGHTCONES_URL = api_url("lightcones.json")
TEXTMAPS_URL = api_url("textmaps.json")

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


def download_light_cone_images(light_cone: dict, overwrite: bool = False) -> None:
    light_cone_id = str(light_cone["id"])
    download_png_assets(
        [
            (
                "light cone icon",
                light_cone.get("icon"),
                os.path.join("icon", "light_cone", f"{light_cone_id}.png"),
            ),
            (
                "light cone preview",
                light_cone.get("preview"),
                os.path.join("image", "light_cone_preview", f"{light_cone_id}.png"),
            ),
            (
                "light cone portrait",
                light_cone.get("portrait"),
                os.path.join("image", "light_cone_portrait", f"{light_cone_id}.png"),
            ),
        ],
        overwrite=overwrite,
    )


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



def main():
    light_cones_api = fetch_json(LIGHTCONES_URL)
    textmaps = fetch_json(TEXTMAPS_URL)
    textmap_en = textmaps.get("EN", {})

    light_cones = load_json(LIGHT_CONES_PATH)
    promotions = load_json(PROMOTIONS_PATH)
    ranks = load_json(RANKS_PATH)

    target_ids, discovery = begin_tracking(
        "light_cones", light_cones_api.keys(), light_cones.keys()
    )
    processed_ids = []
    processed_names = []
    failures = []
    for lcid in target_ids:
        if lcid not in light_cones_api:
            message = f"Tracked light cone {lcid} is not present in the current API build."
            print(f"ERROR: {message}", file=sys.stderr)
            failures.append(message)
            continue

        lc = light_cones_api[lcid]
        display_name = resolve_text(lc["name"], textmap_en)

        try:
            download_light_cone_images(lc, overwrite=not discovery)
        except Exception as exc:
            message = f"Could not prepare images for {display_name} ({lcid}): {exc}."
            print(f"ERROR: {message}", file=sys.stderr)
            failures.append(message)
            continue

        light_cones[lcid] = build_light_cone_entry(lc, textmap_en)
        promotions[lcid] = build_promotion_entry(lc)
        ranks[lcid] = build_rank_entry(lc, textmap_en)

        processed_ids.append(lcid)
        processed_names.append(f"{display_name} ({lcid})")

    if processed_ids:
        save_json(LIGHT_CONES_PATH, light_cones)
        save_json(PROMOTIONS_PATH, promotions)
        save_json(RANKS_PATH, ranks)

    finish_tracking(
        "light_cones", processed_ids, discovery, completed=not failures
    )

    action = "Discovered" if discovery else "Refreshed"
    if processed_names:
        print(f"{action} {len(processed_names)} light cone(s): {', '.join(processed_names)}")
    else:
        print(f"{action} 0 light cones.")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
