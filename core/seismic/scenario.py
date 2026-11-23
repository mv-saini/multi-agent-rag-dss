from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import box

import config
from core.seismic.map_layers import scenario_map_layers
from models.seismic import SeismicScenario


@lru_cache(maxsize=1)
def load_faults():
    faults = gpd.read_file(config.SEISMIC_FAULT_PATH).to_crs(config.SEISMIC_CRS)
    if faults["idsource"].duplicated().any():
        raise ValueError("Fault catalogue contains duplicate source IDs.")
    return faults


@lru_cache(maxsize=1)
def load_coefficients():
    return pd.read_csv(
        config.SEISMIC_COEFFICIENT_PATH,
        sep=";",
        decimal=",",
        skiprows=1,
        encoding="utf-8-sig",
    )


def available_periods():
    return (
        load_coefficients()["IMs"]
        .str.extract(r"SA-T=([0-9.]+)s", expand=False)
        .dropna()
        .astype(float)
        .tolist()
    )


def get_fault(fault_id):
    found = load_faults().loc[lambda frame: frame.idsource == fault_id]
    if len(found) != 1:
        raise ValueError(f"Unknown or ambiguous fault: {fault_id}")
    fault = found.iloc[0]
    if fault.geometry.is_empty or not fault.geometry.is_valid:
        raise ValueError(f"Invalid rupture projection for {fault_id}.")
    return fault


def get_coefficients(im, period=None):
    if im not in ("PGA", "PGV", "SA"):
        raise ValueError("Intensity measure must be PGA, PGV, or SA.")
    table = load_coefficients()
    if im == "SA":
        periods = (
            table["IMs"].str.extract(r"SA-T=([0-9.]+)s", expand=False).astype(float)
        )
        selected = table.loc[periods == period]
    else:
        selected = table.loc[
            table.IMs == ("pga[cm/s2]" if im == "PGA" else "pgv[cm/s]")
        ]
    if len(selected) != 1:
        raise ValueError("Intensity measure or period is not unique in Table S2.")
    return {
        name: float(selected.iloc[0][name])
        for name in (
            "a",
            "b1",
            "b2",
            "c1",
            "c2",
            "c3",
            "k",
            "f1",
            "f2",
            "Mh",
            "Mref",
            "h_[km]",
        )
    }


def calculate_motion(magnitude, rake, rjb_km, vs30, im="PGA", period=None):
    """Copy of script C; log10 is in cm/s² or cm/s, epsilon=0."""

    c = get_coefficients(im, period)
    rjb, velocity = np.broadcast_arrays(
        np.asarray(rjb_km, dtype=float), np.asarray(vs30, dtype=float)
    )
    valid = np.isfinite(rjb) & (rjb >= 0) & np.isfinite(velocity) & (velocity > 0)
    if not math.isfinite(magnitude) or not math.isfinite(rake) or not 0 <= rake <= 360:
        raise ValueError(
            "Magnitude must be finite and rake must be within 0–360 degrees."
        )
    fm = c["b1" if magnitude <= c["Mh"] else "b2"] * (magnitude - c["Mh"])
    if 0 <= rake <= 30 or 150 <= rake <= 210 or 330 <= rake <= 360:
        sof, mechanism = "SS", c["f1"]
    elif 30 < rake < 150:
        sof, mechanism = "TF", c["f2"]
    else:
        sof, mechanism = "NF", 0.0
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        effective = np.sqrt(rjb**2 + c["h_[km]"] ** 2)
        fd = (c["c1"] * (magnitude - c["Mref"]) + c["c2"]) * np.log10(effective) + c[
            "c3"
        ] * effective
        site = c["k"] * np.log10(np.minimum(velocity, 1500.0) / 800.0)
        log_y = c["a"] + fm + mechanism + fd + site
        value = 10.0**log_y / (1.0 if im == "PGV" else 980.665)
    valid &= np.isfinite(value)
    return {
        "Fm_Mw": np.full(rjb.shape, fm),
        "SoF": np.where(valid, sof, None),
        "Fm_SoF": np.where(valid, mechanism, np.nan),
        "R_eff_km": np.where(valid, effective, np.nan),
        "Fd_Mw_R": np.where(valid, fd, np.nan),
        "Fs_Vs30": np.where(valid, site, np.nan),
        "log10_motion": np.where(valid, log_y, np.nan),
        "motion_value": np.where(valid, value, np.nan),
        "Esito_calc": np.where(
            valid, "OK", "Missing/invalid Vs30, RJB, or non-finite result"
        ),
    }


