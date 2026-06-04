from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import Currency

# Per plan §9 / §B.4. Every type maps deterministically to "asset" or "liability".
AccountType = Literal[
    "cash", "savings", "investment", "real_estate", "vehicle", "other_asset",
    "credit", "loan", "mortgage", "other_liability",
]
AssetCategory = Literal["asset", "liability"]

ASSET_TYPES = {"cash", "savings", "investment", "real_estate", "vehicle", "other_asset"}
LIABILITY_TYPES = {"credit", "loan", "mortgage", "other_liability"}

Amount = Annotated[float, Field(ge=0, allow_inf_nan=False)]


def category_for(type_: str) -> AssetCategory:
    return "asset" if type_ in ASSET_TYPES else "liability"


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: AccountType
    balance: Amount = 0.0
    currency: Currency
    notes: Optional[str] = Field(default=None, max_length=400)


class AccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    type: Optional[AccountType] = None
    balance: Optional[Amount] = None
    currency: Optional[Currency] = None
    notes: Optional[str] = Field(default=None, max_length=400)


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
