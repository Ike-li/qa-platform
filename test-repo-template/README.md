# QA Platform Test Repository Template

This repository provides a ready-to-use test template for QA Platform integration testing. It includes API, UI, and performance test scaffolding with Allure reporting support.

## Quick Start

### 1. Register with QA Platform

Before running tests against a live environment, register your test repository:

- Log in to QA Platform at `http://localhost:5000`
- Navigate to **Projects > Register New Repository**
- Enter your repo name and API endpoint URL
- Copy the generated project token and set it as an environment variable:
  ```bash
  export QA_PROJECT_TOKEN="your-token-here"
  ```

### 2. Install Dependencies

```bash
cd test-repo-template
pip install -r requirements.txt
# If you also need UI/performance tests:
# pip install -r requirements-playwright.txt
# pip install -r requirements-locust.txt
```

### 3. Run Tests

```bash
# Run all API tests
pytest api/ -v

# Run with Allure reporting
pytest api/ --alluredir=allure-results
allure serve allure-results
```

## Repository Structure

```
test-repo-template/
├── conftest.py              # Shared fixtures
├── requirements.txt         # Core dependencies
├── api/                     # API integration tests
│   ├── test_users.py
│   ├── test_orders.py
│   └── test_auth.py
├── ui/                      # UI tests (Playwright)
└── performance/             # Performance tests (Locust)
```

## Writing New Tests

1. Place test files in the appropriate directory (`api/`, `ui/`, `performance/`)
2. Use the shared fixtures from `conftest.py` for common data
3. For API tests, use the `responses` library to mock HTTP calls
4. All test functions must start with `test_`
5. Run `pytest` to verify your new tests pass locally before submitting to QA Platform
