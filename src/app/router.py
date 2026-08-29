"""Query router, SQL WHERE/ORDER BY builder, and post-SQL candidate verifier.

Splits a `ParsedQuery` (from `query_parser.py`) into "structured conditions"
(decided definitively by SQL) and "semantic residual" (handled by vector
search), and routes between three strategies:

- structured: semantic_residual is empty -> pure SQL, no embedding API call.
- semantic:   structured conditions are empty -> full vector search, as before.
- hybrid:     both present -> rank by vector similarity after the SQL filter.

Some columns (from `building_geom_meta`, alias "g", and
`building_context_meta`, alias "c") live in different tables than
`building_chunks` (alias "b"). `COLUMN_SOURCE` resolves which table a column
belongs to, and callers pass `table_aliases` (e.g. `{"b": "b.", "g": "g.",
"c": "c."}`) to build the query string with the right prefix.
"""

import pandas as pd

from src.app.query_parser import ParsedQuery

# hazard -> building_chunks risk column mapping.
HAZARD_COLUMN = {
    "ht": "ht_depth_max",
    "rv": "rv_depth_max",
    "ts": "ts_depth_max",
}

# distance_filter.target -> nearest-distance column mapping.
# station/shelter/park/emroute/landmark come from building_chunks (b);
# school/hospital/police/fire/post come from building_context_meta (c).
TARGET_COLUMN = {
    "station":  "nearest_station_dist_m",
    "shelter":  "nearest_shelter_dist_m",
    "park":     "nearest_park_dist_m",
    "emroute":  "nearest_emroute_dist_m",
    "landmark": "nearest_landmark_dist_m",
    "school":   "nearest_school_dist_m",
    "hospital": "nearest_hospital_dist_m",
    "police":   "nearest_police_dist_m",
    "fire":     "nearest_fire_dist_m",
    "post":     "nearest_post_dist_m",
}

# sort_by.key values that are risk columns (used to decide NULLS FIRST/LAST).
_DEPTH_KEYS = {"ht_depth_max", "rv_depth_max", "ts_depth_max"}

# Column name -> source table ("b" = building_chunks is the default, unlisted).
COLUMN_SOURCE = {
    "wall_ratio_n": "g", "wall_ratio_e": "g", "wall_ratio_s": "g", "wall_ratio_w": "g",
    "roof_area_m2": "g", "roof_type_est": "g", "ground_elev_m": "g",
    "volume_m3": "g", "footprint_area_m2": "g", "slenderness": "g",
    "winter_sunlit": "c", "prominence_m": "c", "wooden_density_ratio": "c",
    "nearest_major_road_dist_m": "c",
    "nearest_school_dist_m": "c", "nearest_hospital_dist_m": "c",
    "nearest_police_dist_m": "c", "nearest_fire_dist_m": "c", "nearest_post_dist_m": "c",
    # Footprint shape indicators (from building_geom_meta).
    "circularity": "g", "convexity_ratio": "g",
    "concave_vertex_count": "g", "footprint_vertex_count": "g", "shape_type_est": "g",
}

# Filter threshold constants, shared between build_filter_clauses(),
# verify_candidates(), and the gold_sql definitions in tests/gold_set.py (G23,
# G28) so evaluation and implementation never drift apart.
ORIENT_PREFER_MIN = 0.3    # Lower bound for OrientationFilter mode="prefer".
ORIENT_AVOID_MAX = 0.1     # Upper bound for OrientationFilter mode="avoid".
SUNLIGHT_WALL_S_MIN = 0.3  # South wall ratio lower bound when sunlight=true
                            # (used together with winter_sunlit). Matches gold
                            # set G23 "日当たりのよい建物" exactly. Same value as
                            # ORIENT_PREFER_MIN, but kept as a separate constant
                            # so the two concepts don't silently drift apart.
