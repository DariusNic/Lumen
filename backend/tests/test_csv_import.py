import io
import json


def _register(client):
    return client.post(
        "/api/auth/register",
        json={
            "email": "ana@example.com",
            "password": "password123",
            "full_name": "Ana",
            "base_currency": "RON",
        },
    ).get_json()


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


# Comma-delimited with single signed `Amount` column (Revolut-flavored)
CSV_REVOLUT = b"""Date,Description,Amount,Currency
2026-05-04,GLOVO order,-65.00,RON
2026-05-03,CARREFOUR Baneasa,-342.50,RON
2026-05-03,SALARIU ACME SRL,3800.00,RON
2026-05-02,SPOTIFY*PREMIUM,-35.00,RON
"""

# Semicolon-delimited with split debit/credit (BCR-flavored). Romanian decimal.
CSV_BCR = b"""Data;Descriere;Debit;Credit
04.05.2026;CHIRIE Aviatorilor;3200,00;
03.05.2026;SALARIU ACME SRL;;3800,00
02.05.2026;OMV statia Otopeni;215,40;
"""


def test_preview_detects_columns_and_delimiter(client):
    body = _register(client)
    res = client.post(
        "/api/transactions/import/preview",
        data={"file": (io.BytesIO(CSV_REVOLUT), "revolut.csv")},
        content_type="multipart/form-data",
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["delimiter"] == ","
    assert data["total_rows"] == 4
    assert data["headers"] == ["Date", "Description", "Amount", "Currency"]
    assert data["suggested_mapping"]["date"] == "Date"
    assert data["suggested_mapping"]["amount"] == "Amount"
    assert data["suggested_mapping"]["description"] == "Description"
    assert data["suggested_mapping"]["currency"] == "Currency"


def test_commit_imports_with_auto_categorization(client):
    body = _register(client)
    mapping = {
        "date": "Date",
        "description": "Description",
        "amount": "Amount",
        "currency": "Currency",
        "default_currency": "RON",
    }
    res = client.post(
        "/api/transactions/import/commit",
        data={
            "file": (io.BytesIO(CSV_REVOLUT), "revolut.csv"),
            "mapping": json.dumps(mapping),
        },
        content_type="multipart/form-data",
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    body_json = res.get_json()
    assert body_json["inserted"] == 4
    assert body_json["skipped"] == 0

    # Verify auto-categorization landed correctly.
    txs = client.get(
        "/api/transactions", headers=_auth(body["access_token"])
    ).get_json()["transactions"]
    by_desc = {t["description"]: t["category_name"] for t in txs}
    assert by_desc["GLOVO order"] == "Restaurants"
    assert by_desc["CARREFOUR Baneasa"] == "Groceries"
    assert by_desc["SALARIU ACME SRL"] == "Salary"
    assert by_desc["SPOTIFY*PREMIUM"] == "Subscriptions"
    # All marked as csv-sourced.
    assert all(t["source"] == "csv" for t in txs)


def test_commit_handles_split_debit_credit_and_romanian_decimal(client):
    body = _register(client)
    preview_res = client.post(
        "/api/transactions/import/preview",
        data={"file": (io.BytesIO(CSV_BCR), "bcr.csv")},
        content_type="multipart/form-data",
        headers=_auth(body["access_token"]),
    )
    assert preview_res.status_code == 200
    assert preview_res.get_json()["delimiter"] == ";"

    mapping = {
        "date": "Data",
        "description": "Descriere",
        "debit": "Debit",
        "credit": "Credit",
        "default_currency": "RON",
    }
    res = client.post(
        "/api/transactions/import/commit",
        data={
            "file": (io.BytesIO(CSV_BCR), "bcr.csv"),
            "mapping": json.dumps(mapping),
        },
        content_type="multipart/form-data",
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    assert res.get_json()["inserted"] == 3

    txs = client.get(
        "/api/transactions", headers=_auth(body["access_token"])
    ).get_json()["transactions"]
    by_desc = {t["description"]: t for t in txs}
    # Debit-only row → negative amount; Romanian "3200,00" → 3200.0
    assert by_desc["CHIRIE Aviatorilor"]["amount"] == -3200.00
    assert by_desc["SALARIU ACME SRL"]["amount"] == 3800.00
    assert by_desc["OMV statia Otopeni"]["amount"] == -215.40
    # Categorization still works
    assert by_desc["CHIRIE Aviatorilor"]["category_name"] == "Housing"
    assert by_desc["OMV statia Otopeni"]["category_name"] == "Transport"


def test_commit_requires_amount_or_debit_credit(client):
    body = _register(client)
    mapping = {"date": "Date", "description": "Description"}
    res = client.post(
        "/api/transactions/import/commit",
        data={
            "file": (io.BytesIO(CSV_REVOLUT), "x.csv"),
            "mapping": json.dumps(mapping),
        },
        content_type="multipart/form-data",
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422


def test_commit_skips_unparseable_rows(client):
    body = _register(client)
    bad = b"""Date,Description,Amount,Currency
not-a-date,GLOVO,-50,RON
2026-05-03,CARREFOUR,-100,RON
"""
    mapping = {
        "date": "Date",
        "description": "Description",
        "amount": "Amount",
        "currency": "Currency",
        "default_currency": "RON",
    }
    res = client.post(
        "/api/transactions/import/commit",
        data={"file": (io.BytesIO(bad), "x.csv"), "mapping": json.dumps(mapping)},
        content_type="multipart/form-data",
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    out = res.get_json()
    assert out["inserted"] == 1
    assert out["skipped"] == 1


def test_preview_requires_auth(client):
    res = client.post(
        "/api/transactions/import/preview",
        data={"file": (io.BytesIO(CSV_REVOLUT), "x.csv")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 401
