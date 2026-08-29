"""Loads PLATEAU codelist XML files into code -> Japanese label dictionaries.

Only parses the 7 XML files that `building_chunks` columns actually reference, out
of the many codelists shipped with PLATEAU CityGML data.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

# `codelist_loader.py` lives at src/pipeline/codelist_loader.py, so the repo root
# is three levels up.
CODELIST_DIR = Path(__file__).parent.parent.parent / "data" / "codelists"
_NS = {"gml": "http://www.opengis.net/gml"}

_USED_FILES = {
    "usage":          "Building_usage.xml",
    "structure_type": "BuildingDetailAttribute_buildingStructureType.xml",
    "fire_proof":     "BuildingDetailAttribute_fireproofStructureType.xml",
    "landuse_class":  "Common_landUseType.xml",
    "ht_rank":        "HighTideRiskAttribute_rank.xml",
    "rv_rank":        "RiverFloodingRiskAttribute_rank.xml",
    "ts_rank":        "TsunamiRiskAttribute_rank.xml",
}


def _load_xml(xml_name: str) -> dict[str, str]:
    """Parse one codelist XML into a code -> description dict.

    Args:
        xml_name: Filename under `CODELIST_DIR`.

    Returns:
        A dict mapping code strings to their Japanese description. Empty if the
        file doesn't exist (some codelists are optional depending on data source).
    """
    path = CODELIST_DIR / xml_name
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    return {
        d.find("gml:name", _NS).text.strip(): d.find("gml:description", _NS).text.strip()
        for d in root.findall(".//gml:Definition", _NS)
        if d.find("gml:name", _NS) is not None and d.find("gml:description", _NS) is not None
    }


class CodelistLoader:
    """Caches the 7 codelists used by `building_chunks`, loaded once at construction."""

    def __init__(self) -> None:
        self._maps: dict[str, dict[str, str]] = {
            key: _load_xml(xml_name)
            for key, xml_name in _USED_FILES.items()
        }

    # ------------------------------------------------------------------
    # Generic decode
    # ------------------------------------------------------------------

    def decode(self, map_key: str, code, default: str = "不明") -> str:
        """Look up a code in the given map and return its Japanese label.

        Args:
            map_key: Which codelist to use (a key of `_USED_FILES`).
            code: The raw code value (any type coercible to str).
            default: Returned when `code` is None.

        Returns:
            The Japanese label, or the original code string if no mapping is found
            (rather than raising, since PLATEAU data occasionally has codes not
            covered by the published codelist).
        """
        if code is None:
            return default
        code_str = str(code).strip()
        m = self._maps.get(map_key, {})
        return m.get(code_str, code_str)

    # ------------------------------------------------------------------
    # Per-attribute decoders
    # ------------------------------------------------------------------

    def decode_usage(self, usage_raw) -> str:
        """Decode a JSON-array-encoded usage field, e.g. `'["461"]'`.

        Args:
            usage_raw: The raw column value — a JSON array string, an already-
                parsed list, or None.

        Returns:
            Japanese usage labels joined by "、", or "データなし" if empty/None.
        """
        if usage_raw is None:
            return "データなし"
        try:
            codes = json.loads(usage_raw) if isinstance(usage_raw, str) else list(usage_raw)
            labels = [self.decode("usage", str(c)) for c in codes]
            return "、".join(labels) if labels else "データなし"
        except Exception:
            # Malformed JSON in source data: fall back to the raw value rather
            # than losing the row's usage info entirely.
            return str(usage_raw)

    def decode_structure(self, code) -> str:
        """Decode a building structure type code."""
        return self.decode("structure_type", code)

    def decode_fire_proof(self, code) -> str:
        """Decode a fire-resistance structure code."""
        return self.decode("fire_proof", code)

    def decode_landuse(self, code) -> str:
        """Decode a land use classification code."""
        return self.decode("landuse_class", code)

    def decode_ht_rank(self, code) -> str:
        """Decode a storm surge (高潮) risk rank code to a flood-depth range string."""
        return self.decode("ht_rank", code)

    def decode_rv_rank(self, code) -> str:
        """Decode a river flooding (洪水) risk rank code to a flood-depth range string."""
        return self.decode("rv_rank", code)

    def decode_ts_rank(self, code) -> str:
        """Decode a tsunami (津波) risk rank code to a flood-depth range string."""
        return self.decode("ts_rank", code)

    # ------------------------------------------------------------------
    # Debug summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a human-readable summary of how many entries each map loaded."""
        lines = ["CodelistLoader ロード済みマップ:"]
        for key, xml_name in _USED_FILES.items():
            n = len(self._maps.get(key, {}))
            lines.append(f"  {key:20s} ({xml_name}): {n} エントリ")
        return "\n".join(lines)