QUIET_ROAD_MIN_M = 100.0   # Major-road distance lower bound when quiet=true.
VERTICAL_EVAC_MARGIN_M = 6.0  # Required margin height for vertical_evacuation=true (matches gold set G28).
WOODEN_DENSE_MIN = 0.05    # Wooden density lower bound when wooden_dense=true (confirmed against real data).


def _resolve_alias(col: str, alias: str, table_aliases: dict[str, str] | None) -> str:
    """Resolve a column name to its table alias.

    Args:
        col: The column name.
        alias: Fallback alias used when `table_aliases` is None (backward
            compatibility for callers that only query a single table).
        table_aliases: `{"b": "b.", "g": "g.", "c": "c."}`-style mapping.

    Returns:
        The resolved alias prefix.
    """
    if table_aliases is None:
        return alias
    src = COLUMN_SOURCE.get(col, "b")
    return table_aliases.get(src, alias)


def classify_route(pq: ParsedQuery) -> str:
    """Decide which search route a parsed query should take.

    - has_structured and not has_semantic -> "structured"
    - has_semantic and not has_structured -> "semantic"
    - both present -> "hybrid"
    - neither present -> "semantic" (fallback: vector search on the raw query)

    Args:
        pq: The parsed query.

    Returns:
        One of "structured", "semantic", "hybrid".
    """
    has_structured = bool(
        pq.risk_filters
        or pq.distance_filters
        or pq.fire_proof
        or pq.height_min is not None
        or pq.usage_include
        or pq.structure_type
        or pq.sort_by is not None
        or pq.location_name
        or pq.orientation_filters
        or pq.sunlight
        or pq.quiet
        or pq.vertical_evacuation
        or pq.height_max is not None
        or pq.storeys_min is not None
        or pq.storeys_max is not None
        or pq.usage_exclude
        or pq.structure_exclude
        or pq.roof_type
        or pq.wooden_dense
        or pq.footprint_shape
    )
    has_semantic = bool(pq.semantic_residual.strip())

    if has_structured and not has_semantic:
        return "structured"
    if has_semantic and not has_structured:
        return "semantic"
    if has_structured and has_semantic:
        return "hybrid"
    return "semantic"


