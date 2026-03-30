"""
core/models.py
Pydantic models for all data flowing through the bot.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class Domain(str, Enum):
    CRYPTO = "crypto"
    POLITICS = "politics"
    ECONOMICS = "economics"
    SPORTS = "sports"
    OTHER = "other"


class SignalStrength(str, Enum):
    STRONG_BUY = "STRONG_BUY"    # Edge >= 12%, confidence >= 0.75
    BUY = "BUY"                   # Edge >= 6%, confidence >= 0.65
    HOLD = "HOLD"                 # Edge < 6% or confidence < 0.65
    SELL = "SELL"                 # We hold a position, edge reversed
    STRONG_SELL = "STRONG_SELL"  # Strong reversal


class OutcomeToken(BaseModel):
    token_id: str
    outcome: str                  # "Yes" or "No"
    price: float                  # Current market price (0.0 to 1.0)

    @validator("price")
    def price_range(cls, v):
        assert 0.0 <= v <= 1.0, f"Price {v} out of range"
        return v


class PolymarketMarket(BaseModel):
    """Represents a single binary market from Gamma API."""
    condition_id: str
    question: str
    description: Optional[str] = ""
    category: Optional[str] = ""
    domain: Domain = Domain.OTHER
    tokens: List[OutcomeToken] = []

    # Prices
    yes_price: float = 0.5
    no_price: float = 0.5

    # Volume / liquidity
    volume_24h: float = 0.0
    liquidity: float = 0.0
    total_volume: float = 0.0

    # Timing
    end_date: Optional[datetime] = None
    days_to_resolution: Optional[int] = None

    # Resolution
    resolution_source: Optional[str] = ""
    active: bool = True
    closed: bool = False

    # Raw tags
    tags: List[str] = []

    # Metadata
    market_slug: Optional[str] = ""
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class NewsItem(BaseModel):
    """A single news article relevant to a market."""
    title: str
    url: str
    source: str
    published_at: Optional[datetime] = None
    summary: Optional[str] = ""
    relevance_score: float = 0.0  # 0–1, how relevant to the market
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class ReasoningStep(BaseModel):
    """
    One step in the superforecasting reasoning chain.
    Mirrors the Tetlock superforecasting methodology.
    """
    step_name: str
    question: str
    answer: str
    probability_estimate: Optional[float] = None
    confidence: Optional[float] = None


class ReasoningResult(BaseModel):
    """
    Full output of the structured reasoning engine for one market.
    This is what differentiates us from every other bot.
    """
    market_condition_id: str
    market_question: str

    # The core output
    our_probability: float           # Our calibrated YES probability
    market_probability: float        # What the market currently implies
    edge: float                      # our_probability - market_probability
    confidence: float                # 0.0–1.0 confidence in our estimate
    signal: SignalStrength

    # Reasoning chain (superforecasting steps)
    steps: List[ReasoningStep] = []

    # Supporting evidence
    news_items_used: List[str] = []  # URLs of news used
    base_rate_used: Optional[str] = ""
    reference_class: Optional[str] = ""

    # Calibration metadata
    raw_llm_probability: float = 0.0  # Before calibration
    calibration_adjustment: float = 0.0  # How much we adjusted
    calibration_note: str = ""

    # Kelly sizing output (paper only in Phase 1)
    kelly_fraction: float = 0.0
    suggested_position_pct: float = 0.0
    suggested_position_usd: float = 0.0

    # Timestamps
    reasoned_at: datetime = Field(default_factory=datetime.utcnow)
    valid_until: Optional[datetime] = None   # Expires when news is stale


class PaperTrade(BaseModel):
    """
    A paper trade — never touches real funds in Phase 1.
    Recorded for performance tracking and validation.
    """
    id: Optional[str] = None
    market_condition_id: str
    market_question: str
    side: str                        # "YES" or "NO"
    entry_price: float
    size_usd: float
    signal: SignalStrength
    our_probability: float
    market_probability: float
    edge: float
    confidence: float

    # Outcome (filled when market resolves)
    exit_price: Optional[float] = None
    resolved: bool = False
    resolution_outcome: Optional[str] = None  # "YES" or "NO"
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None

    # Metadata
    domain: Domain = Domain.OTHER
    entered_at: datetime = Field(default_factory=datetime.utcnow)
    exited_at: Optional[datetime] = None
    reasoning_id: Optional[str] = None


class PortfolioSnapshot(BaseModel):
    """Paper portfolio state at a point in time."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    starting_capital: float = 10_000.0
    current_capital: float = 10_000.0
    deployed_capital: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    open_positions: int = 0
    closed_positions: int = 0
    win_rate: float = 0.0
    avg_edge_captured: float = 0.0
    phase: int = 1


class BotAlert(BaseModel):
    """Telegram/notification alert."""
    alert_type: str          # "SIGNAL", "RESOLVED", "ERROR", "DAILY_SUMMARY"
    title: str
    body: str
    signal: Optional[SignalStrength] = None
    market_question: Optional[str] = None
    edge: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