def resolve_area(scenario, boundary=None):
    if boundary is not None:
        area = boundary.to_crs(config.SEISMIC_CRS).geometry.union_all()
    elif scenario.area_mode == "fault_buffer":
        area = get_fault(scenario.fault_id).geometry.buffer(scenario.buffer_km * 1000)
    else:
        area = (
            gpd.GeoSeries([box(*scenario.bbox)], crs=4326)
            .to_crs(config.SEISMIC_CRS)
            .iloc[0]
        )
    if area.is_empty or not area.is_valid or area.area <= 0:
        raise ValueError("The selected analysis area is empty or invalid.")
    return area


def grid_spec(area, scenario):
    west, south, east, north = area.bounds
    step = scenario.resolution_m

    def snap_integer(value):
        nearest = round(value)
        return (
            nearest if math.isclose(value, nearest, rel_tol=0, abs_tol=1e-9) else value
        )

    x0 = (
        scenario.grid_origin_x
        + math.floor(snap_integer((west - scenario.grid_origin_x) / step)) * step
    )
    y0 = (
        scenario.grid_origin_y
        + math.ceil(snap_integer((north - scenario.grid_origin_y) / step)) * step
    )
    cols, rows = math.ceil(snap_integer((east - x0) / step)), math.ceil(
        snap_integer((y0 - south) / step)
    )
    count = cols * rows
    if count > config.SEISMIC_MAX_CELLS:
        raise ValueError(
            f"This extent needs {count:,} grid cells (limit {config.SEISMIC_MAX_CELLS:,}). Choose a smaller area or coarser resolution."
        )
    return x0, y0, cols, rows


def validate_plan(scenario, boundary=None):
    scenario = SeismicScenario.model_validate(scenario)
    get_fault(scenario.fault_id)
    get_coefficients(scenario.intensity_measure, scenario.period_s)
    area = resolve_area(scenario, boundary)
    _, _, cols, rows = grid_spec(area, scenario)
    return {"bounding_grid_cells": cols * rows, "area_sqkm": area.area / 1e6}


def load_population_for_area(area):
    """Optional census data, spatially filtered at read time."""

    if not Path(config.POP_GEOJSON_PATH).exists():
        return None
    schema = gpd.read_file(config.POP_GEOJSON_PATH, rows=0)
    bounds = (
        gpd.GeoSeries([area], crs=config.SEISMIC_CRS).to_crs(schema.crs).total_bounds
    )
    columns = [name for name in ("SEZ21_ID", "P1", "A8", "E3", "PF1") if name in schema]
    population = gpd.read_file(
        config.POP_GEOJSON_PATH, bbox=tuple(bounds), columns=columns
    )
    for name in ("P1", "A8", "E3", "PF1"):
        if name not in population:
            population[name] = 0.0
    return population