def build_filter_clauses(
    pq: ParsedQuery,
    alias: str = "",
    table_aliases: dict[str, str] | None = None,
) -> tuple[list[str], list]:
    """Convert a ParsedQuery's structured conditions into WHERE clause fragments.

    All values are bound via `?` placeholders — never string-interpolated —
    to avoid SQL injection and quoting issues.

    Args:
        pq: The parsed query.
        alias: Fallback table alias when `table_aliases` is None.
        table_aliases: `{"b": "b.", "g": "g.", "c": "c."}`-style mapping. When
            given, `COLUMN_SOURCE` picks the right alias for precomputed
            columns from `building_geom_meta`/`building_context_meta`. When
            None, every column uses `alias` (backward compat for callers that
            haven't joined those meta tables).

    Returns:
        A `(clauses, params)` tuple: WHERE clause fragments to AND together,
        and the corresponding `?` placeholder values in order.
    """
    clauses: list[str] = []
    params: list = []
    height_gt0_added = False

    def col_ref(name: str) -> str:
        return f"{_resolve_alias(name, alias, table_aliases)}{name}"

    # Disaster risk conditions.
    for rf in pq.risk_filters:
        col = HAZARD_COLUMN.get(rf.hazard)
        if col is None:
            continue
        ref = col_ref(col)
        if rf.mode == "none":
            clauses.append(f"{ref} IS NULL")
        elif rf.mode == "max_depth" and rf.max_depth_m is not None:
            clauses.append(f"({ref} IS NULL OR {ref} <= ?)")
            params.append(float(rf.max_depth_m))

    # Distance conditions (simple comparison against precomputed columns; no
    # spatial computation needed here).
    for df in pq.distance_filters:
        col = TARGET_COLUMN.get(df.target)
        if col is None:
            continue
        clauses.append(f"{col_ref(col)} <= ?")
        params.append(float(df.max_dist_m))

    # Fire-resistance spec.
    if pq.fire_proof:
        clauses.append(f"{col_ref('fire_proof')} = ?")
        params.append(pq.fire_proof)

    # Height lower bound (also excludes the -9999.0 sentinel invalid value).
    if pq.height_min is not None:
        clauses.append(f"{col_ref('measured_height')} > 0")
        clauses.append(f"{col_ref('measured_height')} >= ?")
        params.append(float(pq.height_min))
        height_gt0_added = True

    # Height upper bound (independent of height_min; a range naturally works
    # when both are set).
    if pq.height_max is not None:
        if not height_gt0_added:
            clauses.append(f"{col_ref('measured_height')} > 0")
            height_gt0_added = True
        clauses.append(f"{col_ref('measured_height')} <= ?")
        params.append(float(pq.height_max))

    # Sorting by height also needs the invalid-value exclusion, even when
    # neither height_min nor height_max was specified.
    if not height_gt0_added and pq.sort_by is not None and pq.sort_by.key == "measured_height":
        clauses.append(f"{col_ref('measured_height')} > 0")

    # Usage filter.
    if pq.usage_include:
        placeholders = ", ".join(["?" for _ in pq.usage_include])
        clauses.append(f"{col_ref('usage')} IN ({placeholders})")
        params.extend(pq.usage_include)

    # Structure type filter.
    if pq.structure_type:
        clauses.append(f"{col_ref('structure_type')} = ?")
        params.append(pq.structure_type)

    # Storey count range.
    if pq.storeys_min is not None:
        clauses.append(f"{col_ref('storeys')} >= ?")
        params.append(int(pq.storeys_min))
    if pq.storeys_max is not None:
        clauses.append(f"{col_ref('storeys')} <= ?")
        params.append(int(pq.storeys_max))

    # Exclusion conditions (usage / structure).
    if pq.usage_exclude:
        placeholders = ", ".join(["?" for _ in pq.usage_exclude])
        clauses.append(f"{col_ref('usage')} NOT IN ({placeholders})")
        params.extend(pq.usage_exclude)
    if pq.structure_exclude:
        placeholders = ", ".join(["?" for _ in pq.structure_exclude])
        clauses.append(f"{col_ref('structure_type')} NOT IN ({placeholders})")
        params.extend(pq.structure_exclude)

    # Wall orientation (prefer/avoid a south-facing ratio etc.).
    # "prefer" requires both "ratio >= threshold" AND "highest of the 4
    # directions" (dominant orientation). Since the 4 ratios sum to 1.0, a
    # building with 30% south / 30% north would otherwise match both "prefer
    # south" and "prefer north" under a threshold-only test; requiring
    # dominance (ties allowed) resolves that.
    _ALL_DIRS = ("n", "e", "s", "w")
    for of in pq.orientation_filters:
        col = f"wall_ratio_{of.direction}"
        ref = col_ref(col)
        if of.mode == "prefer":
            clauses.append(f"{ref} >= ?")
            params.append(ORIENT_PREFER_MIN)
            for other in _ALL_DIRS:
                if other == of.direction:
                    continue
                clauses.append(f"{ref} >= {col_ref(f'wall_ratio_{other}')}")
        elif of.mode == "avoid":
            clauses.append(f"{ref} <= ?")
            params.append(ORIENT_AVOID_MAX)

    # Sunlight (winter solstice sun reaches, factoring in south-side shading,
    # AND a minimum south wall ratio).
    if pq.sunlight:
        clauses.append(f"{col_ref('winter_sunlit')} = true")
        clauses.append(f"{col_ref('wall_ratio_s')} >= ?")
        params.append(SUNLIGHT_WALL_S_MIN)

    # Quiet (minimum distance from a major road).
    if pq.quiet:
        clauses.append(f"{col_ref('nearest_major_road_dist_m')} >= ?")
        params.append(QUIET_ROAD_MIN_M)

    # Vertical evacuation (same formula and constants as gold set G28).
    if pq.vertical_evacuation:
        clauses.append(f"{col_ref('storeys')} >= 3")
        clauses.append(f"{col_ref('measured_height')} > 0")
        clauses.append(
            f"{col_ref('measured_height')} - GREATEST("
            f"COALESCE({col_ref('ht_depth_max')},0), "
            f"COALESCE({col_ref('rv_depth_max')},0), "
            f"COALESCE({col_ref('ts_depth_max')},0)) >= ?"
        )
        params.append(VERTICAL_EVAC_MARGIN_M)

    # Roof type.
    if pq.roof_type:
        clauses.append(f"{col_ref('roof_type_est')} = ?")
        params.append(pq.roof_type)

    # Dense wooden-construction area.
    if pq.wooden_dense:
        clauses.append(f"{col_ref('wooden_density_ratio')} >= ?")
        params.append(WOODEN_DENSE_MIN)

    # Footprint shape classification (multiple classes accepted via OR).
    if pq.footprint_shape:
        placeholders = ", ".join(["?" for _ in pq.footprint_shape])
        clauses.append(f"{col_ref('shape_type_est')} IN ({placeholders})")
        params.extend(pq.footprint_shape)

    return clauses, params


