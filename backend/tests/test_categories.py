def _register(client, email="ana@example.com"):
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Ana Popescu",
            "base_currency": "RON",
        },
    ).get_json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_seeds_15_default_categories(client):
    body = _register(client)
    res = client.get("/api/categories", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    cats = res.get_json()["categories"]
    assert len(cats) == 15
    names = {c["name"] for c in cats}
    assert "Groceries" in names
    assert "Restaurants" in names
    assert "Goals" in names
    assert "Other" in names
    assert all(c["is_default"] is True for c in cats)


def test_create_custom_category(client):
    body = _register(client)
    res = client.post(
        "/api/categories",
        json={"name": "Pets", "color": "#a78bfa"},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    cat = res.get_json()["category"]
    assert cat["name"] == "Pets"
    assert cat["color"] == "#a78bfa"
    assert cat["is_default"] is False


def test_create_rejects_bad_color(client):
    body = _register(client)
    res = client.post(
        "/api/categories",
        json={"name": "Bad", "color": "purple"},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422


def test_create_rejects_duplicate_name(client):
    body = _register(client)
    res = client.post(
        "/api/categories",
        json={"name": "Groceries", "color": "#000000"},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422
    assert res.get_json()["details"]["field"] == "name"


def test_update_category(client):
    body = _register(client)
    res = client.post(
        "/api/categories",
        json={"name": "Pets", "color": "#a78bfa"},
        headers=_auth(body["access_token"]),
    )
    cat_id = res.get_json()["category"]["id"]
    res2 = client.patch(
        f"/api/categories/{cat_id}",
        json={"name": "Pet care", "color": "#7c3aed"},
        headers=_auth(body["access_token"]),
    )
    assert res2.status_code == 200
    updated = res2.get_json()["category"]
    assert updated["name"] == "Pet care"
    assert updated["color"] == "#7c3aed"


def test_cannot_delete_system_default(client):
    body = _register(client)
    cats = client.get("/api/categories", headers=_auth(body["access_token"])).get_json()["categories"]
    groceries = next(c for c in cats if c["name"] == "Groceries")
    res = client.delete(
        f"/api/categories/{groceries['id']}", headers=_auth(body["access_token"])
    )
    assert res.status_code == 422
    assert res.get_json()["error_code"] == "VALIDATION_ERROR"


def test_delete_custom_category_soft_deletes(client):
    body = _register(client)
    cat = client.post(
        "/api/categories",
        json={"name": "Pets", "color": "#a78bfa"},
        headers=_auth(body["access_token"]),
    ).get_json()["category"]
    res = client.delete(
        f"/api/categories/{cat['id']}", headers=_auth(body["access_token"])
    )
    assert res.status_code == 200
    after = client.get("/api/categories", headers=_auth(body["access_token"])).get_json()["categories"]
    assert all(c["id"] != cat["id"] for c in after)


def test_list_requires_auth(client):
    res = client.get("/api/categories")
    assert res.status_code == 401


def test_users_dont_see_each_others_categories(client):
    a = _register(client, "a@example.com")
    b = _register(client, "b@example.com")
    client.post(
        "/api/categories",
        json={"name": "A-only", "color": "#abcdef"},
        headers=_auth(a["access_token"]),
    )
    cats_b = client.get("/api/categories", headers=_auth(b["access_token"])).get_json()["categories"]
    assert all(c["name"] != "A-only" for c in cats_b)


def test_default_categories_have_zero_monthly_budget(client):
    body = _register(client)
    cats = client.get("/api/categories", headers=_auth(body["access_token"])).get_json()["categories"]
    assert all(c["monthly_budget"] == 0.0 for c in cats)


def test_create_category_with_monthly_budget(client):
    body = _register(client)
    res = client.post(
        "/api/categories",
        json={"name": "Pets", "color": "#a78bfa", "monthly_budget": 250.0},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    assert res.get_json()["category"]["monthly_budget"] == 250.0


def test_update_monthly_budget_on_default_category(client):
    body = _register(client)
    cats = client.get("/api/categories", headers=_auth(body["access_token"])).get_json()["categories"]
    groceries = next(c for c in cats if c["name"] == "Groceries")
    res = client.patch(
        f"/api/categories/{groceries['id']}",
        json={"monthly_budget": 1100.0},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    assert res.get_json()["category"]["monthly_budget"] == 1100.0


def test_monthly_budget_rejects_negative(client):
    body = _register(client)
    res = client.post(
        "/api/categories",
        json={"name": "Pets", "color": "#a78bfa", "monthly_budget": -50},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422
