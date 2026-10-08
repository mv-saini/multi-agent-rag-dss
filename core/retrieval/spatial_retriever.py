import hashlib
import json
import os
from functools import lru_cache
from typing import Optional
import config
import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist
from models.core import POPULATION_COLUMNS, BREAKDOWN_KEYS, RISK_COLOR_MAPS, HazardKind
import itertools


def normalize_population_gdf(pop_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return a copy with all census metrics converted to numeric values."""
    result = pop_gdf.copy()
    for column in POPULATION_COLUMNS:
        if column not in result.columns:
            result[column] = 0
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
    return result


def get_breakdown_key(stats: dict | None) -> str | None:
    """Return the breakdown key from the stats dictionary."""
    if not stats:
        return None
    return next((key for key in BREAKDOWN_KEYS if key in stats), None)


def detect_hazard_kind(gdf: gpd.GeoDataFrame) -> HazardKind:
    """Detect the hazard kind based on the geometry type and columns."""
    geometry_types = set(gdf.geom_type.unique())
    if geometry_types & {"Polygon", "MultiPolygon"}:
        return HazardKind.LANDSLIDE if "per_fr_ita" in gdf.columns else HazardKind.FLOOD
    if geometry_types & {"Point", "MultiPoint"}:
        if "field_16" in gdf.columns:
            return HazardKind.SEISMIC
        if "HI" in gdf.columns:
            return HazardKind.MULTI_HAZARD
    raise ValueError("Unable to determine hazard kind from geometry and columns.")


def summarize_population(pop_gdf: Optional[gpd.GeoDataFrame]) -> dict:
    """Summarize population metrics from the population df."""
    if pop_gdf is None or pop_gdf.empty:
        return {
            "total_population": 0,
            "total_residential_houses": 0,
            "total_residential_buildings": 0,
            "total_families": 0,
        }
    if "SEZ21_ID" in pop_gdf.columns:
        pop_gdf = pop_gdf.drop_duplicates(subset=["SEZ21_ID"])
    return {
        "total_population": int(pop_gdf["P1"].sum()),
        "total_residential_houses": int(pop_gdf["A8"].sum()),
        "total_residential_buildings": int(pop_gdf["E3"].sum()),
        "total_families": int(pop_gdf["PF1"].sum()),
    }


def generate_layer_id(location_name: str, hazard_name: str) -> str:
    """
    Generates a layer ID based on the location and hazard names.
    """
    raw = f"{location_name}_{hazard_name}".lower().replace(" ", "_")
    suffix = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"{raw}_{suffix}"


def classify_polygon_risk(row, hazard_kind: HazardKind) -> tuple[str, str]:
    """
    Classifies the risk level of a polygon hazard based on its attributes.
    """
    hi = row.get("HI")

    if hi is None:
        return "Unclassified", "#9e9e9e"

    if hazard_kind == HazardKind.LANDSLIDE:
        # landslide
        risk_map = {
            0: "Nulla",
            1: "Moderata/Attenzione",
            2: "Media",
            3: "Elevata",
            4: "Molto elevata",
        }
        color_map = RISK_COLOR_MAPS["landslide"]
    else:
        # flood
        risk_map = {
            1: "None",
            2: "Low",
            3: "Medium",
            4: "High",
        }
        color_map = RISK_COLOR_MAPS["flood"]

    label = risk_map.get(int(hi), f"Code_{hi}")
    color = color_map.get(label, "#9e9e9e")

    return label, color


def classify_seismic_risk(value: float) -> tuple[str, str]:
    """
    Classifies the seismic risk level based on the seismic acceleration value.
    """
    if value <= 0.05:
        label = "Low Risk (0.00g - 0.05g)"
    elif value <= 0.15:
        label = "Moderate Risk (0.05g - 0.15g)"
    elif value <= 0.25:
        label = "High Risk (0.15g - 0.25g)"
    elif value <= 0.35:
        label = "Very High Risk (0.25g - 0.35g)"
    else:
        label = "Extremely High Risk (>0.35g)"

    return label, RISK_COLOR_MAPS["seismic"][label]


def classify_multi_hazard_risk(value: float) -> tuple[str, str]:
    """
    Classifies the multi-hazard risk level based on the risk value.
    """
    if value <= 3:
        label = "Low Multi-Hazard (0-3)"
    elif value <= 6:
        label = "Moderate Multi-Hazard (3-6)"
    elif value <= 9:
        label = "High Multi-Hazard (6-9)"
    else:
        label = "Very High Multi-Hazard (9-12)"

    return label, RISK_COLOR_MAPS["multi_hazard"][label]


def _get_risk_classification(
    row: pd.Series, hazard_kind: HazardKind
) -> tuple[str, str]:
    """Helper to classify a row's risk label and color based on its hazard kind before geometric joins."""
    if hazard_kind in {HazardKind.FLOOD, HazardKind.LANDSLIDE}:
        return classify_polygon_risk(row, hazard_kind)
    elif hazard_kind == HazardKind.SEISMIC:
        val = pd.to_numeric(row.get("field_16"), errors="coerce")
        if pd.isna(val):
            return "Unclassified", "#9e9e9e"
        return classify_seismic_risk(float(val))
    elif hazard_kind == HazardKind.MULTI_HAZARD:
        val = pd.to_numeric(row.get("HI"), errors="coerce")
        if pd.isna(val):
            return "Unclassified", "#9e9e9e"
        return classify_multi_hazard_risk(float(val))
    return "Unclassified", "#9e9e9e"


def build_summary_metrics(stats: dict | None) -> dict:
    """Build layer-level summary metadata from the analysis."""
    if not stats:
        return {}

    summary = {
        "geometry_type": stats.get("geometry_type"),
        "total_points": stats.get("total_points"),
        "estimated_grid_resolution_meters": stats.get(
            "estimated_grid_resolution_meters"
        ),
        "max_intensity_recorded": stats.get("max_intensity_recorded"),
        "seismic_acceleration_ag": stats.get("seismic_acceleration_ag"),
    }

    return {key: value for key, value in summary.items() if value is not None}


def build_risk_breakdown(stats: dict | None) -> list[dict]:
    """Convert the stats dictionary to a risk list for frontend."""
    section_key = get_breakdown_key(stats)
    if not section_key:
        return []

    return [
        {
            "risk_label": risk_label,
            **(tier_metrics or {}),
            "has_data": bool(tier_metrics),
        }
        for risk_label, tier_metrics in (stats.get(section_key) or {}).items()
    ]


def add_feature_level_exposure(
    hazard_gdf: gpd.GeoDataFrame,
    pop_gdf: Optional[gpd.GeoDataFrame],
    hazard_kind: HazardKind,
) -> gpd.GeoDataFrame:
    """Attach census exposure to each polygon or point feature."""
    hazard = hazard_gdf.copy().reset_index(drop=True)
    hazard["feature_id"] = hazard.index

    defaults = {
        "affected_area_sqkm": 0.0,
        "exposed_population": 0,
        "exposed_residential_houses": 0,
        "exposed_residential_buildings": 0,
        "exposed_families": 0,
    }

    for column, default in defaults.items():
        hazard[column] = default

    if hazard.empty:
        return hazard

    if hazard_kind in {HazardKind.FLOOD, HazardKind.LANDSLIDE}:
        hazard["affected_area_sqkm"] = hazard.geometry.area / 1_000_000

    if pop_gdf is None or pop_gdf.empty:
        return hazard

    pop = pop_gdf.copy()

    if hazard_kind in {HazardKind.FLOOD, HazardKind.LANDSLIDE}:
        joined = gpd.sjoin(
            pop,
            hazard[["feature_id", "geometry"]],
            how="inner",
            predicate="intersects",
        )
        duplicate_columns = (
            ["feature_id", "SEZ21_ID"] if "SEZ21_ID" in joined.columns else None
        )
    else:
        pop = pop.copy()
        pop["geometry"] = pop.geometry.centroid
        joined = gpd.sjoin_nearest(
            pop,
            hazard[["feature_id", "geometry"]],
            how="inner",
            distance_col="nearest_hazard_distance_m",
        )
        duplicate_columns = ["SEZ21_ID"] if "SEZ21_ID" in joined.columns else None

    if joined.empty:
        return hazard
    if duplicate_columns:
        joined = joined.drop_duplicates(subset=duplicate_columns)

    grouped = (
        joined.groupby("feature_id")
        .agg(
            exposed_population=("P1", "sum"),
            exposed_residential_houses=("A8", "sum"),
            exposed_residential_buildings=("E3", "sum"),
            exposed_families=("PF1", "sum"),
        )
        .reset_index()
    )

    exposure_columns = list(defaults)[1:]
    hazard = hazard.drop(columns=exposure_columns, errors="ignore").merge(
        grouped, on="feature_id", how="left"
    )
    hazard[exposure_columns] = hazard[exposure_columns].fillna(0).astype(int)
    return gpd.GeoDataFrame(hazard, geometry="geometry", crs=hazard_gdf.crs)


def estimate_point_area_proxy_sqkm(
    clipped_gdf: gpd.GeoDataFrame, boundary_gdf: gpd.GeoDataFrame
) -> float:
    """
    Estimates the area represented by one point-grid feature.
    Used for seismic and multi-hazard point grids.
    """

    if clipped_gdf.empty:
        return 0.0

    boundary_area_sqkm = boundary_gdf.geometry.area.sum() / 1_000_000

    if len(clipped_gdf) > 1:
        sample = clipped_gdf.head(100)
        coords = np.array(list(zip(sample.geometry.x, sample.geometry.y)))
        distances = pdist(coords)
        valid_distances = distances[distances > 0]

        if len(valid_distances) > 0:
            min_dist = np.min(valid_distances)
        else:
            min_dist = 1000

        return float((min_dist**2) / 1_000_000)

    if len(clipped_gdf) == 1:
        return float(boundary_area_sqkm)

    return 0.0


def build_hazard_map_layer(
    clipped_gdf: gpd.GeoDataFrame,
    hazard_name: str,
    location_name: str,
    stats: dict | None = None,
    max_features: int = 1000000,
) -> dict:
    """Converts clipped hazard geometry into a GeoJSON map layer with risk classification and summary metrics."""

    if clipped_gdf is None or clipped_gdf.empty:
        return {
            "layer_id": generate_layer_id(location_name, hazard_name),
            "layer_name": f"{hazard_name} risk - {location_name}",
            "hazard_name": hazard_name,
            "location_name": location_name,
            "geometry_type": "Unknown",
            "style_property": "risk_color",
            "label_property": "risk_label",
            "geojson": None,
            "legend": [],
            "summary_metrics": build_summary_metrics(stats),
            "risk_breakdown": build_risk_breakdown(stats),
            "risk_breakdown_key": None,
            "empty": True,
            "feature_count": 0,
        }

    map_gdf = clipped_gdf.copy()

    # Need WGS84 lon/lat.
    map_gdf = map_gdf.to_crs(epsg=4326)

    legend_map = {}

    try:
        hazard_kind = detect_hazard_kind(map_gdf)
        map_geometry_type = (
            "Polygon"
            if hazard_kind in {HazardKind.FLOOD, HazardKind.LANDSLIDE}
            else "Point"
        )

        labels = []
        colors = []

        for _, row in map_gdf.iterrows():
            label, color = _get_risk_classification(row, hazard_kind)
            labels.append(label)
            colors.append(color)
            legend_map[label] = color

        map_gdf["risk_label"] = labels
        map_gdf["risk_color"] = colors
        map_gdf["map_geometry_type"] = map_geometry_type

    except ValueError:
        geom_types = set(map_gdf.geom_type.unique())
        if any(g in ["Point", "MultiPoint"] for g in geom_types):
            map_gdf["risk_label"] = "Unclassified"
            map_gdf["risk_color"] = "#9e9e9e"
            map_gdf["map_geometry_type"] = "Point"
            legend_map["Unclassified"] = "#9e9e9e"
        else:
            map_gdf["risk_label"] = "Unsupported geometry"
            map_gdf["risk_color"] = "#9e9e9e"
            map_gdf["map_geometry_type"] = "Unsupported"
            legend_map["Unsupported geometry"] = "#9e9e9e"

    keep_cols = [
        "risk_label",
        "risk_color",
        "map_geometry_type",
        "HI",
        "field_16",
        "feature_id",
        "affected_area_sqkm",
        "exposed_population",
        "exposed_residential_houses",
        "exposed_residential_buildings",
        "exposed_families",
        "percent_of_territory",
    ]

    keep_cols = [col for col in keep_cols if col in map_gdf.columns]
    map_gdf = map_gdf[keep_cols + ["geometry"]]

    if len(map_gdf) > max_features:
        map_gdf = map_gdf.head(max_features)

    geojson = json.loads(map_gdf.to_json())

    return {
        "layer_id": generate_layer_id(location_name, hazard_name),
        "layer_name": f"{hazard_name} risk - {location_name}",
        "hazard_name": hazard_name,
        "location_name": location_name,
        "geometry_type": map_gdf["map_geometry_type"].iloc[0],
        "style_property": "risk_color",
        "label_property": "risk_label",
        "geojson": geojson,
        "legend": [
            {"label": label, "color": color} for label, color in legend_map.items()
        ],
        "summary_metrics": build_summary_metrics(stats),
        "risk_breakdown": build_risk_breakdown(stats),
        "risk_breakdown_key": get_breakdown_key(stats),
        "empty": False,
        "feature_count": len(map_gdf),
    }


def filter_df(
    df: gpd.GeoDataFrame,
    level: str,
    name: str | None = None,
    id: str | int | None = None,
) -> Optional[gpd.GeoDataFrame]:
    """Filter an administrative boundary by ID or name."""
    id_columns = {"city": "PRO_COM", "province": "COD_PROV", "region": "COD_REG"}
    name_columns = {"city": "COMUNE", "province": "DEN_PROV", "region": "DEN_REG"}

    if level not in id_columns or (id is None and not name):
        return None

    if id is not None:
        match = df[df[id_columns[level]].astype(str) == str(id)]
    else:
        normalized_name = name.strip().casefold()
        match = df[
            df[name_columns[level]].astype(str).str.strip().str.casefold()
            == normalized_name
        ]

    return None if match.empty else match.copy()


@lru_cache(maxsize=3)
def _load_boundary_file(level: str) -> gpd.GeoDataFrame:
    """Returns the administrative boundary GeoDataFrame for the specified level (city, province, region)."""
    paths = {
        "city": config.CITY_ADMIN_BOUNDARY_PATH,
        "province": config.PROVINCE_ADMIN_BOUNDARY_PATH,
        "region": config.REGION_ADMIN_BOUNDARY_PATH,
    }
    return gpd.read_file(os.path.join(config.DATA_DIR, paths[level])).to_crs(epsg=32633)


def get_administrative_boundary_gdf(
    reg_id: str = None,
    reg_name: str = None,
    prov_id: str = None,
    prov_name: str = None,
    city_id: str = None,
    city_name: str = None,
) -> Optional[gpd.GeoDataFrame]:
    """Get the administrative boundary GeoDataFrame for a specific region, province, or city."""
    if city_id or city_name:
        return filter_df(_load_boundary_file("city"), "city", city_name, city_id)
    if prov_id or prov_name:
        return filter_df(
            _load_boundary_file("province"), "province", prov_name, prov_id
        )
    if reg_id or reg_name:
        return filter_df(_load_boundary_file("region"), "region", reg_name, reg_id)
    return None


@lru_cache(maxsize=32)
def _load_hazard_gdf(hazard_file: str) -> gpd.GeoDataFrame:
    """Returns the hazard GeoDataFrame."""
    return gpd.read_file(hazard_file)


def get_hazard_gdf(hazard_file: str) -> Optional[gpd.GeoDataFrame]:
    """Get the hazard GeoDataFrame."""
    try:
        # no crs conversion here. done later if needed
        return _load_hazard_gdf(hazard_file).copy()
    except Exception:
        return None


@lru_cache(maxsize=1)
def _load_population_gdf() -> gpd.GeoDataFrame:
    """Return normalized population GeoDataFrame."""
    return normalize_population_gdf(
        gpd.read_file(config.POP_GEOJSON_PATH).to_crs(epsg=32633)
    )


def get_population_gdf(
    reg_id: str = None,
    reg_name: str = None,
) -> Optional[gpd.GeoDataFrame]:
    """Get population GeoDataFrame for a specific region."""
    population = _load_population_gdf()
    return filter_df(population, level="region", name=reg_name, id=reg_id)


def analyze_hazard_file(
    boundary_gdf: gpd.GeoDataFrame,
    hazard_file: str,
    hazard_name: str,
    location_name: str,
    pop_gdf: Optional[gpd.GeoDataFrame] = None,
    include_map_layer: bool = True,
) -> dict:
    """Clip one hazard source, calculate statistics, and optionally build its map layer."""
    hazard_gdf = get_hazard_gdf(hazard_file)
    if hazard_gdf is None or hazard_gdf.empty:
        return {
            "hazard_type": hazard_name,
            "error": "Hazard file is empty or could not be loaded.",
        }

    boundary = boundary_gdf.copy()
    hazard = hazard_gdf.copy()
    if hazard.crs != boundary.crs:
        hazard = hazard.to_crs(boundary.crs)

    hazard["geometry"] = hazard.geometry.make_valid()
    boundary["geometry"] = boundary.geometry.make_valid()

    try:
        clipped_hazard = gpd.clip(hazard, boundary)
    except Exception:
        return {
            "hazard_type": hazard_name,
            "error": "Geometry conflict during clipping.",
        }

    if clipped_hazard.empty:
        result = {"hazard_type": hazard_name, "statistics": None}
        if include_map_layer:
            result["map_layer"] = build_hazard_map_layer(
                clipped_hazard, hazard_name=hazard_name, location_name=location_name
            )
        return result

    try:
        hazard_kind = detect_hazard_kind(clipped_hazard)
    except ValueError as exc:
        return {"hazard_type": hazard_name, "error": str(exc)}

    if hazard_kind in {HazardKind.FLOOD, HazardKind.LANDSLIDE}:
        stats = _analyze_polygons(clipped_hazard, boundary, pop_gdf, hazard_kind)
    else:
        stats = _analyze_points(clipped_hazard, boundary, pop_gdf, hazard_kind)

    clipped_hazard = add_feature_level_exposure(clipped_hazard, pop_gdf, hazard_kind)

    if hazard_kind in {HazardKind.SEISMIC, HazardKind.MULTI_HAZARD}:
        clipped_hazard["affected_area_sqkm"] = round(
            estimate_point_area_proxy_sqkm(clipped_hazard, boundary), 4
        )

    boundary_area_sqkm = boundary.geometry.area.sum() / 1_000_000
    clipped_hazard["percent_of_territory"] = (
        (clipped_hazard["affected_area_sqkm"] / boundary_area_sqkm * 100).round(4)
        if boundary_area_sqkm
        else 0
    )

    result = {"hazard_type": hazard_name, "statistics": stats}
    if include_map_layer:
        result["map_layer"] = build_hazard_map_layer(
            clipped_hazard, hazard_name, location_name, stats
        )

    result["_clipped_gdf"] = clipped_hazard
    result["_hazard_kind"] = hazard_kind

    return result


def _analyze_polygons(
    clipped_gdf: gpd.GeoDataFrame,
    boundary_gdf: gpd.GeoDataFrame,
    pop_gdf: Optional[gpd.GeoDataFrame],
    hazard_kind: HazardKind,
) -> dict:
    """Handles Area-based hazards (Flood, Landslide)"""

    clipped_gdf["area_sqkm"] = clipped_gdf.geometry.area / 1_000_000
    boundary_area_sqkm = boundary_gdf.geometry.area.sum() / 1_000_000

    if "HI" not in clipped_gdf.columns:
        return {
            "geometry_type": "Polygon/MultiPolygon",
            "error": "Required polygon risk field 'HI' is missing.",
        }

    intensity_stats = clipped_gdf.groupby("HI")["area_sqkm"].sum().to_dict()

    if hazard_kind == HazardKind.LANDSLIDE:
        # landslide cols
        risk_map = {
            0: "Nulla",
            1: "Moderata/Attenzione",
            2: "Media",
            3: "Elevata",
            4: "Molto elevata",
        }
    else:
        # flood cols
        risk_map = {1: "None", 2: "Low", 3: "Medium", 4: "High"}

    pop_centroid_gdf = None
    if pop_gdf is not None and not pop_gdf.empty:
        pop_centroid_gdf = pop_gdf.copy()
        pop_centroid_gdf["geometry"] = pop_centroid_gdf.geometry.centroid

        joined_centroids = gpd.sjoin(
            pop_centroid_gdf, clipped_gdf, how="inner", predicate="within"
        )

        joined_centroids = joined_centroids.drop_duplicates(subset=["SEZ21_ID"])
        joined_centroids["P1"] = gpd.pd.to_numeric(
            joined_centroids["P1"], errors="coerce"
        ).fillna(0)
        joined_centroids["A8"] = (
            gpd.pd.to_numeric(joined_centroids["A8"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
        joined_centroids["E3"] = (
            gpd.pd.to_numeric(joined_centroids["E3"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
        joined_centroids["PF1"] = (
            gpd.pd.to_numeric(joined_centroids["PF1"], errors="coerce")
            .fillna(0)
            .astype(int)
        )

    breakdown = {}
    for risk in risk_map.values():
        breakdown[risk] = {}

    for hi_code, area in intensity_stats.items():
        desc = risk_map.get(hi_code, f"Code_{hi_code}")

        if pop_centroid_gdf is not None and not joined_centroids.empty:
            joined_centroids_hi = joined_centroids[joined_centroids["HI"] == hi_code]
            tier_pop = joined_centroids_hi["P1"].sum()
            intensity_population = int(tier_pop)
            total_houses = int(joined_centroids_hi["A8"].sum())
            total_buildings = int(joined_centroids_hi["E3"].sum())
            total_families = int(joined_centroids_hi["PF1"].sum())
        else:
            intensity_population = 0
            total_houses = 0
            total_buildings = 0
            total_families = 0

        if total_buildings > 0:
            people_per_building = round(
                float(intensity_population / total_buildings), 2
            )
        else:
            people_per_building = 0.0

        if total_houses > 0:
            occupancy_rate = round(float(total_families / total_houses) * 100, 1)
        else:
            occupancy_rate = 0

        breakdown[desc] = {
            "affected_area_sqkm": round(area, 2),
            "percent_of_territory": (
                round((area / boundary_area_sqkm * 100), 1) if boundary_area_sqkm else 0
            ),
            "exposed_population": intensity_population,
            "exposed_residential_houses": total_houses,
            "exposed_residential_buildings": total_buildings,
            "exposed_families": total_families,
            "average_people_per_building": people_per_building,
            "housing_occupancy_percentage": occupancy_rate,
        }

    return {"geometry_type": "Polygon/MultiPolygon", "intensity_breakdown": breakdown}


def _aggregate_point_tiers(
    clipped_gdf: gpd.GeoDataFrame,
    joined_pop: Optional[gpd.GeoDataFrame],
    value_column: str,
    bins: list[float],
    labels: list[str],
    tier_column: str,
    point_area_proxy_sqkm: float,
    boundary_area_sqkm: float,
) -> dict[str, dict]:
    """Aggregate point grid features into discrete tiers and summarize exposure metrics."""
    values = pd.to_numeric(clipped_gdf[value_column], errors="coerce")
    categories = pd.cut(values, bins=bins, labels=labels, include_lowest=True)
    counts = categories.value_counts().to_dict()

    grouped = None
    if joined_pop is not None and not joined_pop.empty:
        population = joined_pop.copy()
        population[tier_column] = pd.cut(
            pd.to_numeric(population[value_column], errors="coerce"),
            bins=bins,
            labels=labels,
            include_lowest=True,
        )
        grouped = population.groupby(tier_column, observed=False).agg(
            exposed_population=("P1", "sum"),
            exposed_residential_houses=("A8", "sum"),
            exposed_residential_buildings=("E3", "sum"),
            exposed_families=("PF1", "sum"),
        )

    breakdown = {}
    for label in labels:
        point_count = int(counts.get(label, 0))
        if point_count <= 0:
            breakdown[label] = {}
            continue

        exposure = {
            "exposed_population": 0,
            "exposed_residential_houses": 0,
            "exposed_residential_buildings": 0,
            "exposed_families": 0,
        }
        if grouped is not None and label in grouped.index:
            exposure.update(
                {key: int(value) for key, value in grouped.loc[label].items()}
            )

        area = point_count * point_area_proxy_sqkm
        houses = exposure["exposed_residential_houses"]
        buildings = exposure["exposed_residential_buildings"]
        breakdown[label] = {
            "point_count": point_count,
            "affected_area_sqkm": round(area, 2),
            "percent_of_territory": (
                round(area / boundary_area_sqkm * 100, 1) if boundary_area_sqkm else 0
            ),
            **exposure,
            "housing_occupancy_percentage": (
                round(exposure["exposed_families"] / houses * 100, 1) if houses else 0
            ),
            "average_people_per_building": (
                round(exposure["exposed_population"] / buildings, 2)
                if buildings
                else 0.0
            ),
        }
    return breakdown


def _analyze_points(
    clipped_gdf: gpd.GeoDataFrame,
    boundary_gdf: gpd.GeoDataFrame,
    pop_gdf: Optional[gpd.GeoDataFrame],
    hazard_kind: HazardKind,
) -> dict:
    """Analyze seismic or multi-hazard point grids."""
    stats = {"geometry_type": "Point Grid", "total_points": len(clipped_gdf)}
    boundary_area_sqkm = boundary_gdf.geometry.area.sum() / 1_000_000
    point_area_proxy_sqkm = estimate_point_area_proxy_sqkm(clipped_gdf, boundary_gdf)

    if len(clipped_gdf) > 1:
        stats["estimated_grid_resolution_meters"] = round(
            (point_area_proxy_sqkm * 1_000_000) ** 0.5, 1
        )
    elif len(clipped_gdf) == 1:
        stats["estimated_grid_resolution_meters"] = (
            "Single point, using total boundary area as proxy"
        )

    joined_pop = None
    if pop_gdf is not None and not pop_gdf.empty:
        population = pop_gdf.copy()
        population["geometry"] = population.geometry.centroid
        joined_pop = gpd.sjoin_nearest(
            population, clipped_gdf, how="inner", distance_col="proximity_dist"
        )
        if "SEZ21_ID" in joined_pop.columns:
            joined_pop = joined_pop.drop_duplicates(subset=["SEZ21_ID"])

    if hazard_kind == HazardKind.SEISMIC:
        value_column = "field_16"
        numeric = pd.to_numeric(clipped_gdf[value_column], errors="coerce").dropna()
        if numeric.empty:
            return stats
        stats["seismic_acceleration_ag"] = {
            "max": round(float(numeric.max()), 3),
            "mean": round(float(numeric.mean()), 3),
            "min": round(float(numeric.min()), 3),
        }
        labels = list(RISK_COLOR_MAPS["seismic"])
        stats["seismic_discrete_zones"] = _aggregate_point_tiers(
            clipped_gdf,
            joined_pop,
            value_column,
            [0.0, 0.05, 0.15, 0.25, 0.35, float("inf")],
            labels,
            "seismic_tier",
            point_area_proxy_sqkm,
            boundary_area_sqkm,
        )
        return stats

    value_column = "HI"
    numeric = pd.to_numeric(clipped_gdf[value_column], errors="coerce").dropna()
    if numeric.empty:
        return stats
    stats["max_intensity_recorded"] = int(numeric.max())
    labels = list(RISK_COLOR_MAPS["multi_hazard"])
    stats["multi_hazard_spatial_breakdown"] = _aggregate_point_tiers(
        clipped_gdf,
        joined_pop,
        value_column,
        [0, 3, 6, 9, 12],
        labels,
        "hi_tier",
        point_area_proxy_sqkm,
        boundary_area_sqkm,
    )
    return stats


def clean_types(obj):
    """Recursively converts NumPy data types to native Python types. Avoids issues with JSON serialization."""
    if isinstance(obj, dict):
        return {k: clean_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_types(i) for i in obj]
    elif isinstance(obj, (np.floating, float)):
        return float(obj)
    elif isinstance(obj, (np.integer, int)):
        return int(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def calculate_hazard_overlaps(
    clipped_hazards: dict,
    boundary_gdf: gpd.GeoDataFrame,
    pop_gdf: Optional[gpd.GeoDataFrame],
) -> list[dict]:
    """Calculates overlapping areas and population exposure between pairs of hazards (excluding Multi-Hazard Index and No-Risk zones)."""
    overlaps = []
    boundary_area_sqkm = boundary_gdf.geometry.area.sum() / 1_000_000

    pop_centroids = None
    if pop_gdf is not None and not pop_gdf.empty:
        pop_centroids = pop_gdf.copy()
        pop_centroids["geometry"] = pop_centroids.geometry.centroid

    valid_hazards = {
        name: data
        for name, data in clipped_hazards.items()
        if data[1] in {HazardKind.FLOOD, HazardKind.LANDSLIDE, HazardKind.SEISMIC}
    }

    hazard_names = list(valid_hazards.keys())

    for name_a, name_b in itertools.combinations(hazard_names, 2):
        gdf_a, kind_a = valid_hazards[name_a]
        gdf_b, kind_b = valid_hazards[name_b]

        if gdf_a.empty or gdf_b.empty:
            continue

        gdf_a = gdf_a.copy()
        gdf_b = gdf_b.copy()
        gdf_a["temp_risk_a"] = gdf_a.apply(
            lambda r: _get_risk_classification(r, kind_a)[0], axis=1
        )
        gdf_b["temp_risk_b"] = gdf_b.apply(
            lambda r: _get_risk_classification(r, kind_b)[0], axis=1
        )

        # Filter out 'None' (Flood) and 'Nulla' (Landslide)
        if kind_a in {HazardKind.FLOOD, HazardKind.LANDSLIDE}:
            gdf_a = gdf_a[~gdf_a["temp_risk_a"].isin(["None", "Nulla"])]

        if kind_b in {HazardKind.FLOOD, HazardKind.LANDSLIDE}:
            gdf_b = gdf_b[~gdf_b["temp_risk_b"].isin(["None", "Nulla"])]

        if gdf_a.empty or gdf_b.empty:
            continue

        total_area = 0.0
        exposed_pop = 0
        exposed_bldgs = 0
        severity_breakdown = {}

        # Flood and Landslide
        if kind_a in {HazardKind.FLOOD, HazardKind.LANDSLIDE} and kind_b in {
            HazardKind.FLOOD,
            HazardKind.LANDSLIDE,
        }:
            overlap_gdf = gpd.overlay(gdf_a, gdf_b, how="intersection")
            if overlap_gdf.empty:
                continue

            overlap_gdf["area_sqkm"] = overlap_gdf.geometry.area / 1_000_000
            total_area = overlap_gdf["area_sqkm"].sum()

            if pop_centroids is not None:
                pop_in_overlap = gpd.sjoin(
                    pop_centroids, overlap_gdf, how="inner", predicate="within"
                )
                if not pop_in_overlap.empty:
                    pop_in_overlap = pop_in_overlap.drop_duplicates(subset=["SEZ21_ID"])
                    exposed_pop = int(
                        pd.to_numeric(pop_in_overlap["P1"], errors="coerce")
                        .fillna(0)
                        .sum()
                    )
                    exposed_bldgs = int(
                        pd.to_numeric(pop_in_overlap["E3"], errors="coerce")
                        .fillna(0)
                        .sum()
                    )

                    # population inside overlap
                    for _, row in pop_in_overlap.iterrows():
                        key = (
                            row.get("temp_risk_a", "Unknown"),
                            row.get("temp_risk_b", "Unknown"),
                        )
                        if key not in severity_breakdown:
                            severity_breakdown[key] = {
                                "overlap_area_sqkm": 0.0,
                                "exposed_population": 0,
                            }
                        severity_breakdown[key]["exposed_population"] += int(
                            pd.to_numeric(row.get("P1", 0))
                        )

            # consider area if population is zero
            for _, row in overlap_gdf.iterrows():
                key = (
                    row.get("temp_risk_a", "Unknown"),
                    row.get("temp_risk_b", "Unknown"),
                )
                if key not in severity_breakdown:
                    severity_breakdown[key] = {
                        "overlap_area_sqkm": 0.0,
                        "exposed_population": 0,
                    }
                severity_breakdown[key]["overlap_area_sqkm"] += row["area_sqkm"]

        # Seismic vs Flood/Landslide
        elif (
            kind_a == HazardKind.SEISMIC
            and kind_b in {HazardKind.FLOOD, HazardKind.LANDSLIDE}
        ) or (
            kind_b == HazardKind.SEISMIC
            and kind_a in {HazardKind.FLOOD, HazardKind.LANDSLIDE}
        ):

            poly_name, poly_gdf = (
                (name_a, gdf_a)
                if kind_a in {HazardKind.FLOOD, HazardKind.LANDSLIDE}
                else (name_b, gdf_b)
            )
            point_name, point_gdf = (
                (name_b, gdf_b)
                if kind_a in {HazardKind.FLOOD, HazardKind.LANDSLIDE}
                else (name_a, gdf_a)
            )

            if point_gdf.crs != poly_gdf.crs:
                poly_gdf = poly_gdf.to_crs(point_gdf.crs)

            overlap_gdf = gpd.sjoin(
                point_gdf, poly_gdf, how="inner", predicate="within"
            )
            if overlap_gdf.empty:
                continue

            proxy_area = estimate_point_area_proxy_sqkm(point_gdf, boundary_gdf)
            total_area = len(overlap_gdf) * proxy_area

            if pop_centroids is not None:
                poly_indices = overlap_gdf["index_right"].unique()
                active_polys = poly_gdf.loc[poly_indices]
                pop_in_overlap = gpd.sjoin(
                    pop_centroids, active_polys, how="inner", predicate="within"
                )

                if not pop_in_overlap.empty:
                    pop_in_overlap = pop_in_overlap.drop_duplicates(subset=["SEZ21_ID"])
                    exposed_pop = int(
                        pd.to_numeric(pop_in_overlap["P1"], errors="coerce")
                        .fillna(0)
                        .sum()
                    )
                    exposed_bldgs = int(
                        pd.to_numeric(pop_in_overlap["E3"], errors="coerce")
                        .fillna(0)
                        .sum()
                    )

            for _, row in overlap_gdf.iterrows():
                risk_a = row.get("temp_risk_a", "Unknown")
                risk_b = row.get("temp_risk_b", "Unknown")
                key = (risk_a, risk_b)

                if key not in severity_breakdown:
                    severity_breakdown[key] = {
                        "overlap_area_sqkm": 0.0,
                        "exposed_population": 0,
                    }
                severity_breakdown[key]["overlap_area_sqkm"] += proxy_area

            if exposed_pop > 0:
                for key, stats in severity_breakdown.items():
                    proportion = (
                        stats["overlap_area_sqkm"] / total_area if total_area else 0
                    )
                    stats["exposed_population"] = int(proportion * exposed_pop)

        else:
            continue

        breakdown_list = []
        for (risk_a, risk_b), stats in severity_breakdown.items():
            if stats["overlap_area_sqkm"] > 0:
                breakdown_list.append(
                    {
                        f"{name_a}_risk": risk_a,
                        f"{name_b}_risk": risk_b,
                        "overlap_area_sqkm": round(stats["overlap_area_sqkm"], 3),
                        "exposed_population": stats["exposed_population"],
                    }
                )

        overlaps.append(
            {
                "combination": f"{name_a} and {name_b}",
                "total_overlap_area_sqkm": round(total_area, 2),
                "percent_of_territory": (
                    round((total_area / boundary_area_sqkm * 100), 2)
                    if boundary_area_sqkm
                    else 0.0
                ),
                "total_exposed_population": exposed_pop,
                "total_exposed_buildings": exposed_bldgs,
                "severity_breakdown": breakdown_list,
            }
        )

    return overlaps


def run_hazard_analysis(
    target_gdf: Optional[gpd.GeoDataFrame],
    location_type: str,
    location_name: str,
    pop_gdf: Optional[gpd.GeoDataFrame],
    hazards: list,
) -> dict | None:
    if target_gdf is None or target_gdf.empty:
        return None

    hazard_metrics = []
    map_layers = []
    clipped_hazards_dict = {}

    for hazard in hazards:
        hazard_name = hazard.get("hazard_name", "Unknown hazard")
        result = analyze_hazard_file(
            boundary_gdf=target_gdf,
            hazard_file=os.path.join(
                config.DATA_DIR, hazard.get("hazard_file_path", "").lstrip("/")
            ),
            hazard_name=hazard_name,
            location_name=location_name,
            pop_gdf=pop_gdf,
            include_map_layer=True,
        )

        clipped_gdf = result.pop("_clipped_gdf", None)
        hazard_kind = result.pop("_hazard_kind", None)
        if (
            clipped_gdf is not None
            and not clipped_gdf.empty
            and hazard_kind is not None
        ):
            clipped_hazards_dict[hazard_name] = (clipped_gdf, hazard_kind)

        map_layer = result.pop("map_layer", None)
        hazard_metrics.append(result)
        if map_layer:
            map_layers.append(map_layer)

    location = {
        "name": location_name,
        "type": location_type,
        "total_area_sqkm": round(target_gdf.geometry.area.sum() / 1_000_000, 2),
        **summarize_population(pop_gdf),
    }

    hazard_overlaps = calculate_hazard_overlaps(
        clipped_hazards_dict, target_gdf, pop_gdf
    )

    return {
        "location": location,
        "hazard_metrics": hazard_metrics,
        "hazard_overlaps": hazard_overlaps,
        "map_layers": map_layers,
    }


def retrieve(spatial_contexts: list[dict]) -> list[dict]:
    """
    Retrieve hazard analysis for a list of spatial contexts, which include regions, provinces, and cities, along with their hazards.
    """

    all_analyses = []

    for context in spatial_contexts:
        hazards = context.get("hazard", [])

        for region in context.get("geographic_context", []):
            provinces = region.get("province") or []

            pop_gdf = get_population_gdf(
                reg_id=region.get("region_id"), reg_name=region.get("region_name")
            )

            if provinces:
                # If provinces are specified, analyze each province and its cities
                for prov in provinces:
                    cities = prov.get("city") or []

                    if cities:
                        # If cities are specified, analyze each city
                        for city in cities:
                            target_gdf = get_administrative_boundary_gdf(
                                city_id=city.get("city_id"),
                                city_name=city.get("city_name"),
                            )

                            pop_gdf_city = (
                                pop_gdf[
                                    pop_gdf["PRO_COM"].astype(str)
                                    == str(city.get("city_id"))
                                ]
                                if pop_gdf is not None
                                else None
                            )

                            all_analyses.append(
                                run_hazard_analysis(
                                    target_gdf,
                                    "city",
                                    city.get("city_name"),
                                    pop_gdf_city,
                                    hazards,
                                )
                            )

                    else:
                        # If no cities are specified, analyze the province directly
                        target_gdf = get_administrative_boundary_gdf(
                            prov_id=prov.get("province_id"),
                            prov_name=prov.get("province_name"),
                        )

                        pop_gdf_prov = (
                            pop_gdf[
                                pop_gdf["CODPRO"].astype(str)
                                == str(prov.get("province_id"))
                            ]
                            if pop_gdf is not None
                            else None
                        )

                        all_analyses.append(
                            run_hazard_analysis(
                                target_gdf,
                                "province",
                                prov.get("province_name"),
                                pop_gdf_prov,
                                hazards,
                            )
                        )

            else:
                # If no provinces are specified, analyze the region directly
                target_gdf = get_administrative_boundary_gdf(
                    reg_id=region.get("region_id"), reg_name=region.get("region_name")
                )

                pop_gdf_region = (
                    pop_gdf[
                        pop_gdf["COD_REG"].astype(str) == str(region.get("region_id"))
                    ]
                    if pop_gdf is not None
                    else None
                )

                all_analyses.append(
                    run_hazard_analysis(
                        target_gdf,
                        "region",
                        region.get("region_name"),
                        pop_gdf_region,
                        hazards,
                    )
                )

    valid_analyses = [analysis for analysis in all_analyses if analysis is not None]

    return clean_types(valid_analyses)
