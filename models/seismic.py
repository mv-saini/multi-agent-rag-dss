from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

import config


class ScenarioDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    fault_id: str | None = None
    magnitude: float | None = None
    resolution_m: float = Field(default=config.SEISMIC_RESOLUTION_M, gt=0)
    intensity_measure: Literal["PGA", "PGV", "SA"] = config.SEISMIC_DEFAULT_IM
    period_s: float | None = Field(default=None, gt=0)
    area_mode: Literal["fault_buffer", "bbox"] = "bbox"
    buffer_km: float | None = Field(default=None, gt=0)
    bbox: tuple[float, float, float, float] | None = None
    rake: float | None = Field(default=None, ge=0, le=360)
    vs30_override: float | None = Field(default=None, gt=0)
    grid_origin_x: float = config.SEISMIC_GRID_ORIGIN_X
    grid_origin_y: float = config.SEISMIC_GRID_ORIGIN_Y

    @model_validator(mode="before")
    @classmethod
    def selected_area_parameters(cls, values):
        if not isinstance(values, dict):
            return values
        values = dict(values)
        mode = values.get("area_mode", "bbox")
        if mode != "fault_buffer":
            values["buffer_km"] = None
        elif values.get("buffer_km") is None:
            values["buffer_km"] = config.SEISMIC_BUFFER_KM
        if mode != "bbox":
            values["bbox"] = None
        return values


class SeismicScenario(ScenarioDraft):
    fault_id: str = Field(min_length=1)
    magnitude: float

    @model_validator(mode="after")
    def validate_scenario(self):
        if self.intensity_measure == "SA" and self.period_s is None:
            raise ValueError(
                "SA requires a spectral period from the coefficient table."
            )
        if self.intensity_measure != "SA":
            self.period_s = None
        if self.area_mode == "bbox":
            if self.bbox is None:
                raise ValueError("Select an area on the map.")
            west, south, east, north = self.bbox
            if not (-180 <= west < east <= 180 and -90 < south < north < 90):
                raise ValueError(
                    "Area must be a valid WGS84 west/south/east/north box."
                )
        return self


class ScenarioSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: SeismicScenario
