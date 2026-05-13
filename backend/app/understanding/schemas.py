"""Pydantic schemas for tender and company profiles.

These are the canonical typed shapes produced by the LLM extractor and
consumed by the matching pipeline. JSON copies of these schemas are also
persisted in the `tender_profile` / `capabilities` JSONB columns.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TenderProfile(BaseModel):
    """Structured representation of a tender extracted by the LLM."""

    cpv_code: str
    title: str
    summary: str = ""
    buyer_country: str | None = None
    buyer_name: str | None = None
    budget_eur: float | None = None
    deadline: date | None = None
    required_certifications: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    language: str | None = None


class CompanyProfile(BaseModel):
    """Structured representation of a candidate supplier company."""

    name: str
    country: str | None = None
    website: str | None = None
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    employee_count: int | None = None
    annual_revenue_eur: float | None = None
    languages: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """Wrapper that records extraction provenance."""

    model_config = ConfigDict(protected_namespaces=())

    source_type: Literal["tender", "company"]
    source_id: str
    profile: TenderProfile | CompanyProfile
    model_used: str
    confidence: float | None = None
