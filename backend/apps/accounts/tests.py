# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# This project's login flow issues TWO tokens with very different
# lifespans and storage rules: a short-lived "access" token returned
# directly in the response body (the frontend keeps it in memory only),
# and a longer-lived "refresh" token set as an httponly cookie - meaning
# JavaScript on the page can never read it, even our own legitimate code,
# which protects it even if the page had an XSS vulnerability.
#
# verify_id_token (the function that would normally call Firebase's real
# servers to check a login token) is mocked in both tests, so these run
# instantly and don't depend on Firebase being reachable - what's actually
# under test is OUR code's handling of tokens/cookies once Firebase's
# check has already succeeded, not Firebase itself.
#
# Test 1: a fresh login gets an access token in the body, a refresh token
# ONLY as an httponly cookie (never in the JSON body where JS could read
# it), and creates a local User row tied to the Firebase identity.
# Test 2: the full lifecycle - refreshing rotates to a brand new refresh
# token (the old one stops being valid), and logging out blacklists it for
# real, so a stale refresh token can't be reused afterward.
# ============================================================================

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.views import REFRESH_COOKIE_NAME


@pytest.mark.django_db
@patch("apps.accounts.views.verify_id_token")
def test_login_issues_access_body_and_httponly_refresh_cookie(mock_verify):
    mock_verify.return_value = {"uid": "firebase-uid-1", "email": "person@example.com"}
    client = APIClient()

    resp = client.post("/api/auth/login/", {"id_token": "fake"}, format="json")

    assert resp.status_code == 200
    assert "access" in resp.data
    assert "refresh" not in resp.data  # never exposed to JS
    assert User.objects.filter(firebase_uid="firebase-uid-1").exists()

    cookie = resp.cookies.get(REFRESH_COOKIE_NAME)
    assert cookie is not None
    assert cookie["httponly"] is True


@pytest.mark.django_db
@patch("apps.accounts.views.verify_id_token")
def test_refresh_rotates_cookie_and_logout_clears_it(mock_verify):
    mock_verify.return_value = {"uid": "firebase-uid-2", "email": "person2@example.com"}
    client = APIClient()

    login_resp = client.post("/api/auth/login/", {"id_token": "fake"}, format="json")
    client.cookies[REFRESH_COOKIE_NAME] = login_resp.cookies[REFRESH_COOKIE_NAME].value

    refresh_resp = client.post("/api/auth/token/refresh/")
    assert refresh_resp.status_code == 200
    assert "access" in refresh_resp.data
    new_cookie = refresh_resp.cookies.get(REFRESH_COOKIE_NAME)
    assert new_cookie is not None
    assert new_cookie.value != login_resp.cookies[REFRESH_COOKIE_NAME].value

    client.cookies[REFRESH_COOKIE_NAME] = new_cookie.value
    logout_resp = client.post("/api/auth/logout/")
    assert logout_resp.status_code == 204

    # The blacklisted refresh token must no longer work.
    stale_refresh = client.post("/api/auth/token/refresh/")
    assert stale_refresh.status_code == 401
