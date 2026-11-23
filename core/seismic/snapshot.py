import base64
import gzip
import json

import geopandas as gpd
from shapely.geometry import mapping, shape
import pandas as pd

from core.seismic.scenario import get_fault


def capture(cells, metadata):
    fault = get_fault(metadata["fault_id"])
    payload = {
        "cells": json.loads(cells.to_json(na="null")),
        "crs": str(cells.crs),
        "numeric_columns": cells.select_dtypes(include="number").columns.tolist(),
        "fault": json.loads(
            fault.drop(labels=["geometry"]).to_json(double_precision=15)
        ),
        "fault_geometry": mapping(fault.geometry),
    }
    return base64.b64encode(
        gzip.compress(json.dumps(payload, allow_nan=False).encode(), mtime=0)
    ).decode("ascii")


def restore(snapshot):
    payload = json.loads(gzip.decompress(base64.b64decode(snapshot, validate=True)))
    cells = gpd.GeoDataFrame.from_features(
        payload["cells"]["features"], crs=payload["crs"]
    )
    for column in payload.get("numeric_columns", []):
        cells[column] = pd.to_numeric(cells[column], errors="raise")
    fault = pd.Series(
        {**payload["fault"], "geometry": shape(payload["fault_geometry"])}
    )
    return cells, fault
