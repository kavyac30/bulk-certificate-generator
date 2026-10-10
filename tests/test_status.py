import time

from app.config import settings
from app.services import job_processor


def test_pending_job_reports_zero_progress(client, submit, monkeypatch):
    monkeypatch.setattr("app.routers.jobs.dispatch", lambda job_id: None)  # nobody processes it
    body = submit().json()
    assert body["status"] == "pending"
    assert body["progress"] == {"total": 3, "succeeded": 0, "failed": 0, "pending": 3, "percent_complete": 0.0}
    assert body["started_at"] is None and body["completed_at"] is None

    job_processor.process_job(body["id"])
    after = client.get(f"/api/v1/jobs/{body['id']}").json()
    assert after["status"] == "completed"
    assert after["progress"]["percent_complete"] == 100.0
    assert after["completed_at"] is not None


def test_progress_is_visible_while_job_is_processing(client, submit, monkeypatch):
    monkeypatch.setattr("app.routers.jobs.dispatch", lambda job_id: None)
    body = submit(recipients=[{"name": f"U{i}", "email": f"u{i}@example.com"} for i in range(4)]).json()

    snapshots = []
    real = job_processor.render_certificate

    def spy(data, path):
        snapshots.append(client.get(f"/api/v1/jobs/{body['id']}").json())
        return real(data, path)

    monkeypatch.setattr(job_processor, "render_certificate", spy)
    job_processor.process_job(body["id"])

    assert [s["status"] for s in snapshots] == ["processing"] * 4
    assert [s["progress"]["succeeded"] for s in snapshots] == [0, 1, 2, 3]
    assert snapshots[2]["progress"]["percent_complete"] == 50.0


def test_status_counts_mix_of_success_and_failure(submit):
    body = submit(recipients=[
        {"name": "Ok", "email": "ok@example.com"},
        {"name": "Bad", "email": "bad"},
    ]).json()
    assert body["status"] == "completed_with_errors"
    assert body["progress"] == {"total": 2, "succeeded": 1, "failed": 1, "pending": 0, "percent_complete": 100.0}


def test_background_mode_processes_job_asynchronously(client, payload, monkeypatch):
    monkeypatch.setattr(settings, "processing_mode", "background")
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    deadline = time.time() + 15
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/v1/jobs/{job_id}").json()
        if status["status"] in ("completed", "completed_with_errors", "failed"):
            break
        time.sleep(0.05)
    assert status["status"] == "completed"
    assert status["progress"]["succeeded"] == 3
