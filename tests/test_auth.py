"""
Security tests for dashboard authentication.
"""
import pytest
from fastapi.testclient import TestClient
from dashboard import app

client = TestClient(app)

def test_unauthenticated_pending_trades():
    resp = client.get("/api/pending_trades")
    assert resp.status_code == 401

def test_unauthenticated_approve():
    resp = client.post("/api/approve/1")
    assert resp.status_code == 401

def test_unauthenticated_reject():
    resp = client.post("/api/reject/1")
    assert resp.status_code == 401

def test_unauthenticated_trace():
    resp = client.get("/api/trace/1")
    assert resp.status_code == 401

def test_login_success():
    resp = client.post("/api/login", json={"username": "operator", "password": "operator123"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

def test_login_failure():
    resp = client.post("/api/login", json={"username": "operator", "password": "wrong"})
    assert resp.status_code == 401

def test_authenticated_approve():
    # Login first
    client.post("/api/login", json={"username": "operator", "password": "operator123"})
    # Fetch CSRF token from the session (we can just use the session's csrf_token)
    # Since CSRF is disabled in test mode, we can skip the header.
    resp = client.post("/api/approve/999999")
    # It should return 404 or error, but NOT 401
    assert resp.status_code != 401
    # Should return a JSON error
    assert resp.json().get("status") == "ERROR" or resp.json().get("detail") == "Trade not found"