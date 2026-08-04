from __future__ import annotations

from datetime import date
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class Review(BaseModel):
    reviewer_name: Optional[str] = None
    rating: Optional[float] = None
    text: Optional[str] = None
    review_date: Optional[date] = None


class Category(BaseModel):
    primary_category: str
    sub_category: str


class FAQ(BaseModel):
    title: str
    content: str
    order: int = 0


class Highlight(BaseModel):
    reason_heading: str
    reason_description: str


class Location(BaseModel):
    """Business base location (not service / travel area)."""

    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    raw_location: Optional[str] = None


class ServiceArea(BaseModel):
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    service_pincode: Optional[str] = None
    travel_radius: Optional[int] = None
    can_travel_nationwide: Optional[bool] = None
    can_travel_statewide: Optional[bool] = None


class YearsInBusiness(BaseModel):
    start_year: Optional[int] = None
    start_month: Optional[int] = None


class Price(BaseModel):
    amount: float
    per: str  # event | hour | day | person | etc.


class TimeSlot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_time: str = Field(alias="from")
    to_time: str = Field(alias="to")


class DayAvailability(BaseModel):
    isAvailable: bool = False
    availability: list[TimeSlot] = Field(default_factory=list)


class WeeklyHours(BaseModel):
    monday: Optional[DayAvailability] = None
    tuesday: Optional[DayAvailability] = None
    wednesday: Optional[DayAvailability] = None
    thursday: Optional[DayAvailability] = None
    friday: Optional[DayAvailability] = None
    saturday: Optional[DayAvailability] = None
    sunday: Optional[DayAvailability] = None


class SocialMediaLink(BaseModel):
    platform_type: str
    platform_url: str


class Package(BaseModel):
    title: str
    description: str
    price: Optional[Price] = None
    prices: list[Price] = Field(default_factory=list)
    offerings: list[str] = Field(default_factory=list)


class Addon(BaseModel):
    title: str
    description: str
    amount: float


class MandatoryFee(BaseModel):
    title: str
    description: str
    amount: float


class SetupRequirement(BaseModel):
    title: str
    description: str


class PortfolioFile(BaseModel):
    type: Literal["image", "video"]
    url: str


class LogisticDetails(BaseModel):
    power_requirements: Optional[str] = None
    equipment_provided: Optional[list[str]] = None
    equipment_needed_from_venue: Optional[list[str]] = None
    team_size: Optional[int] = None
    travel_fee_notes: Optional[str] = None
    indoor_outdoor: Optional[Literal["indoor", "outdoor", "both"]] = None


class VendorEvent(BaseModel):
    event_date: Optional[date] = None
    location: Optional[str] = None
    event_type: Optional[str] = None
    description: Optional[str] = None


class VendorProfile(BaseModel):
    # Identity
    business_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    secondary_phone_number: Optional[str] = None
    business_type: Optional[str] = None
    slug: Optional[str] = None
    website: Optional[str] = None
    profile_picture: Optional[str] = None

    # What they do
    categories: Optional[list[Category]] = None
    services_provided: Optional[list[str]] = None
    tagline: Optional[str] = None
    description: Optional[str] = None
    reason_to_book_me: Optional[list[Highlight]] = None
    faqs: Optional[list[FAQ]] = None
    languages: Optional[list[str]] = None
    genres_or_styles: Optional[list[str]] = None
    years_in_business: Optional[YearsInBusiness] = None

    # Media
    portfolio_files: Optional[list[PortfolioFile]] = None

    # Location & travel
    location: Optional[Location] = None
    service_area: Optional[ServiceArea] = None
    available_dates: Optional[list[date]] = None
    unavailable_dates: Optional[list[date]] = None

    # Booking logistics
    booking_notice: Optional[int] = None  # in days
    setup_time: Optional[Union[int, str]] = None  # in hours
    breakdown_time: Optional[Union[int, str]] = None  # in hours
    has_event_space: Optional[bool] = None
    emergency_booking: Optional[bool] = None
    weekly_hours: Optional[WeeklyHours] = None
    setup_requirements: Optional[list[SetupRequirement]] = None
    logistic_details: Optional[LogisticDetails] = None

    # Pricing
    prices: Optional[list[Price]] = None
    packages: Optional[list[Package]] = None
    available_addons: Optional[list[Addon]] = None
    mandatory_fees: Optional[list[MandatoryFee]] = None

    # Ratings & social proof (extract-only)
    rating_average: Optional[float] = Field(default=None, ge=0, le=5)
    reviews: Optional[list[Review]] = None
    times_booked: Optional[int] = None
    repeat_client_rate: Optional[float] = None

    # Contact / booking (extract-only extras + product overlap)
    response_time: Optional[str] = None
    response_rate: Optional[float] = None
    booking_url: Optional[str] = None
    verified_badges: Optional[list[str]] = None
    insurance_info: Optional[str] = None
    cancellation_policy: Optional[str] = None

    # Extra
    awards: Optional[list[str]] = None
    similar_vendors: Optional[list[str]] = None
    social_media: Optional[list[SocialMediaLink]] = None
    past_events: Optional[list[VendorEvent]] = None
    upcoming_events: Optional[list[VendorEvent]] = None
