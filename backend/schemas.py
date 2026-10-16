from typing import Literal
from pydantic import BaseModel, Field, field_validator

class Article(BaseModel):
    id: str = ''
    title: str = Field(default='Untitled article', max_length=500)
    text: str = Field(min_length=80, max_length=40000)
    publisher: str = Field(default='User-provided', max_length=300)
    url: str = Field(default='', max_length=2048)
    date: str = Field(default='', max_length=80)
    fictional: bool = False

class AnalysisRequest(BaseModel):
    articles: list[Article] = Field(min_length=2, max_length=10)
    use_llm: bool = True
    reference_summary: str | None = Field(default=None, max_length=20000)
    duplicate_threshold: float = Field(default=0.92, ge=0.7, le=1)

class SearchRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=180)
    days: int = Field(default=7, ge=1, le=30)
    limit: int = Field(default=10, ge=2, le=10)

class ExtractRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=10)

class CitedClaim(BaseModel):
    text: str = Field(max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)

class Event(CitedClaim):
    date: str | None = None

class Synthesis(BaseModel):
    summary: list[CitedClaim] = Field(max_length=12)
    events: list[Event] = Field(max_length=30)

class Review(BaseModel):
    classification: Literal['potential_contradiction','possible_update','different_scope','insufficient_evidence']
    explanation: str = Field(max_length=2000)
