from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .utils import (
    DEFAULT_MAX_BATCH_SIZE,
    MAX_STRUCTURE_BASE64_CHARS,
    normalize_sequence,
)


StructureFormat = Literal["pdb", "cif", "mmcif"]
ItemStatus = Literal["ok", "partial", "failed"]
AggregateLabel = Literal[
    "likely_binder",
    "possible_binder",
    "unlikely_binder",
    "insufficient_data",
]


class ProteinInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    sequence: str | None = Field(default=None, max_length=100_000)

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized, _warnings = normalize_sequence(value)
        return normalized


class StructureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: StructureFormat
    content_base64: str = Field(
        ...,
        min_length=1,
        max_length=MAX_STRUCTURE_BASE64_CHARS,
        description="Base64-encoded PDB or mmCIF content.",
    )
    chain_a: str | None = Field(default=None, min_length=1, max_length=8)
    chain_b: str | None = Field(default=None, min_length=1, max_length=8)

    @field_validator("format", mode="before")
    @classmethod
    def normalize_format(cls, value: str) -> str:
        return value.lower() if isinstance(value, str) else value

    @field_validator("chain_a", "chain_b")
    @classmethod
    def strip_chain_ids(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("chain identifiers cannot be blank")
        return stripped


class ScoreOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_dscript: bool = True
    run_prodigy: bool = True
    temperature_celsius: float = Field(default=25.0, ge=-273.15, le=150.0)
    fail_fast: bool = False


class ScoreItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=200)
    protein_a: ProteinInput
    protein_b: ProteinInput
    structure: StructureInput | None = None


class ScoreBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ScoreItem] = Field(
        ...,
        min_length=1,
        max_length=DEFAULT_MAX_BATCH_SIZE,
        description=f"Non-empty batch, up to {DEFAULT_MAX_BATCH_SIZE} items.",
    )
    options: ScoreOptions = Field(default_factory=ScoreOptions)

    @model_validator(mode="after")
    def item_ids_must_be_unique(self) -> "ScoreBatchRequest":
        ids = [item.id for item in self.items]
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        if duplicates:
            raise ValueError(f"item ids must be unique: {', '.join(duplicates)}")
        return self


class ProteinSummary(BaseModel):
    name: str


class DScriptScore(BaseModel):
    available: bool
    interaction_probability: float | None = None
    raw_score: float | None = None
    model_name: str = "dscript"
    warnings: list[str] = Field(default_factory=list)


class ProdigyScore(BaseModel):
    available: bool
    delta_g_kcal_per_mol: float | None = None
    kd_molar: float | None = None
    temperature_celsius: float = 25.0
    warnings: list[str] = Field(default_factory=list)


class ScoreSet(BaseModel):
    dscript: DScriptScore
    prodigy: ProdigyScore


class AggregateIndicator(BaseModel):
    available: bool
    label: AggregateLabel
    notes: str


class ScoreItemResult(BaseModel):
    id: str
    status: ItemStatus
    protein_a: ProteinSummary
    protein_b: ProteinSummary
    scores: ScoreSet
    aggregate: AggregateIndicator
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BatchSummary(BaseModel):
    submitted: int
    succeeded: int
    partial: int
    failed: int


class ScoreBatchResponse(BaseModel):
    results: list[ScoreItemResult]
    batch_summary: BatchSummary


@dataclass(frozen=True)
class SequencePair:
    item_id: str
    protein_a_name: str
    sequence_a: str | None
    protein_b_name: str
    sequence_b: str | None


@dataclass
class DScriptResult:
    available: bool
    interaction_probability: float | None = None
    raw_score: float | None = None
    model_name: str = "dscript"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def unavailable(
        cls,
        error: str,
        *,
        model_name: str = "dscript",
        warnings: list[str] | None = None,
    ) -> "DScriptResult":
        return cls(
            available=False,
            model_name=model_name,
            warnings=warnings or [],
            errors=[error],
        )


@dataclass
class ProdigyResult:
    available: bool
    delta_g_kcal_per_mol: float | None = None
    kd_molar: float | None = None
    temperature_celsius: float = 25.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def unavailable(
        cls,
        error: str,
        *,
        temperature_celsius: float = 25.0,
        warnings: list[str] | None = None,
    ) -> "ProdigyResult":
        return cls(
            available=False,
            temperature_celsius=temperature_celsius,
            warnings=warnings or [],
            errors=[error],
        )
