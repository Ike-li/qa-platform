"""Common fixtures for QA Platform test suite."""

import pytest


@pytest.fixture
def api_base_url():
    """Base URL for API tests."""
    return "http://api.example.com"


@pytest.fixture
def mock_auth_token():
    """Sample authentication token."""
    return "test-bearer-token-abc123"


@pytest.fixture
def sample_user_data():
    """Sample user data for API tests."""
    return {
        "id": 1,
        "username": "testuser",
        "email": "test@example.com",
        "role": "tester",
        "is_active": True,
    }


@pytest.fixture
def sample_order_data():
    """Sample order data for API tests."""
    return {
        "id": 101,
        "user_id": 1,
        "items": [{"name": "Widget A", "qty": 3, "price": 9.99}],
        "total": 29.97,
        "status": "pending",
    }