def build_order_clause(
    pq: ParsedQuery,
    route: str,
    alias: str = "",
    table_aliases: dict[str, str] | None = None,
) -> str:
    """Build the ORDER BY clause.

    - `pq.sort_by` set -> explicit sort (`*_depth_max` columns flip
      NULLS FIRST/LAST depending on direction, since NULL means "no risk").
    - No sort_by, route is hybrid/semantic -> `ORDER BY score DESC`.
    - No sort_by, route is structured -> `ORDER BY {alias}id` (just to
      guarantee a deterministic order).

    Args:
        pq: The parsed query.
        route: The search route from `classify_route()`.
        alias: Fallback table alias when `table_aliases` is None.
        table_aliases: See `build_filter_clauses()`.

    Returns:
        The full `ORDER BY ...` SQL clause.
    """
    if pq.sort_by is not None:
        key = pq.sort_by.key
        order = pq.sort_by.order.upper()
        if order not in ("ASC", "DESC"):
            order = "DESC"
        if key in _DEPTH_KEYS:
            # Put NULL (no risk) first in ascending order (safest), last in
            # descending order.
            nulls = "NULLS FIRST" if order == "ASC" else "NULLS LAST"
        else:
            nulls = "NULLS LAST"
        ref = f"{_resolve_alias(key, alias, table_aliases)}{key}"
        return f"ORDER BY {ref} {order} {nulls}"

    if route in ("hybrid", "semantic"):
        return "ORDER BY score DESC"
    return f"ORDER BY {alias}id"


