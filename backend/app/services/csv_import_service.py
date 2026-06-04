"""CSV import for transactions.

Two-call flow from the frontend (matches the 3-step wizard in DESIGN.md §4):
  1. POST /api/transactions/import/preview   — upload file, get parsed first
                                                rows + auto-detected column mapping.
  2. POST /api/transactions/import/commit    — submit confirmed mapping; we
                                                bulk-insert.

We support whatever Romanian banks export (BCR, ING, Revolut, BT, Raiffeisen):
- comma OR semicolon delimiter (auto-sniffed)
- amount can be a single signed column OR two columns (debit / credit)
- date in d/m/Y, Y-m-d, d.m.Y, d-m-Y, etc. (parsed leniently)
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Optional

import pandas as pd
from pydantic import BaseModel, Field

from app.models.transaction import TransactionCreate
from app.services import tx_service
from app.utils.errors import ValidationError


# Heuristics: column name → canonical role. Lowercased before lookup.
_COLUMN_ALIASES: dict[str, str] = {
    # date
    "date": "date", "data": "date", "data tranzactiei": "date", "transaction date": "date",
    "booking date": "date", "value date": "date",
    # description / merchant
    "description": "description", "descriere": "description", "details": "description",
    "narrative": "description", "explicatii": "description",
    "merchant": "merchant", "comerciant": "merchant", "beneficiar": "merchant",
    "payee": "merchant",
    # amount
    "amount": "amount", "suma": "amount", "valoare": "amount", "total": "amount",
    "debit": "debit", "credit": "credit",
    "withdrawal": "debit", "deposit": "credit",
    # currency
    "currency": "currency", "ccy": "currency", "moneda": "currency", "valuta": "currency",
}


class ImportPreviewResult(BaseModel):
    headers: list[str]
    sample_rows: list[dict[str, Any]]
    suggested_mapping: dict[str, Optional[str]]
    delimiter: str
    total_rows: int


class ImportMapping(BaseModel):
    """User-confirmed column mapping submitted at commit time."""

    date: str = Field(min_length=1)
    description: str = Field(min_length=1)
    amount: Optional[str] = None   # if single signed column
    debit: Optional[str] = None    # if split debit/credit columns
    credit: Optional[str] = None
    currency: Optional[str] = None  # column name; falls back to default_currency
    merchant: Optional[str] = None
    default_currency: str = "RON"


class ImportCommitResult(BaseModel):
    inserted: int
    skipped: int
    errors: list[str]


def _sniff_delimiter(text: str) -> str:
    head = text[:4096]
    return ";" if head.count(";") > head.count(",") else ","


def _read(content: bytes) -> tuple[pd.DataFrame, str]:
    text = content.decode("utf-8-sig", errors="replace")
    delim = _sniff_delimiter(text)
    try:
        df = pd.read_csv(io.StringIO(text), sep=delim, dtype=str, keep_default_na=False)
    except Exception as e:
        raise ValidationError(f"Could not parse CSV: {e}") from e
    df.columns = [c.strip() for c in df.columns]
    return df, delim


def _suggest_mapping(headers: list[str]) -> dict[str, Optional[str]]:
    out: dict[str, Optional[str]] = {
        "date": None, "description": None, "merchant": None,
        "amount": None, "debit": None, "credit": None, "currency": None,
    }
    for h in headers:
        role = _COLUMN_ALIASES.get(h.strip().lower())
        if role and out.get(role) is None:
            out[role] = h
    return out


def preview(content: bytes) -> ImportPreviewResult:
    df, delim = _read(content)
    headers = list(df.columns)
    sample = df.head(5).to_dict(orient="records")
    return ImportPreviewResult(
        headers=headers,
        sample_rows=sample,
        suggested_mapping=_suggest_mapping(headers),
        delimiter=delim,
        total_rows=len(df),
    )


def _coerce_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        # pandas's to_datetime is unforgiving with mixed formats unless dayfirst flexes.
        return pd.to_datetime(value, dayfirst=True, errors="raise").to_pydatetime()
    except Exception:
        return None


def _coerce_amount(value: str) -> Optional[float]:
    if value is None or value == "":
        return None
    s = str(value).strip()
    # Tolerate Romanian decimal (1.234,56) and English (1,234.56). Also strip currency suffixes.
    s = s.replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        # If both, the rightmost is the decimal separator.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    # Strip non-numeric trailers like "RON" or "EUR".
    cleaned = ""
    for ch in s:
        if ch.isdigit() or ch in ".-+":
            cleaned += ch
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def commit(user_id: str, content: bytes, mapping: ImportMapping) -> ImportCommitResult:
    df, _ = _read(content)
    if df.empty:
        return ImportCommitResult(inserted=0, skipped=0, errors=["File contained no rows"])

    if not (mapping.amount or (mapping.debit and mapping.credit)):
        raise ValidationError(
            "Mapping must specify either `amount` OR both `debit` and `credit`",
            details={"field": "amount"},
        )

    inserted = 0
    skipped = 0
    errors: list[str] = []
    for i, row in df.iterrows():
        try:
            date = _coerce_date(row.get(mapping.date, ""))
            if not date:
                skipped += 1
                continue

            if mapping.amount:
                amount = _coerce_amount(row.get(mapping.amount, ""))
            else:
                debit = _coerce_amount(row.get(mapping.debit or "", "")) or 0.0
                credit = _coerce_amount(row.get(mapping.credit or "", "")) or 0.0
                amount = credit - debit
            if amount is None or amount == 0:
                skipped += 1
                continue

            description = str(row.get(mapping.description, "")).strip()
            if not description:
                skipped += 1
                continue

            currency = (
                str(row.get(mapping.currency, "")).strip().upper()
                if mapping.currency else mapping.default_currency
            ) or mapping.default_currency
            if currency not in {"RON", "EUR", "USD"}:
                currency = mapping.default_currency

            merchant = (
                str(row.get(mapping.merchant, "")).strip() or None
                if mapping.merchant else None
            )

            tx_service.create(
                user_id,
                TransactionCreate(
                    date=date,
                    amount=float(amount),
                    currency=currency,  # type: ignore[arg-type]
                    description=description,
                    merchant=merchant,
                    source="csv",
                ),
            )
            inserted += 1
        except Exception as e:  # noqa: BLE001 — per-row failures shouldn't abort the batch
            skipped += 1
            errors.append(f"row {int(i) + 2}: {e}")  # +2 for header + 1-based

    return ImportCommitResult(inserted=inserted, skipped=skipped, errors=errors[:20])
