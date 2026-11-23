import json

import config
from core.seismic.scenario import available_periods, load_faults, validate_plan
from models.seismic import SeismicScenario


def catalogue(query="", include_geometry=False):
    faults = load_faults()
    if query:
        mask = faults.idsource.str.contains(
            query, case=False, regex=False
        ) | faults.sourcename.str.contains(query, case=False, regex=False)
        faults = faults.loc[mask]
    columns = ["idsource", "sourcename", "maxmag", "rake"]
    result = {
        "faults": json.loads(faults[columns].to_json(orient="records")),
        "periods": available_periods(),
        "max_cells": config.SEISMIC_MAX_CELLS,
        "defaults": {
            "resolution_m": config.SEISMIC_RESOLUTION_M,
            "buffer_km": config.SEISMIC_BUFFER_KM,
            "intensity_measure": config.SEISMIC_DEFAULT_IM,
            "period_s": config.SEISMIC_DEFAULT_PERIOD_S,
            "grid_origin_x": config.SEISMIC_GRID_ORIGIN_X,
            "grid_origin_y": config.SEISMIC_GRID_ORIGIN_Y,
        },
    }
    if include_geometry:
        result["geojson"] = json.loads(
            faults[columns + ["geometry"]].to_crs(4326).to_json()
        )
    return result



def validate_context(context):
    for item in context.get("seismic_scenarios", []):
        validate_plan(SeismicScenario.model_validate(item))
