import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator

ALLOWED_DISCOUNT_TIERS = {0, 10, 15, 20}
ALLOWED_CHANNELS = {"email", "push"}
MAX_MESSAGING_LENGTH = 300


PROFANITY_BLOCKLIST = {"damn", "hell", "crap"}

# Basic PII patterns: email addresses, phone numbers, credit-card-like digit runs
PII_PATTERNS = [
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),   # email
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),                # phone
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),                          # card-like digit run
]


class DiscountTier(int, Enum):
    NONE = 0
    LOW = 10
    MEDIUM = 15
    HIGH = 20


class Channel(str, Enum):
    EMAIL = "email"
    PUSH = "push"


class RetentionIncentive(BaseModel):
    customer_id: int
    discount_pct: DiscountTier
    channel: Channel
    product_focus: str = Field(..., description="Must be a valid product_id from core.dim_products")
    messaging: str = Field(..., max_length=MAX_MESSAGING_LENGTH)

    @field_validator("messaging")
    @classmethod
    def check_messaging_content(cls, v):
        lowered = v.lower()

        for word in PROFANITY_BLOCKLIST:
            if word in lowered:
                raise ValueError(f"Messaging contains disallowed content (profanity filter)")

        for pattern in PII_PATTERNS:
            if pattern.search(v):
                raise ValueError("Messaging appears to contain PII (email/phone/card-like pattern)")

        return v