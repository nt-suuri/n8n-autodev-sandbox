from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sqlalchemy.pool import StaticPool

import sandbox.url_shortener as module
from sandbox.url_shortener import Base, Link, app, get_db


@pytest.fixture(autouse=True)
def test_db(monkeypatch):
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    monkeypatch.setattr(module, "engine", test_engine)

    def override_get_db():
        with Session(test_engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    yield test_engine
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(test_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_create_link(client):
    resp = client.post("/links", json={"url": "https://example.com", "alias": "ex"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["alias"] == "ex"
    assert "example.com" in data["url"]
    assert data["clicks"] == 0
    assert "expires_at" in data


def test_create_link_auto_alias(client):
    resp = client.post("/links", json={"url": "https://example.com"})
    assert resp.status_code == 201
    assert resp.json()["alias"]


def test_create_link_duplicate_alias(client):
    client.post("/links", json={"url": "https://example.com", "alias": "dup"})
    resp = client.post("/links", json={"url": "https://other.com", "alias": "dup"})
    assert resp.status_code == 409


def test_redirect(client):
    client.post("/links", json={"url": "https://example.com", "alias": "go"})
    resp = client.get("/go", follow_redirects=False)
    assert resp.status_code == 302
    assert "example.com" in resp.headers["location"]


def test_redirect_not_found(client):
    resp = client.get("/notexist", follow_redirects=False)
    assert resp.status_code == 404


def test_redirect_increments_clicks(client):
    client.post("/links", json={"url": "https://example.com", "alias": "cnt"})
    client.get("/cnt", follow_redirects=False)
    resp = client.get("/links/cnt/stats")
    assert resp.json()["clicks"] == 1


def test_stats(client):
    client.post("/links", json={"url": "https://example.com", "alias": "st"})
    resp = client.get("/links/st/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["alias"] == "st"
    assert data["clicks"] == 0


def test_stats_not_found(client):
    resp = client.get("/links/noexist/stats")
    assert resp.status_code == 404


def test_redirect_expired_link(client, test_db):
    client.post("/links", json={"url": "https://example.com", "alias": "exp"})
    with Session(test_db) as db:
        link = db.get(Link, "exp")
        link.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    resp = client.get("/exp", follow_redirects=False)
    assert resp.status_code == 404


def test_stats_expired_link(client, test_db):
    client.post("/links", json={"url": "https://example.com", "alias": "expst"})
    with Session(test_db) as db:
        link = db.get(Link, "expst")
        link.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    resp = client.get("/links/expst/stats")
    assert resp.status_code == 404