def verify_candidates(
    candidates: pd.DataFrame,
    pq: ParsedQuery,
) -> tuple[pd.DataFrame, list[str]]:
    """Re-evaluate `build_filter_clauses()`'s conditions in pandas, defensively.

    Rows that pass the SQL filter should never violate these conditions in
    principle, but this exists as a safety net for candidates reached via
    geocoded coordinates, or the `use_query_parser=False` backward-compat
    path (where `vector_search()` gets a default `ParsedQuery()` instead of
    the real one). Reuses the same module-level constants as
    `build_filter_clauses()` so SQL and pandas can't silently drift apart.

    Args:
        candidates: Candidate rows to verify.
        pq: The parsed query whose conditions must hold.

    Returns:
        A `(filtered_df, removed_reasons)` tuple: candidates with violations
        removed, and a human-readable reason string per removed row.
    """
    if candidates.empty:
        return candidates, []

    keep_mask = pd.Series(True, index=candidates.index)
    removed_reasons: list[str] = []

    def _mark(violation: pd.Series, reason_fmt: str, col: str) -> None:
        nonlocal keep_mask
        hit = violation.fillna(False) & keep_mask
        for idx in candidates.index[hit]:
            removed_reasons.append(
                reason_fmt.format(id=candidates.loc[idx, "id"], value=candidates.loc[idx, col])
            )
        keep_mask &= ~hit

    for rf in pq.risk_filters:
        col = HAZARD_COLUMN.get(rf.hazard)
        if col is None or col not in candidates.columns:
            continue
        if rf.mode == "none":
            violation = candidates[col].notna()
            _mark(violation, "{id}: " + col + "={value} が非NULL（リスクなし条件に違反）", col)
        elif rf.mode == "max_depth" and rf.max_depth_m is not None:
            violation = candidates[col].notna() & (candidates[col] > rf.max_depth_m)
            _mark(violation, "{id}: " + col + f"={{value}} > {rf.max_depth_m}", col)

    for dfilter in pq.distance_filters:
        col = TARGET_COLUMN.get(dfilter.target)
        if col is None or col not in candidates.columns:
            continue
        violation = candidates[col].isna() | (candidates[col] > dfilter.max_dist_m)
        _mark(violation, "{id}: " + col + f"={{value}} > {dfilter.max_dist_m}", col)

    if pq.fire_proof and "fire_proof" in candidates.columns:
        violation = candidates["fire_proof"] != pq.fire_proof
        _mark(violation, "{id}: fire_proof={value} != " + pq.fire_proof, "fire_proof")

    if pq.height_min is not None and "measured_height" in candidates.columns:
        violation = ~(candidates["measured_height"] > 0) | (candidates["measured_height"] < pq.height_min)
        _mark(violation, "{id}: measured_height={value} が height_min=" + str(pq.height_min) + " 未満", "measured_height")

    if pq.height_max is not None and "measured_height" in candidates.columns:
        violation = ~(candidates["measured_height"] > 0) | (candidates["measured_height"] > pq.height_max)
        _mark(violation, "{id}: measured_height={value} が height_max=" + str(pq.height_max) + " 超過", "measured_height")

    if pq.usage_include and "usage" in candidates.columns:
        violation = ~candidates["usage"].isin(pq.usage_include)
        _mark(violation, "{id}: usage={value} が usage_include に含まれない", "usage")

    if pq.structure_type and "structure_type" in candidates.columns:
        violation = candidates["structure_type"] != pq.structure_type
        _mark(violation, "{id}: structure_type={value} != " + pq.structure_type, "structure_type")

    if pq.storeys_min is not None and "storeys" in candidates.columns:
        violation = candidates["storeys"].isna() | (candidates["storeys"] < pq.storeys_min)
        _mark(violation, "{id}: storeys={value} が storeys_min=" + str(pq.storeys_min) + " 未満", "storeys")

    if pq.storeys_max is not None and "storeys" in candidates.columns:
        violation = candidates["storeys"].isna() | (candidates["storeys"] > pq.storeys_max)
        _mark(violation, "{id}: storeys={value} が storeys_max=" + str(pq.storeys_max) + " 超過", "storeys")

    # SQL's NOT IN also excludes NULL rows (NULL NOT IN (...) evaluates to
    # NULL, treated as false), so include isna() in the violation check here
    # too to match that semantics.
    if pq.usage_exclude and "usage" in candidates.columns:
        violation = candidates["usage"].isna() | candidates["usage"].isin(pq.usage_exclude)
        _mark(violation, "{id}: usage={value} が usage_exclude に含まれる（またはNULL）", "usage")

    if pq.structure_exclude and "structure_type" in candidates.columns:
        violation = candidates["structure_type"].isna() | candidates["structure_type"].isin(pq.structure_exclude)
        _mark(violation, "{id}: structure_type={value} が structure_exclude に含まれる（またはNULL）", "structure_type")

    for of in pq.orientation_filters:
        col = f"wall_ratio_{of.direction}"
        if col not in candidates.columns:
            continue
        if of.mode == "prefer":
            violation = candidates[col].isna() | (candidates[col] < ORIENT_PREFER_MIN)
            # Re-evaluate the "dominant orientation" requirement, matching SQL.
            for other in ("n", "e", "s", "w"):
                if other == of.direction:
                    continue
                other_col = f"wall_ratio_{other}"
                if other_col in candidates.columns:
                    violation = violation | (candidates[col] < candidates[other_col])
            _mark(violation, "{id}: " + col + f"={{value}} が prefer条件（>={ORIENT_PREFER_MIN}かつ優勢方位）に違反", col)
        elif of.mode == "avoid":
            # SQL's `<= ?` also excludes NULL rows, so include isna() here too.
            violation = candidates[col].isna() | (candidates[col] > ORIENT_AVOID_MAX)
            _mark(violation, "{id}: " + col + f"={{value}} > {ORIENT_AVOID_MAX} またはNULL（avoid条件違反）", col)

    if pq.sunlight and "winter_sunlit" in candidates.columns and "wall_ratio_s" in candidates.columns:
        violation = (~candidates["winter_sunlit"].fillna(False)) | \
            candidates["wall_ratio_s"].isna() | (candidates["wall_ratio_s"] < SUNLIGHT_WALL_S_MIN)
        _mark(violation, "{id}: winter_sunlit/wall_ratio_s が sunlight 条件を満たさない", "wall_ratio_s")

    if pq.quiet and "nearest_major_road_dist_m" in candidates.columns:
        violation = candidates["nearest_major_road_dist_m"].isna() | \
            (candidates["nearest_major_road_dist_m"] < QUIET_ROAD_MIN_M)
        _mark(violation, "{id}: nearest_major_road_dist_m={value} が quiet条件未満", "nearest_major_road_dist_m")

    if pq.vertical_evacuation and {"storeys", "measured_height"}.issubset(candidates.columns):
        depth_cols = [c for c in ("ht_depth_max", "rv_depth_max", "ts_depth_max") if c in candidates.columns]
        max_depth = candidates[depth_cols].fillna(0.0).max(axis=1) if depth_cols else 0.0
        margin = candidates["measured_height"] - max_depth
        violation = candidates["storeys"].isna() | (candidates["storeys"] < 3) | \
            ~(candidates["measured_height"] > 0) | (margin < VERTICAL_EVAC_MARGIN_M)
        _mark(violation, "{id}: 垂直避難条件（storeys>=3かつ余裕高さ>={value}）に違反", "measured_height")

    if pq.roof_type and "roof_type_est" in candidates.columns:
        violation = candidates["roof_type_est"] != pq.roof_type
        _mark(violation, "{id}: roof_type_est={value} != " + pq.roof_type, "roof_type_est")

    if pq.wooden_dense and "wooden_density_ratio" in candidates.columns:
        violation = candidates["wooden_density_ratio"].isna() | \
            (candidates["wooden_density_ratio"] < WOODEN_DENSE_MIN)
        _mark(violation, "{id}: wooden_density_ratio={value} が wooden_dense条件未満", "wooden_density_ratio")

    if pq.footprint_shape and "shape_type_est" in candidates.columns:
        violation = ~candidates["shape_type_est"].isin(pq.footprint_shape)
        _mark(violation, "{id}: shape_type_est={value} が footprint_shape=" + str(pq.footprint_shape) + " に含まれない", "shape_type_est")

    filtered = candidates[keep_mask].reset_index(drop=True)
    if removed_reasons:
        # Cap logged reasons at 10 so a full-dataset verification run (e.g.
        # an equivalence check) doesn't flood the console.
        print(f"  [verify_candidates] {len(removed_reasons)} 件の条件違反候補を除外:")
        for reason in removed_reasons[:10]:
            print(f"    - {reason}")
        if len(removed_reasons) > 10:
            print(f"    ...（他 {len(removed_reasons) - 10} 件省略）")

    return filtered, removed_reasons
