"""Tests for /api/auth endpoints."""

import responses
import requests


@responses.activate
def test_login_success(api_base_url):
    """POST /api/auth/login returns a token on valid credentials."""
    responses.add(
        responses.POST,
        f"{api_base_url}/api/auth/login",
        json={"token": "eyJhbGciOiJIUzI1NiJ9.dGVzdA.valid", "expires_in": 3600},
        status=200,
    )
    resp = requests.post(
        f"{api_base_url}/api/auth/login",
        json={"username": "testuser", "password": "correct-password"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["expires_in"] == 3600


@responses.activate
def test_login_invalid(api_base_url):
    """POST /api/auth/login returns 401 on invalid credentials."""
    responses.add(
        responses.POST,
        f"{api_base_url}/api/auth/login",
        json={"error": "Invalid username or password"},
        status=401,
    )
    resp = requests.post(
        f"{api_base_url}/api/auth/login",
        json={"username": "testuser", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert "error" in data


@responses.activate
def test_token_refresh(api_base_url, mock_auth_token):
    """POST /api/auth/refresh returns a new token."""
    responses.add(
        responses.POST,
        f"{api_base_url}/api/auth/refresh",
        json={"token": "new-refreshed-token-xyz", "expires_in": 3600},
        status=200,
    )
    resp = requests.post(
        f"{api_base_url}/api/auth/refresh",
        headers={"Authorization": f"Bearer {mock_auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["token"] != mock_auth_token
