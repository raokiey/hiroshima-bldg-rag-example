"""Resolves a place name (station, landmark, ...) to WGS84 coordinates.

Lookup order:
  1. Internal station.geojson (key: station name) — exact match, then partial.
  2. Internal landmark.geojson (key: name) — exact match, then partial.
  3. Nominatim API fallback (via urllib.request, no extra dependency).
  4. None (logged; caller continues without a spatial filter).

GeoJSON sources are cached at module level and loaded only once.
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# `geocoder.py` lives at src/app/geocoder.py, so the repo root is three
# levels up.
ROOT = Path(__file__).parent.parent.parent

# GeoJSON file paths.
_STATION_PATH = ROOT / "data" / "related" / "34100_hiroshima-shi_city_2022_station.geojson"
_LANDMARK_PATH = ROOT / "data" / "related" / "34100_hiroshima-shi_city_2022_landmark.geojson"

# Module-level cache, populated on first use.
_station_cache: list[dict] | None = None
_landmark_cache: list[dict] | None = None


def _load_station_cache() -> list[dict]:
    """Load station.geojson into a list of {name, lon, lat, line} dicts."""
    global _station_cache
    if _station_cache is not None:
        return _station_cache

    if not _STATION_PATH.exists():
        print(f"  [WARN] station.geojson が見つかりません: {_STATION_PATH}")
        _station_cache = []
        return _station_cache

    with open(_STATION_PATH, encoding="utf-8") as f:
        data = json.load(f)

    cache = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])
        name = props.get("駅名", "")
        if name and len(coords) >= 2:
            cache.append({
                "name": name,
                "lon": float(coords[0]),
                "lat": float(coords[1]),
                "line": props.get("路線名", ""),
            })

    _station_cache = cache
    return _station_cache


def _load_landmark_cache() -> list[dict]:
    """Load landmark.geojson into a list of {name, lon, lat, type} dicts."""
    global _landmark_cache
    if _landmark_cache is not None:
        return _landmark_cache

    if not _LANDMARK_PATH.exists():
        print(f"  [WARN] landmark.geojson が見つかりません: {_LANDMARK_PATH}")
        _landmark_cache = []
        return _landmark_cache

    with open(_LANDMARK_PATH, encoding="utf-8") as f:
        data = json.load(f)

    cache = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])
        name = props.get("名称", "")
        if name and len(coords) >= 2:
            cache.append({
                "name": name,
                "lon": float(coords[0]),
                "lat": float(coords[1]),
                "type": props.get("種類", ""),
            })

    _landmark_cache = cache
    return _landmark_cache


def _search_internal(
    name: str,
    entries: list[dict],
) -> Optional[tuple[float, float]]:
    """Search a cached entry list, exact match first, then substring match.

    Args:
        name: The query place name.
        entries: A cache list from `_load_station_cache()` or
            `_load_landmark_cache()`.

    Returns:
        `(lon, lat)` if found, else None.
    """
    # Exact match (case/width-sensitive).
    for e in entries:
        if e["name"] == name:
            return (e["lon"], e["lat"])

    # Substring match: name contains the entry's name, or vice versa.
    for e in entries:
        if name in e["name"] or e["name"] in name:
            return (e["lon"], e["lat"])

    return None


def _nominatim_geocode(name: str) -> Optional[tuple[float, float]]:
    """Geocode a place name via the Nominatim API.

    Uses `urllib.request` (no extra dependency). Nominatim's usage policy
    requires a `User-Agent` header. Times out after 5 seconds.

    Args:
        name: The place name to geocode.

    Returns:
        `(lon, lat)`, or None on any failure (network, parse, no results).
    """
    try:
        params = urllib.parse.urlencode({
            "q": f"{name} 広島市",
            "format": "json",
            "limit": "1",
            "countrycodes": "jp",
        })
        url = f"https://nominatim.openstreetmap.org/search?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "PLATEAU-RAG/1.0 (geospatial-city-rag)"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            results = json.loads(resp.read().decode("utf-8"))

        if results:
            lon = float(results[0]["lon"])
            lat = float(results[0]["lat"])
            return (lon, lat)

    except Exception as exc:
        print(f"  [WARN] Nominatim ジオコーディング失敗 ({name}): {exc}")

    return None


def geocode(name: str) -> Optional[tuple[float, float]]:
    """Resolve a place name to WGS84 coordinates, trying each source in order.

    Lookup order: internal station.geojson -> internal landmark.geojson ->
    Nominatim API -> None (caller continues without a spatial filter).

    Args:
        name: The place name to geocode.

    Returns:
        `(lon, lat)`, or None if no source could resolve it.
    """
    if not name:
        return None

    # 1. Internal station cache.
    stations = _load_station_cache()
    result = _search_internal(name, stations)
    if result is not None:
        print(f"  [GEOCODE] '{name}' → station キャッシュ: lon={result[0]:.4f}, lat={result[1]:.4f}")
        return result

    # 2. Internal landmark cache.
    landmarks = _load_landmark_cache()
    result = _search_internal(name, landmarks)
    if result is not None:
        print(f"  [GEOCODE] '{name}' → landmark キャッシュ: lon={result[0]:.4f}, lat={result[1]:.4f}")
        return result

    # 3. Nominatim API.
    print(f"  [GEOCODE] '{name}' → Nominatim API で検索中...")
    result = _nominatim_geocode(name)
    if result is not None:
        print(f"  [GEOCODE] '{name}' → Nominatim: lon={result[0]:.4f}, lat={result[1]:.4f}")
        return result

    # 4. Unresolvable.
    print(f"  [GEOCODE] '{name}' → 解決不能 — 空間フィルタなしで継続")
    return None


if __name__ == "__main__":
    # Manual smoke test.
    test_names = ["広島駅", "平和記念公園", "広島城", "宮島", "女学院前駅"]
    for n in test_names:
        r = geocode(n)
        if r:
            print(f"  '{n}' → lon={r[0]:.4f}, lat={r[1]:.4f}")
        else:
            print(f"  '{n}' → None（未解決）")
