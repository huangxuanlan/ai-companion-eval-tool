from __future__ import annotations

from fastapi.testclient import TestClient
from main import app
from routers import models_router


def test_legacy_config_export_route_downloads_template():
    with TestClient(app) as client:
        response = client.get("/api/configs/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment;" in response.headers.get("content-disposition", "")


def test_stepfun_flash_hidden_from_public_model_list_but_still_queryable():
    original_adapter = models_router._adapter
    models_router._adapter = None
    try:
        with TestClient(app) as client:
            listing = client.get("/api/models")
            detail = client.get("/api/models/stepfun-flash")
    finally:
        models_router._adapter = original_adapter

    assert listing.status_code == 200
    public_ids = {item["id"] for item in listing.json()["models"]}
    assert "stepfun-flash" not in public_ids

    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == "stepfun-flash"
    assert payload["status"] == "deprecated"
