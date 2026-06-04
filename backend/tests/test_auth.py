def _payload(email="ana@example.com", password="password123", **overrides):
    body = {
        "email": email,
        "password": password,
        "full_name": "Ana Popescu",
        "base_currency": "RON",
    }
    body.update(overrides)
    return body


# ---- /api/auth/register ----

def test_register_creates_user_and_returns_tokens(client):
    res = client.post("/api/auth/register", json=_payload())
    assert res.status_code == 201
    body = res.get_json()
    assert body["user"]["email"] == "ana@example.com"
    assert body["user"]["full_name"] == "Ana Popescu"
    assert body["user"]["base_currency"] == "RON"
    assert "id" in body["user"]
    assert body["access_token"]
    assert body["refresh_token"]
    # password_hash must NEVER be returned
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_register_lowercases_email(client):
    res = client.post("/api/auth/register", json=_payload(email="Ana@Example.COM"))
    assert res.status_code == 201
    assert res.get_json()["user"]["email"] == "ana@example.com"


def test_register_rejects_duplicate_email(client):
    client.post("/api/auth/register", json=_payload())
    res = client.post("/api/auth/register", json=_payload())
    assert res.status_code == 422
    body = res.get_json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["details"].get("field") == "email"


def test_register_rejects_invalid_email(client):
    res = client.post("/api/auth/register", json=_payload(email="not-an-email"))
    assert res.status_code == 422
    assert res.get_json()["error_code"] == "VALIDATION_ERROR"


def test_register_rejects_short_password(client):
    res = client.post("/api/auth/register", json=_payload(password="short"))
    assert res.status_code == 422


def test_register_rejects_unsupported_currency(client):
    res = client.post("/api/auth/register", json=_payload(base_currency="GBP"))
    assert res.status_code == 422


# ---- /api/auth/login ----

def test_login_returns_tokens_for_valid_credentials(client):
    client.post("/api/auth/register", json=_payload())
    res = client.post(
        "/api/auth/login", json={"email": "ana@example.com", "password": "password123"}
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == "ana@example.com"


def test_login_is_case_insensitive_on_email(client):
    client.post("/api/auth/register", json=_payload())
    res = client.post(
        "/api/auth/login", json={"email": "ANA@example.com", "password": "password123"}
    )
    assert res.status_code == 200


def test_login_rejects_wrong_password(client):
    client.post("/api/auth/register", json=_payload())
    res = client.post(
        "/api/auth/login", json={"email": "ana@example.com", "password": "wrongpassword"}
    )
    assert res.status_code == 401
    assert res.get_json()["error_code"] == "UNAUTHORIZED"


def test_login_rejects_unknown_email(client):
    res = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "password123"}
    )
    assert res.status_code == 401


def test_login_requires_both_fields(client):
    res = client.post("/api/auth/login", json={"email": "ana@example.com"})
    assert res.status_code == 422
    assert res.get_json()["error_code"] == "VALIDATION_ERROR"


# ---- /api/auth/refresh ----

def test_refresh_with_refresh_token_issues_new_access_token(client):
    body = client.post("/api/auth/register", json=_payload()).get_json()
    res = client.post(
        "/api/auth/refresh", headers={"Authorization": f"Bearer {body['refresh_token']}"}
    )
    assert res.status_code == 200
    assert res.get_json()["access_token"]


def test_refresh_rejects_access_token(client):
    body = client.post("/api/auth/register", json=_payload()).get_json()
    res = client.post(
        "/api/auth/refresh", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    # Wrong token type → 401 via our unified envelope
    assert res.status_code == 401


def test_refresh_requires_token(client):
    res = client.post("/api/auth/refresh")
    assert res.status_code == 401


# ---- /api/auth/logout ----

def test_logout_with_valid_token_returns_ok(client):
    body = client.post("/api/auth/register", json=_payload()).get_json()
    res = client.post(
        "/api/auth/logout", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}


def test_logout_requires_token(client):
    res = client.post("/api/auth/logout")
    assert res.status_code == 401


# ---- /api/auth/forgot (stub) ------------------------------------------------

def test_forgot_returns_ok_for_unknown_email(client):
    """Anti-enumeration: never leak whether an email exists."""
    res = client.post("/api/auth/forgot", json={"email": "nobody@example.com"})
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}


def test_forgot_returns_ok_for_known_email(client):
    client.post("/api/auth/register", json=_payload())
    res = client.post("/api/auth/forgot", json={"email": "ana@example.com"})
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}


def test_forgot_requires_email(client):
    res = client.post("/api/auth/forgot", json={})
    assert res.status_code == 422


# ---- /api/auth/reset --------------------------------------------------------

def test_reset_returns_ok_with_valid_token(app, client):
    """End-to-end: register → mint a real reset token → reset → log in
    with the new password."""
    from app.services import token_service
    body = client.post(
        "/api/auth/register",
        json={
            "email": "resetme@example.com",
            "password": "originalpass123",
            "full_name": "Reset Me",
            "base_currency": "EUR",
        },
    ).get_json()
    user_id = body["user"]["id"]
    with app.app_context():
        token = token_service.mint(user_id, "reset_password")
    res = client.post(
        "/api/auth/reset",
        json={"token": token, "password": "newpassword123"},
    )
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}
    # New password works.
    login_ok = client.post(
        "/api/auth/login",
        json={"email": "resetme@example.com", "password": "newpassword123"},
    )
    assert login_ok.status_code == 200


def test_reset_rejects_unknown_token(client):
    res = client.post(
        "/api/auth/reset",
        json={"token": "not-a-real-token", "password": "newpassword123"},
    )
    assert res.status_code == 422
    assert res.get_json()["error_code"] == "VALIDATION_ERROR"


def test_reset_rejects_short_password(client):
    res = client.post(
        "/api/auth/reset", json={"token": "x", "password": "short"}
    )
    assert res.status_code == 422


def test_reset_rejects_missing_token(client):
    res = client.post("/api/auth/reset", json={"password": "newpassword123"})
    assert res.status_code == 422
