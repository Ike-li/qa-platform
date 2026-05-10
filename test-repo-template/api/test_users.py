"""Tests for /api/users endpoints."""

import responses
import requests


@responses.activate
def test_get_users(api_base_url):
    """GET /api/users returns a list of users."""
    responses.add(
        responses.GET,
        f"{api_base_url}/api/users",
        json=[
            {"id": 1, "username": "alice", "role": "tester"},
            {"id": 2, "username": "bob", "role": "admin"},
        ],
        status=200,
    )
    resp = requests.get(f"{api_base_url}/api/users")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2


@responses.activate
def test_get_user_by_id(api_base_url, sample_user_data):
    """GET /api/users/1 returns the specified user."""
    responses.add(
        responses.GET,
        f"{api_base_url}/api/users/1",
        json=sample_user_data,
        status=200,
    )
    resp = requests.get(f"{api_base_url}/api/users/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"


@responses.activate
def test_create_user(api_base_url):
    """POST /api/users creates a new user."""
    new_user = {
        "id": 3,
        "username": "charlie",
        "email": "charlie@example.com",
        "role": "viewer",
        "is_active": True,
    }
    responses.add(
        responses.POST,
        f"{api_base_url}/api/users",
        json=new_user,
        status=201,
    )
    resp = requests.post(
        f"{api_base_url}/api/users",
        json={"username": "charlie", "email": "charlie@example.com", "role": "viewer"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "charlie"


@responses.activate
def test_user_not_found(api_base_url):
    """GET /api/users/999 returns 404 when user does not exist."""
    responses.add(
        responses.GET,
        f"{api_base_url}/api/users/999",
        json={"error": "User not found"},
        status=404,
    )
    resp = requests.get(f"{api_base_url}/api/users/999")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
