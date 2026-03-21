"""Regression tests for pairs API endpoints.

Covers:
- BUGFIX-01: FREE-tier pair limit enforced server-side (HTTP 403)
- BUGFIX-02: Soft-delete commit persists (is_active=0 readable after DELETE)
"""

import json


def _insert_active_pair(conn, leader: str, follower: str) -> int:
    """Insert an active ticker pair directly and return its id."""
    cursor = conn.execute(
        "INSERT INTO ticker_pairs (leader, follower, is_active) VALUES (?, ?, 1)",
        (leader, follower),
    )
    conn.commit()
    return cursor.lastrowid


def test_free_tier_limit(api_client, tmp_db):
    """POST /api/pairs returns 403 when FREE tier already has 5 active pairs."""
    # Insert exactly 5 active pairs directly into the DB
    pairs = [
        ("AAPL", "MSFT"),
        ("AAPL", "GOOG"),
        ("AAPL", "AMZN"),
        ("AAPL", "TSLA"),
        ("AAPL", "NVDA"),
    ]
    for leader, follower in pairs:
        _insert_active_pair(tmp_db, leader, follower)

    # Attempt to add a 6th pair via the API
    response = api_client.post(
        "/api/pairs",
        json={"leader": "AAPL", "followers": ["META"]},
    )

    assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
    detail = response.json().get("detail", "")
    assert "Free tier" in detail, f"Expected 'Free tier' in detail, got: {detail!r}"


def test_delete_commits(api_client, tmp_db):
    """DELETE /api/pairs soft-deletes and commits — is_active=0 readable after call."""
    # Insert one active pair and capture its id
    pair_id = _insert_active_pair(tmp_db, "SPY", "QQQ")

    # Call the delete endpoint with the pair id.
    # starlette TestClient.delete() has no body parameter; use request() directly.
    response = api_client.request(
        "DELETE",
        "/api/pairs",
        json={"ids": [pair_id]},
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert response.json()["removed"] == 1

    # Open a new cursor on the same connection to verify the commit persisted
    row = tmp_db.execute(
        "SELECT is_active FROM ticker_pairs WHERE leader = ? AND follower = ?",
        ("SPY", "QQQ"),
    ).fetchone()
    assert row is not None, "Row should still exist after soft-delete"
    assert row["is_active"] == 0, f"Expected is_active=0, got {row['is_active']}"
