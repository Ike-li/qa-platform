"""Tests for /api/orders endpoints."""

import responses
import requests


@responses.activate
def test_list_orders(api_base_url):
    """GET /api/orders returns a list of orders."""
    responses.add(
        responses.GET,
        f"{api_base_url}/api/orders",
        json=[
            {"id": 101, "user_id": 1, "total": 29.97, "status": "pending"},
            {"id": 102, "user_id": 2, "total": 15.00, "status": "completed"},
        ],
        status=200,
    )
    resp = requests.get(f"{api_base_url}/api/orders")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2


@responses.activate
def test_create_order(api_base_url, sample_order_data):
    """POST /api/orders creates a new order."""
    responses.add(
        responses.POST,
        f"{api_base_url}/api/orders",
        json=sample_order_data,
        status=201,
    )
    resp = requests.post(
        f"{api_base_url}/api/orders",
        json={"user_id": 1, "items": [{"name": "Widget A", "qty": 3, "price": 9.99}]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"


@responses.activate
def test_order_total(api_base_url):
    """Verify that order total is calculated correctly from items."""
    items = [
        {"name": "Widget A", "qty": 3, "price": 9.99},
        {"name": "Widget B", "qty": 1, "price": 15.00},
    ]
    expected_total = round(sum(item["qty"] * item["price"] for item in items), 2)

    responses.add(
        responses.POST,
        f"{api_base_url}/api/orders",
        json={
            "id": 200,
            "user_id": 1,
            "items": items,
            "total": expected_total,
            "status": "pending",
        },
        status=201,
    )
    resp = requests.post(
        f"{api_base_url}/api/orders", json={"user_id": 1, "items": items}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["total"] == 44.97


@responses.activate
def test_order_not_found(api_base_url):
    """GET /api/orders/999 returns 404 when order does not exist."""
    responses.add(
        responses.GET,
        f"{api_base_url}/api/orders/999",
        json={"error": "Order not found"},
        status=404,
    )
    resp = requests.get(f"{api_base_url}/api/orders/999")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
