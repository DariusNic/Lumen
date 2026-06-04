def _register(client, **overrides):
    payload = {
        "email": "ana@example.com",
        "password": "password123",
        "full_name": "Ana Popescu",
        "base_currency": "RON",
    }
    payload.update(overrides)
    return client.post("/api/auth/register", json=payload).get_json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- GET /api/me ----

def test_me_requires_auth(client):
    res = client.get("/api/me")
    assert res.status_code == 401
    assert res.get_json()["error_code"] == "UNAUTHORIZED"


def test_me_returns_user(client):
    body = _register(client)
    res = client.get("/api/me", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    user = res.get_json()["user"]
    assert user["email"] == "ana@example.com"
    assert user["full_name"] == "Ana Popescu"
    assert user["base_currency"] == "RON"
    assert "id" in user


def test_me_rejects_invalid_token(client):
    res = client.get("/api/me", headers=_auth("not.a.real.token"))
    assert res.status_code == 401


# ---- PATCH /api/me ----

def test_me_patch_updates_full_name(client):
    body = _register(client)
    res = client.patch(
        "/api/me", json={"full_name": "Ana Updated"}, headers=_auth(body["access_token"])
    )
    assert res.status_code == 200
    assert res.get_json()["user"]["full_name"] == "Ana Updated"


def test_me_patch_updates_base_currency(client):
    body = _register(client)
    res = client.patch(
        "/api/me", json={"base_currency": "EUR"}, headers=_auth(body["access_token"])
    )
    assert res.status_code == 200
    assert res.get_json()["user"]["base_currency"] == "EUR"


def test_me_patch_ignores_unknown_fields(client):
    body = _register(client)
    res = client.patch(
        "/api/me",
        json={"email": "trying@to-change.com", "is_admin": True, "full_name": "Ana 2"},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    user = res.get_json()["user"]
    # email is unchanged; is_admin doesn't exist
    assert user["email"] == "ana@example.com"
    assert user["full_name"] == "Ana 2"


def test_me_patch_rejects_unsupported_currency(client):
    body = _register(client)
    res = client.patch(
        "/api/me", json={"base_currency": "GBP"}, headers=_auth(body["access_token"])
    )
    assert res.status_code == 422


def test_me_patch_with_empty_body_is_noop(client):
    body = _register(client)
    res = client.patch("/api/me", json={}, headers=_auth(body["access_token"]))
    assert res.status_code == 200
    user = res.get_json()["user"]
    assert user["email"] == "ana@example.com"


def test_me_patch_requires_auth(client):
    res = client.patch("/api/me", json={"full_name": "Ana Updated"})
    assert res.status_code == 401
