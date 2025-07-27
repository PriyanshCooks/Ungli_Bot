# back_end_llm/pydantic_models.py
from typing import List, Optional
from pydantic import BaseModel, Field

class ConversationEntry(BaseModel):
    question: str
    answer: str

class ConversationLog(BaseModel):
    conversation: List[ConversationEntry]

class PredictionResult(BaseModel):
    predicted_interests: List[str] = Field(..., description="Inferred product-level application areas")

class DisplayName(BaseModel):
    text: Optional[str] = None

class Location(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class Place(BaseModel):
    displayName: Optional[DisplayName] = None
    formattedAddress: Optional[str] = None
    location: Optional[Location] = None
    primaryType: Optional[str] = None
    types: Optional[List[str]] = None
    businessStatus: Optional[str] = None
    googleMapsURL: Optional[str] = None
    websiteURL: Optional[str] = None
    nationalPhoneNumber: Optional[str] = None
    internationalPhoneNumber: Optional[str] = None
    rating: Optional[float] = None
    userRatingCount: Optional[int] = Field(None, alias="userRatingCount")

class SearchQueryEntry(BaseModel):
    application: str
    google_search_terms: List[str]
    matched_places: List[Place]
    status: str  # "OK", "ZERO_RESULTS", or "ERROR"

class SearchQueryResults(BaseModel):
    extracted_applications: List[str]
    targeting_keywords: List[SearchQueryEntry]

class SearchTerms(BaseModel):
    search_terms: List[str]


