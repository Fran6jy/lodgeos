"""Tests for per-user dashboard access tokens (privacy isolation)."""

import time

import pytest

from openclaw.storage.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def db(tmp_path):
    return SQLiteAdapter(str(tmp_path / "t.db"))


def test_token_resolves_to_its_user(db):
    token = db.create_dashboard_token("alice", ttl_seconds=60)
    assert db.resolve_dashboard_token(token) == "alice"


def test_each_user_gets_distinct_token(db):
    t_alice = db.create_dashboard_token("alice")
    t_bob = db.create_dashboard_token("bob")
    assert t_alice != t_bob
    # Critical privacy guarantee: a token only ever resolves to its own user.
    assert db.resolve_dashboard_token(t_alice) == "alice"
    assert db.resolve_dashboard_token(t_bob) == "bob"


def test_expired_token_denied(db):
    token = db.create_dashboard_token("alice", ttl_seconds=0)
    time.sleep(0.01)
    assert db.resolve_dashboard_token(token) is None


def test_unknown_token_denied(db):
    assert db.resolve_dashboard_token("not-a-real-token") is None


def test_regenerating_replaces_prior_token(db):
    old = db.create_dashboard_token("alice")
    new = db.create_dashboard_token("alice")
    assert db.resolve_dashboard_token(old) is None  # old link revoked
    assert db.resolve_dashboard_token(new) == "alice"