def generate_scenario(scenario, boundary=None):
    """Return full grid cells with values, area geometry, and reproducible metadata."""

    scenario = SeismicScenario.model_validate(scenario)
    fault = get_fault(scenario.fault_id)
    area = resolve_area(scenario, boundary)
    x0, y0, cols, rows = grid_spec(area, scenario)
    step = scenario.resolution_m
    row, col = np.indices((rows, cols))
    x, y = x0 + col.ravel() * step, y0 - row.ravel() * step
    cells = gpd.GeoDataFrame(
        {"id": np.arange(rows * cols), "row": row.ravel(), "col": col.ravel()},
        geometry=box(x, y - step, x + step, y),
        crs=config.SEISMIC_CRS,
    )
    cells = cells.loc[cells.intersects(area)].copy()
    cells["affected_area_sqkm"] = cells.geometry.intersection(area).area / 1e6
    cells = cells.loc[cells.affected_area_sqkm > 0].copy()
    sites = gpd.GeoDataFrame(geometry=cells.geometry.centroid, crs=cells.crs)
    if scenario.vs30_override is not None:
        velocity = np.full(len(cells), scenario.vs30_override)
    else:
        import rasterio

        with rasterio.open(config.SEISMIC_VS30_PATH) as raster:
            sampling_sites = sites.to_crs(raster.crs)
            samples = list(
                raster.sample(
                    zip(sampling_sites.geometry.x, sampling_sites.geometry.y),
                    indexes=1,
                    masked=True,
                )
            )
            velocity = np.array(
                [
                    float(sample[0]) if not np.ma.is_masked(sample[0]) else np.nan
                    for sample in samples
                ]
            )
    cells["Vs30_1"] = velocity
    cells["RJB_km"] = sites.geometry.distance(fault.geometry).to_numpy() / 1000
    rake = scenario.rake if scenario.rake is not None else float(fault.rake)
    for key, values in calculate_motion(
        scenario.magnitude,
        rake,
        cells.RJB_km,
        velocity,
        scenario.intensity_measure,
        scenario.period_s,
    ).items():
        cells[key] = values
    sigla = (
        f"SA_{scenario.period_s:g}s".replace(".", "p")
        if scenario.intensity_measure == "SA"
        else scenario.intensity_measure
    )
    field = f"{sigla}_cms" if scenario.intensity_measure == "PGV" else f"{sigla}_g"
    cells[field] = cells.motion_value
    cells[f"log10_{sigla}"] = cells.log10_motion
    cells["DISS_rake"] = rake
    cells["Mw_calc"] = scenario.magnitude
    metadata = {
        **scenario.model_dump(mode="json"),
        "model": "Lanzano2019_RJB_Table_S2",
        "statistic": "median",
        "epsilon": 0,
        "component": "RotD50",
        "damping_percent": 5 if scenario.intensity_measure == "SA" else None,
        "units": "cm/s" if scenario.intensity_measure == "PGV" else "g",
        "value_column": field,
        "fault_name": str(fault.sourcename),
        "catalogue_maxmag": float(fault.maxmag),
        "rake_used": rake,
        "crs": str(cells.crs),
        "grid": {"x0": x0, "y0": y0, "rows": rows, "cols": cols},
        "rupture_assumption": "Entire selected source polygon is the rupture projection, including hypothetical magnitudes.",
        "extent_note": "Calculation extent only; shaking may extend beyond it.",
        "vs30_source": (
            "user override"
            if scenario.vs30_override is not None
            else Path(config.SEISMIC_VS30_PATH).name
        ),
    }
    return cells, area, metadata


