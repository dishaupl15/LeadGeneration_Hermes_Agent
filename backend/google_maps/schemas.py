"""
google_maps/schemas.py
───────────────────────
Pydantic request/response models for the Google Maps module.

Completely independent of src/schemas/lead_schema.py.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ── Request ───────────────────────────────────────────────────────────────────

class MapLeadsRequest(BaseModel):
    """POST /maps-leads/generate — what to search and where."""

    category: str = Field(
        ...,
        min_length=1,
        max_length=100,
        example="construction",
        description="Business category (e.g. 'construction', 'IT', 'pharma')",
    )
    state: str = Field(
        ...,
        min_length=1,
        max_length=100,
        example="Maharashtra",
        description="Indian state name",
    )
    district: Optional[str] = Field(
        default=None,
        max_length=100,
        example="Pune",
        description="District/city (omit to search the entire state)",
    )
    target: int = Field(
        default=50,
        ge=1,
        le=500,
        example=50,
        description="Target number of unique businesses (1–500)",
    )
    exclude_seen: bool = Field(
        default=True,
        description=(
            "If true, skip place_ids already returned in previous requests "
            "for the same category+state+district."
        ),
    )


# ── Business ──────────────────────────────────────────────────────────────────

class MapBusiness(BaseModel):
    """A single unique business discovered from Google Maps."""

    place_id:        str            = Field(...,  description="Google Place ID — primary dedup key")
    name:            str            = Field(...,  description="Business name")
    address:         str            = Field("",   description="Formatted address from Google")
    phone:           Optional[str]  = Field(None, description="Phone number (intl preferred)")
    website:         Optional[str]  = Field(None, description="Official website URL")
    google_maps_uri: Optional[str]  = Field(None, description="Google Maps link")
    primary_type:    Optional[str]  = Field(None, description="Google primary place type")
    latitude:        Optional[float] = Field(None)
    longitude:       Optional[float] = Field(None)
    source:          str            = Field("google_maps", description="Always 'google_maps'")
    search_query:    str            = Field("",   description="Query that discovered this business")
    search_area:     str            = Field("",   description="Locality/area searched")

    class Config:
        extra = "ignore"


# ── Response / stats ──────────────────────────────────────────────────────────

class MapLeadsStats(BaseModel):
    """Run statistics returned alongside the results."""

    total_api_calls:    int       = Field(0,   description="HTTP calls made to Google Places API")
    total_raw_results:  int       = Field(0,   description="Total results received before dedup")
    duplicates_removed: int       = Field(0,   description="place_id duplicates removed")
    secondary_dupes:    int       = Field(0,   description="Secondary dedup removals (name/website/phone)")
    previously_seen:    int       = Field(0,   description="Skipped because seen in a prior request")
    with_phone:         int       = Field(0,   description="Businesses with a phone number")
    with_website:       int       = Field(0,   description="Businesses with a website")
    areas_searched:     int       = Field(0,   description="Sub-areas actually queried")
    queries_executed:   int       = Field(0,   description="Total search queries sent")
    areas_list:         list[str] = Field(default_factory=list)
    target_reached:     bool      = Field(False)
    exhausted:          bool      = Field(False, description="True if all areas exhausted before target")
    elapsed_seconds:    float     = Field(0.0)


class MapLeadsResponse(BaseModel):
    """Full response from POST /maps-leads/generate."""

    success:    bool              = Field(..., example=True)
    category:   str               = Field(..., example="construction")
    state:      str               = Field(..., example="Maharashtra")
    district:   Optional[str]     = Field(None, example="Pune")
    target:     int               = Field(..., example=50)
    total:      int               = Field(..., description="Unique businesses returned")
    businesses: list[MapBusiness] = Field(default_factory=list)
    stats:      MapLeadsStats     = Field(default_factory=MapLeadsStats)
    message:    str               = Field("")


# ── Geography responses ───────────────────────────────────────────────────────

class StatesResponse(BaseModel):
    states: list[str]


class DistrictsResponse(BaseModel):
    state:     str
    districts: list[str]
