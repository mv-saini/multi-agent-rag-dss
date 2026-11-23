import geopandas as gpd
import numpy as np
from shapely import get_point, shortest_line

from core.seismic.scenario import get_fault


def scenario_layers(cells, metadata, *, fault=None):
    """Prepares the scenario layers for export from the saved snapshot."""

    bounds = cells.geometry.bounds
    data = {
        "id": cells.col.to_numpy() * metadata["grid"]["rows"]
        + cells.row.to_numpy()
        + 1,
        "left": bounds.minx.to_numpy(),
        "top": bounds.maxy.to_numpy(),
        "right": bounds.maxx.to_numpy(),
        "bottom": bounds.miny.to_numpy(),
        "row_index": cells.row.to_numpy(),
        "col_index": cells.col.to_numpy(),
        "Vs30_1": cells.Vs30_1.to_numpy(),
    }
    grid = gpd.GeoDataFrame(data, geometry=cells.geometry.to_numpy(), crs=cells.crs)
    centroids = grid.copy()
    centroids.geometry = grid.geometry.centroid
    calculated = centroids.copy()
    if fault is None:
        fault = get_fault(metadata["fault_id"])
    for name, value in fault.items():
        if name != "geometry":
            calculated[f"DISS_{name}"] = value

    calculated["DISS_rake"] = metadata["rake_used"]
    lines = shortest_line(centroids.geometry.to_numpy(), fault.geometry)
    nearest = gpd.GeoSeries(get_point(lines, -1), crs=cells.crs)
    calculated["n"] = 1
    calculated["distance"] = cells.RJB_km.to_numpy() * 1000
    calculated["feature_x"] = centroids.geometry.x
    calculated["feature_y"] = centroids.geometry.y
    calculated["nearest_x"] = nearest.x
    calculated["nearest_y"] = nearest.y
    calculated["RJB_km"] = cells.RJB_km.to_numpy()
    calculated["Mw_calc"] = metadata["magnitude"]
    value_column = metadata["value_column"]
    sigla = value_column.rsplit("_", 1)[0]
    calculated["IM_calc"] = sigla
    calculated["T_calc_s"] = (
        metadata["period_s"] if metadata["intensity_measure"] == "SA" else np.nan
    )
    for name in (
        "SoF",
        "Fm_Mw",
        "Fm_SoF",
        "R_eff_km",
        "Fd_Mw_R",
        "Fs_Vs30",
        f"log10_{sigla}",
        value_column,
        "Esito_calc",
    ):
        calculated[name] = cells[name].to_numpy()

    final = grid.copy()
    for name in calculated.columns:
        if name != "geometry":
            final[name + "_2" if name in final else name] = calculated[name].to_numpy()
    step = f"{metadata['resolution_m']:g}"
    fault_id = metadata["fault_id"]
    layers = {
        f"griglia_{step}m_vs30": grid,
        "centroidi_vs30": centroids,
        f"centroidi_RJB_{fault_id}": calculated,
        f"Griglia_{step}m_RJB_{fault_id}": final,
    }
    if metadata["intensity_measure"] == "PGA":
        layers[f"centroidi_RJB_{fault_id}_PGA"] = calculated.copy()
    return layers
