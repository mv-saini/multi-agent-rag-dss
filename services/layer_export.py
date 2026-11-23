import io
import json
import re
import tempfile
import warnings
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

import geopandas as gpd
import config

from core.seismic.export import scenario_layers
from core.seismic.snapshot import restore
from core.seismic.styles import colorize


def _color_style(
    frame, color_field="risk_color", label_field="risk_label", *, fault=False
):
    root = ET.Element("qgis", version="3.34", styleCategories="Symbology")
    renderer = ET.SubElement(
        root, "renderer-v2", type="categorizedSymbol", attr=color_field
    )
    categories = ET.SubElement(renderer, "categories")
    symbols = ET.SubElement(renderer, "symbols")
    points = frame.geom_type.isin(["Point", "MultiPoint"]).all()
    colors = frame[[color_field, label_field]].drop_duplicates(color_field)
    for i, (color, label) in enumerate(colors.itertuples(index=False, name=None)):
        color = str(color)
        ET.SubElement(
            categories,
            "category",
            value=color,
            type="string",
            symbol=str(i),
            label=str(label),
            render="true",
        )
        symbol = ET.SubElement(
            symbols,
            "symbol",
            name=str(i),
            type="marker" if points else "fill",
            alpha="0" if color == "#00000000" else "1",
        )
        layer = ET.SubElement(
            symbol,
            "layer",
            attrib={
                "class": "SimpleMarker" if points else "SimpleFill",
                "enabled": "1",
            },
        )
        options = ET.SubElement(layer, "Option", type="Map")
        for key, value in {
            "color": color[:7],
            "outline_style": "no",
            "name": "circle",
            "size": "1.5",
            "size_unit": "MM",
        }.items():
            ET.SubElement(options, "Option", name=key, value=value, type="QString")
        if fault:
            symbol.set("alpha", "1")
            for option in options:
                if option.get("name") == "color":
                    option.set("value", "185,28,28,31")
                if option.get("name") == "outline_style":
                    option.set("value", "solid")
            for key, value in {
                "outline_color": "#b91c1c",
                "outline_width": "0.5",
            }.items():
                ET.SubElement(options, "Option", name=key, value=value, type="QString")
    return ET.tostring(root, encoding="unicode")


def layer_frame(bundle, layer):
    """Export scenario snapshots or the saved geometry of ordinary hazard layers."""

    layers = {item["layer_id"]: item for item in bundle["map_layers"]}
    base = layers.get(layer.get("scenario_group"), layer)
    source = layers.get(layer.get("geojson_source"), layer)
    features = source.get("geojson", {}).get("features", [])
    note = "Exported saved map geometry and attributes."
    if layer.get("export_view") == "fault":
        frame = gpd.GeoDataFrame.from_features(features, crs=4326).to_crs(
            layer["scenario"]["crs"]
        )
        return (
            frame,
            "Selected fault rupture projection and its attributes saved with the scenario. Mw_calc and rake_used describe the scenario; maxmag and rake are catalogue values.",
        )
    if base.get("scenario"):
        cells, fault = restore(base["_export_snapshot"])
        meta = base["scenario"]
        frames = scenario_layers(cells, meta, fault=fault)
        kind = layer["export_view"]
        if kind == "vs30":
            frame = frames[f"griglia_{meta['resolution_m']:g}m_vs30"]
        elif kind in ("rjb", "pga_points"):
            frame = frames[f"centroidi_RJB_{meta['fault_id']}"]
        else:
            frame = frames[f"Griglia_{meta['resolution_m']:g}m_RJB_{meta['fault_id']}"]
        if kind in ("gray", "pga_raster"):
            spec = layer["_export_style"]
            frame["risk_color"], frame["risk_label"] = colorize(
                cells.motion_value.to_numpy(dtype="float32"), spec
            )
            note = "Raster view exported as original projected grid-cell polygons, not raster pixels. Numeric values and full calculation attributes are kept."
        elif features:
            display = (
                gpd.GeoDataFrame.from_features(features, crs=4326)
                .set_index("id")
                .reindex(cells.id.to_numpy())
                .to_crs(frame.crs)
            )
            if kind == "shaking_points":
                frame.geometry = display.geometry.to_numpy()
                for name in display.columns:
                    if name != "geometry" and name not in frame:
                        frame[name] = display[name].to_numpy()
            frame["risk_color"] = display[
                layer.get("style_property", "risk_color")
            ].to_numpy()
            frame["risk_label"] = display[
                layer.get("label_property", "risk_label")
            ].to_numpy()
    else:
        # Non-scenario hazard layers: GeoJSON.
        if not features:
            raise ValueError("This layer has no saved export geometry.")
        frame = gpd.GeoDataFrame.from_features(features, crs=4326)
        frame["risk_color"] = frame.get(
            layer.get("style_property", "risk_color"), "#9e9e9e"
        )
        frame["risk_label"] = frame.get(
            layer.get("label_property", "risk_label"), "Unclassified"
        )
    return frame, note


def shapefile_zip(bundle, layer_id):
    layer = next(
        (item for item in bundle["map_layers"] if item["layer_id"] == layer_id), None
    )
    if layer is None:
        raise LookupError("Layer not found in this evidence bundle.")
    frame, note = layer_frame(bundle, layer)
    if frame.empty:
        raise ValueError("This layer has no features to export.")
    geometry_types = set(frame.geom_type)
    if not (
        geometry_types <= {"Polygon", "MultiPolygon"}
        or geometry_types <= {"Point"}
        or geometry_types <= {"MultiPoint"}
        or geometry_types <= {"LineString", "MultiLineString"}
    ):
        raise ValueError(
            "This layer contains mixed geometry types that cannot be stored in one Shapefile."
        )
    name = (
        re.sub(r"[^A-Za-z0-9_-]+", "_", layer["layer_name"]).strip("_")[:100] or "layer"
    )

    for column in frame.columns:
        if column != frame.geometry.name and frame[column].dtype == object:
            frame[column] = frame[column].map(
                lambda v: (
                    json.dumps(v, ensure_ascii=False)
                    if isinstance(v, (list, dict))
                    else v
                )
            )
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory(
        prefix="layer-export-", dir=config.DATA_DIR
    ) as directory:
        path = Path(directory) / f"{name}.shp"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            frame.to_file(path, driver="ESRI Shapefile", encoding="UTF-8", index=False)
        saved = gpd.read_file(path, rows=0)
        original = [c for c in frame.columns if c != frame.geometry.name]
        stored = [c for c in saved.columns if c != saved.geometry.name]
        fields = dict(zip(original, stored, strict=True))
        if "risk_color" in frame and "risk_label" in frame:
            path.with_suffix(".qml").write_text(
                _color_style(frame, fault=layer.get("export_view") == "fault"),
                encoding="utf-8",
            )
        path.with_suffix(".fields.json").write_text(
            json.dumps(fields, indent=2), encoding="utf-8"
        )
        readme = f"{layer['layer_name']}\n\n{note}\nCRS: {frame.crs}\nFeatures: {len(frame)}\n\nExtract the ZIP and open the .shp file. Keep all companion files together.\nDBF limits column names to 10 characters; see .fields.json for the mapping.\n"
        if caught:
            readme += "\n".join(dict.fromkeys(str(w.message) for w in caught))
        path.with_suffix(".README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(Path(directory).iterdir()):
                archive.write(file, arcname=file.name)
    return name + ".zip", buffer.getvalue()
