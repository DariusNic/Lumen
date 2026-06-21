from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.models.user import Currency

# Per plan §9 / §B.4. Every type maps deterministically to "asset" or "liability".
# Only the auto-seeded accounts ("investment", "other_asset") are created today,
# but the full enum is kept so historical documents still validate.
AccountType = Literal[
    "cash", "savings", "investment", "real_estate", "vehicle", "other_asset",
    "credit", "loan", "mortgage", "other_liability",
]
AssetCategory = Literal["asset", "liability"]

ASSET_TYPES = {"cash", "savings", "investment", "real_estate", "vehicle", "other_asset"}


def category_for(type_: str) -> AssetCategory:
    return "asset" if type_ in ASSET_TYPES else "liability"


class AccountPublic(BaseModel):
    id: str
    name: str
    type: AccountType
    category: AssetCategory
    balance: float
    currency: Currency
    is_automatic: bool
    source_ref: Optional[str]
    notes: Optional[str]
    last_updated: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
