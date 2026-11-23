import base64
import json
import struct
import zlib

import geopandas as gpd
import numpy as np

from core.seismic.styles import colorize, legend, style_spec
from rasterio.transform import from_origin, array_bounds
from rasterio.warp import (
    calculate_default_transform,
    reproject,
    transform,
    Resampling,
)


def raster_preview(cells, metadata, spec):
    grid = metadata["grid"]
    src = np.full((grid["rows"], grid["cols"]), np.nan, dtype="float32")
    src[cells.row.to_numpy(), cells.col.to_numpy()] = cells.motion_value.to_numpy()
    affine = from_origin(
        grid["x0"], grid["y0"], metadata["resolution_m"], metadata["resolution_m"]
    )
    bounds = array_bounds(*src.shape, affine)
    dst_transform, width, height = calculate_default_transform(
        metadata["crs"], "EPSG:3857", grid["cols"], grid["rows"], *bounds
    )
    dst = np.full((height, width), np.nan, dtype="float32")
    reproject(
        src,
        dst,
        src_transform=affine,
        src_crs=metadata["crs"],
        dst_transform=dst_transform,
        dst_crs="EPSG:3857",
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.nearest,
    )
    colors, _ = colorize(dst.ravel(), spec)
    rgba = np.array(
        [
            [int(c[i : i + 2], 16) for i in (1, 3, 5)] + [0 if len(c) == 9 else 255]
            for c in colors
        ],
        dtype="uint8",
    ).reshape(height, width, 4)

    def chunk(name, data):
        return (
            struct.pack("!I", len(data))
            + name
            + data
            + struct.pack("!I", zlib.crc32(name + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + row.tobytes() for row in rgba)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    west, south, east, north = array_bounds(height, width, dst_transform)
    x, y = transform(
        "EPSG:3857", "EPSG:4326", [west, east, east, west], [north, north, south, south]
    )
    return {
        "url": "data:image/png;base64," + base64.b64encode(png).decode(),
        "coordinates": list(map(list, zip(x, y))),
    }


def scenario_map_layers(cells, metadata, base):
    field = metadata["value_column"]
    specs = [
        ("vs30", "Vs30 · A", "Vs30_1", False, False),
        ("rjb", "RJB distance · BB", "RJB_km", True, False),
    ]
    if metadata["intensity_measure"] == "PGA":
        specs += [("pga_points", "PGA centroids · C", field, True, False)]
    specs += [
        ("gray", f"{metadata['intensity_measure']} raster · E", field, False, True)
    ]
    if metadata["intensity_measure"] == "PGA":
        specs += [("pga_raster", "PGA raster colors · EE", field, False, True)]
    result = [base]

    frame = cells[
        ["id", "Vs30_1", "RJB_km", "Mw_calc", "motion_value", "Esito_calc", "geometry"]
    ].copy()
    frame[field] = cells[field]
    frame["fault_id"] = metadata["fault_id"]
    frame["intensity_measure"] = metadata["intensity_measure"]
    frame["motion_units"] = metadata["units"]
    shared_points = None
    for kind, title, column, points, raster in specs:
        spec = style_spec(
            kind,
            cells[column].to_numpy(dtype="float32") if raster else cells[column],
            column,
        )
        layer = {
            **base,
            "layer_id": base["layer_id"] + "_" + kind,
            "layer_name": f"{title} · {metadata['fault_id']} · Mw {metadata['magnitude']:g} · {base['location_name']}",
            "view_label": title,
            "scenario_group": base["layer_id"],
            "legend": legend(spec),
            "geometry_type": "Raster" if raster else "Point" if points else "Polygon",
            "render_style": {"opacity": 1, "point_radius": 2.835, "outline_width": 0},
        }
        layer["export_view"] = kind
        if raster:
            layer["_export_style"] = spec
            layer["raster_image"] = raster_preview(cells, metadata, spec)
            layer["geojson"] = {"type": "FeatureCollection", "features": []}
        elif kind == "pga_points" and shared_points is not None:
            layer["geojson_source"] = shared_points["layer_id"]
            layer["geojson"] = {"type": "FeatureCollection", "features": []}
            layer["style_property"] = "pga_color"
            layer["label_property"] = "pga_label"
        else:
            view = frame.copy()
            if points:
                view.geometry = view.geometry.centroid
            view["risk_color"], view["risk_label"] = colorize(cells[column], spec)
            if kind == "rjb" and metadata["intensity_measure"] == "PGA":
                pga_spec = style_spec("pga_points", cells[field], field)
                view["pga_color"], view["pga_label"] = colorize(cells[field], pga_spec)
                shared_points = layer
            layer["geojson"] = json.loads(view.to_crs(4326).to_json(na="null"))
        layer["summary_metrics"] = {
            **base["summary_metrics"],
            "geometry_type": layer["geometry_type"],
        }
        result.append(layer)
    from core.seismic.snapshot import capture

    base["_export_snapshot"] = capture(cells, metadata)
    base["export_view"] = "shaking_points"
    base["scenario_group"] = base["layer_id"]
    base["layer_name"] += " · shaking points"

    # Avoid circular import
    from core.seismic.scenario import get_fault

    fault = get_fault(metadata["fault_id"])
    fault_frame = gpd.GeoDataFrame([fault.to_dict()], crs=metadata["crs"])
    fault_frame["fault_id"] = metadata["fault_id"]
    fault_frame["Mw_calc"] = metadata["magnitude"]
    fault_frame["rake_used"] = metadata["rake_used"]
    fault_frame["risk_color"] = "#b91c1c"
    fault_frame["risk_label"] = str(fault.sourcename)
    result.append(
        {
            "layer_id": base["layer_id"] + "_fault",
            "layer_name": f"Selected fault · {metadata['fault_id']} · {fault.sourcename}",
            "hazard_name": "Scenario fault",
            "location_name": base["location_name"],
            "view_label": "Fault rupture projection",
            "scenario_group": base["layer_id"],
            "scenario": metadata,
            "export_view": "fault",
            "geometry_type": "Polygon",
            "style_property": "risk_color",
            "label_property": "risk_label",
            "render_style": {
                "opacity": 0.12,
                "point_radius": 0,
                "outline_width": 2,
                "outline_color": "#b91c1c",
            },
            "geojson": json.loads(fault_frame.to_crs(4326).to_json(na="null")),
            "legend": [
                {"label": "Selected fault rupture projection", "color": "#b91c1c"}
            ],
            "feature_count": 1,
            "empty": False,
        }
    )
    return result
