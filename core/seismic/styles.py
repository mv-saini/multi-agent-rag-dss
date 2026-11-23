import math
import numpy as np
import config

VS_COLORS = [
    "#d7191c",
    "#ff6201",
    "#ffcc01",
    "#fff301",
    "#ffff91",
    "#c4ff65",
    "#729f38",
    "#5a7d2c",
    "#0f5c26",
    "#5865d7",
]
SHAKING = ["#3288bd", "#abdda4", "#ffffbf", "#fdae61", "#d7191c"]
CENTROID = ["#d7191c", "#fdae61", "#ffffbf", "#abdda4", "#2b83ba"]


def ramp(position, colors):
    p = np.clip(np.asarray(position), 0, 1) * (len(colors) - 1)
    stops = np.array([[int(c[i : i + 2], 16) for i in (1, 3, 5)] for c in colors])
    lo = np.floor(p).astype(int)
    hi = np.minimum(lo + 1, len(colors) - 1)
    rgb = np.floor(
        stops[lo] + (stops[hi] - stops[lo]) * (p - lo)[..., None] + 0.5
    ).astype(int)
    return np.array(["#%02x%02x%02x" % tuple(v) for v in rgb.reshape(-1, 3)]).reshape(
        p.shape
    )


def style_spec(kind, values, field):
    valid = np.asarray(values, dtype=float)
    valid = valid[np.isfinite(valid)]
    low, high = (float(valid.min()), float(valid.max())) if len(valid) else (0.0, 0.0)
    spec = {"kind": kind, "field": field, "low": low, "high": high, "ranges": []}
    if kind == "vs30":
        bounds = [0, 180, 240, 300, 360, 420, 480, 560, 640, 760, float("inf")]
        labels = [
            "<180",
            "180–240",
            "240–300",
            "300–360",
            "360–420",
            "420–480",
            "480–560",
            "560–640",
            "640–760",
            ">760",
        ]
        spec["ranges"] = [
            (bounds[i], bounds[i + 1], VS_COLORS[i], labels[i]) for i in range(10)
        ]
    elif kind == "gray":
        spec["colors"] = ["#000000", "#ffffff"]
        spec["continuous"] = True
    else:
        step = (
            1.0
            if kind == "rjb"
            else (
                config.SEISMIC_PGA_POINT_INTERVAL
                if kind == "pga_points"
                else config.SEISMIC_PGA_RASTER_INTERVAL
            )
        )
        if not math.isfinite(step) or step <= 0:
            raise ValueError("Seismic style intervals must be finite and positive.")
        start = low if kind == "pga_points" else 0.0
        n = max(
            1,
            (
                math.ceil(round((high - start) / step, 10))
                if kind == "pga_raster"
                else math.ceil((high - start) / step)
            ),
        )
        colors = (
            ["#ffffff", "#000000"]
            if kind == "rjb"
            else CENTROID if kind == "pga_points" else SHAKING
        )
        if kind == "pga_raster" and n == 1:
            spec.update(low=0.0, colors=[colors[0], colors[-1]], continuous=True)
        else:
            palette = ramp(np.arange(n) / max(1, n - 1), colors)
            spec["ranges"] = [
                (
                    start + i * step,
                    (
                        high
                        if kind == "pga_raster" and i == n - 1
                        else start + (i + 1) * step
                    ),
                    str(palette[i]),
                    f'{start+i*step:.6g} – {(high if kind == "pga_raster" and i == n-1 else start+(i+1)*step):.6g}',
                )
                for i in range(n)
            ]
    return spec


def colorize(values, spec):
    v = np.asarray(values, dtype=float)
    valid = np.isfinite(v)
    if spec["kind"] == "vs30":
        valid &= v > 0
        idx = np.searchsorted(
            [180, 240, 300, 360, 420, 480, 560, 640, 760],
            np.nan_to_num(v),
            side="right",
        )
        idx[v == 760] = 8
    elif spec.get("continuous"):
        span = spec["high"] - spec["low"]
        colors = ramp((np.nan_to_num(v) - spec["low"]) / (span or 1), spec["colors"])
        return np.where(valid, colors, "#00000000"), np.where(
            valid, [f"{x:.6g}" for x in v], "No data"
        )
    else:
        idx = np.searchsorted(
            [r[1] for r in spec["ranges"]], np.nan_to_num(v), side="left"
        )
        idx = np.clip(idx, 0, len(spec["ranges"]) - 1)
    colors = np.array([r[2] for r in spec["ranges"]])[idx]
    labels = np.array([r[3] for r in spec["ranges"]])[idx]
    return np.where(valid, colors, "#00000000"), np.where(valid, labels, "No data")


def legend(spec):
    if spec.get("continuous"):
        return [
            {"label": f"{v:.6g}", "color": str(c)}
            for v, c in zip(
                np.linspace(spec["low"], spec["high"], 5),
                ramp(np.linspace(0, 1, 5), spec["colors"]),
            )
        ]
    return [{"label": r[3], "color": r[2]} for r in spec["ranges"]]