def build_analysis(
    scenario, boundary=None, location_name="Selected area", population=None
):
    cells, area, metadata = generate_scenario(scenario, boundary)

    full_cells = cells.copy()
    cells.geometry = cells.geometry.intersection(area)
    valid = cells.motion_value.notna()
    values = cells.loc[valid, "motion_value"]
    stats = {
        "geometry_type": "Scenario grid",
        "total_points": len(cells),
        "estimated_grid_resolution_meters": metadata["resolution_m"],
        "valid_cells": int(valid.sum()),
        "missing_cells": int((~valid).sum()),
        "calculated_area_sqkm": float(cells.loc[valid, "affected_area_sqkm"].sum()),
        "missing_area_sqkm": float(cells.loc[~valid, "affected_area_sqkm"].sum()),
        "motion": {
            "units": metadata["units"],
            "min": float(values.min()) if len(values) else None,
            "max": float(values.max()) if len(values) else None,
            "area_weighted_mean": (
                float(
                    np.average(values, weights=cells.loc[valid, "affected_area_sqkm"])
                )
                if len(values)
                else None
            ),
        },
    }

    # Color classes describe shaking only.
    edges = (
        np.linspace(float(values.min()), float(values.max()), 6)
        if len(values)
        else np.zeros(6)
    )
    palette = ["#3288bd", "#abdda4", "#ffffbf", "#fdae61", "#d7191c"]
    labels = [f"{edges[i]:.6g}–{edges[i+1]:.6g} {metadata['units']}" for i in range(5)]
    bins = np.clip(
        np.searchsorted(edges[1:-1], cells.motion_value.fillna(0), side="left"), 0, 4
    )
    cells["risk_color"] = [
        palette[i] if ok else "#9e9e9e" for i, ok in zip(bins, valid)
    ]
    cells["risk_label"] = [labels[i] if ok else "No data" for i, ok in zip(bins, valid)]
    exposure_columns = {
        "P1": "exposed_population",
        "A8": "exposed_residential_houses",
        "E3": "exposed_residential_buildings",
        "PF1": "exposed_families",
    }
    stats["exposure_method"] = (
        "Census centroid assigned only to its containing valid scenario cell; no nearest-cell extrapolation."
    )
    stats["exposure_available"] = population is not None
    if population is not None:
        pop = population.to_crs(cells.crs).copy()
        pop.geometry = pop.geometry.centroid
        if "SEZ21_ID" in pop:
            pop = pop.drop_duplicates("SEZ21_ID")
        pop = pop.loc[pop.geometry.intersects(area)].reset_index(drop=True)
        pop["_population_id"] = pop.index
        joined = gpd.sjoin(
            pop,
            cells[["id", "geometry", "motion_value"]],
            how="left",
            predicate="intersects",
        )
        joined = joined.sort_values("id").drop_duplicates("_population_id")
        covered = joined.motion_value.notna()
        stats["population_with_valid_shaking"] = float(
            pd.to_numeric(joined.loc[covered, "P1"], errors="coerce").sum()
        )
        stats["population_without_valid_shaking"] = float(
            pd.to_numeric(joined.loc[~covered, "P1"], errors="coerce").sum()
        )
        for source, dest in exposure_columns.items():
            joined[source] = pd.to_numeric(joined[source], errors="coerce").fillna(0)
            grouped = joined.loc[covered].groupby("id")[source].sum()
            cells[dest] = cells.id.map(grouped).fillna(0)
    cells["intensity_measure"] = metadata["intensity_measure"]
    cells["motion_units"] = metadata["units"]
    cells["fault_id"] = metadata["fault_id"]
    cells["percent_of_territory"] = cells.affected_area_sqkm / (area.area / 1e6) * 100
    identity = json.dumps(metadata, sort_keys=True) + area.wkb_hex
    layer_id = "scenario_" + hashlib.sha256(identity.encode()).hexdigest()[:16]
    title = f"Scenario {metadata['intensity_measure']} · {metadata['fault_id']} · Mw {metadata['magnitude']:g} · {location_name}"
    legend = [
        {"label": label, "color": color}
        for label, color in cells.loc[valid, ["risk_label", "risk_color"]]
        .drop_duplicates()
        .sort_values("risk_label")
        .itertuples(index=False, name=None)
    ]
    if (~valid).any():
        legend.append({"label": "No data", "color": "#9e9e9e"})
    map_columns = [
        "id",
        "motion_value",
        "motion_units",
        "intensity_measure",
        "fault_id",
        "Mw_calc",
        "Vs30_1",
        "RJB_km",
        "Esito_calc",
        "affected_area_sqkm",
        "percent_of_territory",
        "risk_color",
        "risk_label",
        "geometry",
    ]
    map_columns += [name for name in exposure_columns.values() if name in cells]
    map_points = cells[map_columns].copy()
    map_points.geometry = full_cells.geometry.centroid
    layer = {
        "layer_id": layer_id,
        "layer_name": title,
        "hazard_name": "Seismic scenario",
        "location_name": location_name,
        "geometry_type": "Point",
        "render_style": {"opacity": 1, "point_radius": 2.835, "outline_width": 0},
        "style_property": "risk_color",
        "label_property": "risk_label",
        "geojson": json.loads(map_points.to_crs(4326).to_json(na="null")),
        "legend": legend,
        "feature_count": len(cells),
        "empty": cells.empty,
        "scenario": metadata,
        "summary_metrics": {
            "geometry_type": "Point",
            "total_points": len(cells),
            "estimated_grid_resolution_meters": metadata["resolution_m"],
        },
    }
    return {
        "location": {
            "name": location_name,
            "type": metadata["area_mode"],
            "total_area_sqkm": area.area / 1e6,
        },
        "hazard_metrics": [
            {
                "hazard_type": "Seismic scenario",
                "scenario": metadata,
                "statistics": stats,
            }
        ],
        "hazard_overlaps": [],
        "map_layers": scenario_map_layers(full_cells, metadata, layer),
    }
