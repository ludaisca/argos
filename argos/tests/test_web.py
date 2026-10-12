"""UI web: endpoints principales (FastAPI TestClient con home aislado)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from argos.config import ArgosConfig  # noqa: E402
from argos.web import server as web_server  # noqa: E402
from argos.web.server import create_app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_status_empty_home(client: TestClient, isolated_home: Path) -> None:
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["llm"]["llm_configured"] is False
    assert data["home"] == str(isolated_home)
    assert data["brief"]["source"] == "none"
    assert set(data["sessions"]) == {"instagram", "facebook", "linkedin", "x"}
    assert data["busy"] is False


def test_index_and_meta(client: TestClient) -> None:
    home = client.get("/")
    assert home.status_code == 200
    assert "Argos" in home.text

    data = client.get("/api/meta").json()
    assert data["platforms"] == [
        "facebook",
        "instagram",
        "linkedin",
        "places",
        "x",
        "youtube",
    ]
    assert data["platform_labels"]["places"] == "Lugares (OSM/Google)"
    assert "ig_profile" in data["target_types"]["instagram"]
    assert "fb_page" in data["target_types"]["facebook"]
    assert data["target_types"]["places"] == ["places_search"]
    assert data["target_types"]["youtube"] == ["yt_channel", "yt_search", "yt_video"]
    assert data["kinds"]["ig_search"] == ["posts", "users"]
    assert data["kinds"]["x_search"] == ["top", "latest"]


def test_brief_roundtrip(client: TestClient, isolated_home: Path) -> None:
    payload = {
        "job": "prueba",
        "objective": "investigar algo",
        "questions": ["¿uno?", "¿dos?"],
        "platforms": ["instagram"],
        "targets": [{"type": "ig_profile", "value": "nasa", "limit": 3}],
        "max_targets": 4,
    }
    r = client.put("/api/brief", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["platforms"] == ["instagram"]
    assert (isolated_home / "brief.yaml").is_file()

    got = client.get("/api/brief").json()
    assert got["source"] == "home"
    assert got["objective"] == "investigar algo"
    assert got["targets"] == payload["targets"]


def test_brief_invalid_platform_falls_back_to_all(client: TestClient) -> None:
    r = client.put(
        "/api/brief",
        json={"job": "x", "objective": "x", "platforms": ["tiktok"]},
    )
    assert r.status_code == 200
    assert r.json()["platforms"] == [
        "facebook",
        "instagram",
        "linkedin",
        "places",
        "x",
        "youtube",
    ]


def test_brief_requires_objective(client: TestClient) -> None:
    r = client.put("/api/brief", json={"objective": "   ", "job": "x"})
    assert r.status_code == 422


def test_settings_roundtrip_and_mask(client: TestClient) -> None:
    r = client.put(
        "/api/settings",
        json={
            "llm_api_key": "clave-secreta-123456",
            "llm_model": "modelo-x",
            "interval_hours": 6,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["llm_key_set"] is True
    assert "clave-secreta-123456" not in json.dumps(data)
    assert data["llm_key_masked"].startswith("clav")
    assert data["llm_model"] == "modelo-x"
    assert data["interval_hours"] == 6.0
    assert ArgosConfig.load().get("llm_api_key") == "clave-secreta-123456"


def test_settings_test_llm_without_key(client: TestClient) -> None:
    assert client.post("/api/settings/test-llm").status_code == 400


def test_jobs_create_list_delete(client: TestClient, isolated_home: Path) -> None:
    r = client.post(
        "/api/jobs",
        json={
            "job": "Tema X",
            "objective": "investigar X",
            "filename": "tema-x",
            "platforms": ["facebook"],
        },
    )
    assert r.status_code == 200, r.text
    assert (isolated_home / "jobs" / "tema-x.yaml").is_file()

    listing = client.get("/api/jobs").json()
    assert [j["file"] for j in listing["pending"]] == ["tema-x.yaml"]
    assert listing["pending"][0]["job"] == "Tema X"

    duplicate = client.post(
        "/api/jobs", json={"job": "Tema X", "objective": "x", "filename": "tema-x"}
    )
    assert duplicate.status_code == 409

    assert client.delete("/api/jobs/tema-x.yaml").status_code == 200
    assert client.get("/api/jobs").json()["pending"] == []


def test_jobs_reject_path_traversal(client: TestClient) -> None:
    assert client.delete("/api/jobs/..%2Fconfig.yaml").status_code in (400, 404)


def test_run_lifecycle_with_fake_launcher(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    launched: dict[str, Any] = {}

    def fake_launch(
        self: Any, args: list[str], *, kind: str, label: str
    ) -> web_server.ProcRecord:
        record = web_server.ProcRecord(id="rec1", kind=kind, label=label, status="ok")
        record.result = {"run_name": "fake-run", "results": [{"status": "ok"}]}
        launched["args"] = args
        self.records[record.id] = record
        return record

    monkeypatch.setattr(web_server.UIService, "launch", fake_launch)
    assert client.put("/api/brief", json={"objective": "x", "job": "j"}).status_code == 200

    r = client.post("/api/run", json={"source": "brief"})
    assert r.status_code == 200, r.text
    assert launched["args"] == ["agent", "run", "--json"]

    state = client.get("/api/run/rec1").json()
    assert state["status"] == "ok"
    assert state["result"]["run_name"] == "fake-run"


def test_run_conflict_when_busy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    service = client.app.state.service  # type: ignore[attr-defined]
    service.records["b1"] = web_server.ProcRecord(
        id="b1", kind="run", label="x", status="running"
    )
    r = client.post("/api/run", json={"source": "brief"})
    assert r.status_code == 409


def test_run_requires_brief(client: TestClient) -> None:
    r = client.post("/api/run", json={"source": "brief"})
    assert r.status_code == 422


def test_run_job_validates_name(client: TestClient) -> None:
    r = client.post("/api/run", json={"source": "job", "job": "../../evil.yaml"})
    assert r.status_code in (400, 404)


def test_daemon_lifecycle_fake(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_launch(
        self: Any, args: list[str], *, kind: str, label: str
    ) -> web_server.ProcRecord:
        record = web_server.ProcRecord(id="d1", kind=kind, label=label)
        self.records[record.id] = record
        return record

    monkeypatch.setattr(web_server.UIService, "launch", fake_launch)
    r = client.post("/api/daemon", json={"interval_hours": 5})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "d1"

    state = client.get("/api/daemon").json()
    assert state["record"]["label"] == "daemon cada 5.0 h"

    assert client.delete("/api/daemon").json() == {"running": False}


def test_runs_listing_detail_and_files(client: TestClient, isolated_home: Path) -> None:
    run = isolated_home / "runs" / "demo-20260101-000000"
    (run / "data").mkdir(parents=True)
    (run / "run.json").write_text(
        json.dumps(
            {
                "job": "demo",
                "objective": "objetivo demo",
                "plan_source": "brief",
                "platforms": ["instagram"],
                "results": [{"target": "ig_profile:nasa", "status": "ok"}],
            }
        ),
        encoding="utf-8",
    )
    (run / "analysis.md").write_text("# Hola\n\n- uno\n", encoding="utf-8")
    (run / "data" / "posts.jsonl").write_text("{}\n", encoding="utf-8")

    listing = client.get("/api/runs").json()["runs"]
    assert listing[0]["name"] == "demo-20260101-000000"
    assert listing[0]["ok"] == 1
    assert listing[0]["analysis"] is True

    detail = client.get("/api/runs/demo-20260101-000000").json()
    assert "# Hola" in detail["analysis"]
    assert any(f["path"] == "data/posts.jsonl" for f in detail["files"])

    file = client.get("/api/runs/demo-20260101-000000/file/analysis.md")
    assert file.status_code == 200
    assert "Hola" in file.text

    traversal = client.get(
        "/api/runs/demo-20260101-000000/file/%2e%2e%2f%2e%2e%2fconfig.yaml"
    )
    assert traversal.status_code in (400, 404)


def test_missing_run_returns_404(client: TestClient) -> None:
    assert client.get("/api/runs/no-existe").status_code == 404
    assert client.get("/api/runs/no%20existe").status_code in (400, 404)


def test_places_search_and_save(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    from argos import places as places_mod
    from argos.models import Place

    def fake_search(query: str, **kwargs: Any) -> places_mod.PlacesResult:
        return places_mod.PlacesResult(
            places=[Place(source="osm", id="node/9", name="Café X", query=query)],
            actions=1,
            detail="1 lugar (test)",
            center=places_mod.GeoPoint(label="Puebla", lat=19.0, lon=-98.2),
        )

    monkeypatch.setattr(places_mod, "search", fake_search)
    r = client.post(
        "/api/places/search", json={"query": "cafés", "location": "Puebla, MX"}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["places"][0]["name"] == "Café X"
    assert data["center"]["lat"] == 19.0

    r = client.post(
        "/api/places/save",
        json={"query": "cafés", "location": "Puebla, MX", "places": data["places"]},
    )
    assert r.status_code == 200, r.text
    run_name = r.json()["run_name"]
    run_dir = isolated_home / "runs" / run_name
    assert (run_dir / "places.jsonl").is_file()
    assert (run_dir / "report.md").is_file()
    listing = client.get("/api/runs").json()["runs"]
    assert any(item["name"] == run_name for item in listing)


def test_places_search_rejects_unknown_provider(client: TestClient) -> None:
    r = client.post("/api/places/search", json={"query": "x", "provider": "bing"})
    assert r.status_code == 422


def test_places_save_requires_places(client: TestClient) -> None:
    r = client.post("/api/places/save", json={"query": "x", "places": []})
    assert r.status_code == 422


def test_leads_sources_toggle_roundtrip(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argos.places as places_mod
    import argos.searxng as searxng_mod

    monkeypatch.setattr(searxng_mod, "search", lambda *a, **k: ["hit"])
    monkeypatch.setattr(
        places_mod, "reverse_geocode", lambda *a, **k: {"city": "Puebla", "state": "Puebla"}
    )

    data = client.get("/api/leads/sources").json()
    by_id = {item["id"]: item for item in data["sources"]}
    assert set(by_id) == {"searxng", "bing", "facebook", "nominatim", "gmaps"}
    assert all(item["enabled"] for item in data["sources"])
    assert by_id["searxng"]["status"] == "ok"
    assert by_id["gmaps"]["status"] == "on-demand"

    r = client.put("/api/leads/sources", json={"enabled": {"gmaps": False, "facebook": False}})
    assert r.status_code == 200
    assert r.json()["enabled"]["gmaps"] is False

    data = client.get("/api/leads/sources").json()
    by_id = {item["id"]: item for item in data["sources"]}
    assert by_id["gmaps"]["enabled"] is False
    assert by_id["gmaps"]["status"] == "off"
    assert by_id["facebook"]["enabled"] is False
    assert by_id["facebook"]["status"] == "off"

    service = client.app.state.service  # type: ignore[attr-defined]
    persisted = service.config.get("leads_sources")
    assert persisted == {
        "searxng": True,
        "bing": True,
        "facebook": False,
        "gmaps": False,
        "nominatim": True,
    }

    assert (
        client.put("/api/leads/sources", json={"enabled": {"nope": True}}).status_code == 422
    )
