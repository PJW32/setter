"""HTTP 요청의 형식 검증. 조건 범위와 요인 해석은 기존 엔진이 검증한다."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool

FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class MessageIn(BaseModel):
    text: str = Field(max_length=4000)


class PreferenceChangeIn(BaseModel):
    factor: str
    level: str
    evidence: str | None = None


class ParamsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: str | None = None
    house_types: list[str] | None = None
    max_area_m2: FiniteNumber | None = None
    new_contracts_only: StrictBool | None = None


class ChangesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_constraints: dict[str, FiniteNumber | None] = Field(default_factory=dict)
    clear_constraints: list[str] = Field(default_factory=list)
    params: ParamsIn = Field(default_factory=ParamsIn)
    preference_changes: list[PreferenceChangeIn] = Field(default_factory=list)


class WhatIfIn(BaseModel):
    changes: ChangesIn
