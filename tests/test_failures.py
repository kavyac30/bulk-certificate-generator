
from app.models import Certificate, Job, JobStatus
from app.services import job_processor


def _boom_for(bad_name, original):
    def fake_render(data, path):
        if data.recipient_name == bad_name:
            raise RuntimeError("disk exploded")
        return original(data, path)

    return fake_render


def test_unexpected_error_on_one_certificate_does_not_block_others(client, submit, monkeypatch):
    monkeypatch.setattr(
        job_processor, "render_certificate", _boom_for("User 1", job_processor.render_certificate)
    )
    body = submit(recipients=[{"name": f"User {i}", "email": f"u{i}@example.com"} for i in range(4)]).json()

    assert body["status"] == "completed_with_errors"
    assert body["progress"]["succeeded"] == 3
    assert body["progress"]["failed"] == 1

    failed = client.get(f"/api/v1/jobs/{body['id']}/certificates?status=failed").json()["items"]
    assert len(failed) == 1
    assert failed[0]["recipient_name"] == "User 1"
    assert "disk exploded" in failed[0]["error_message"]
    assert failed[0]["download_url"] is None

    ok = client.get(f"/api/v1/jobs/{body['id']}/certificates?status=success").json()["items"]
    assert sorted(c["recipient_name"] for c in ok) == ["User 0", "User 2", "User 3"]


def test_unrenderable_name_fails_only_that_certificate(client, submit):
    recipients = [
        {"name": "Good Person", "email": "good@example.com"},
        {"name": "张伟", "email": "zhang@example.com"},   # passes validation, fails rendering
        {"name": "Another Good", "email": "good2@example.com"},
    ]
    body = submit(recipients=recipients).json()
    assert body["status"] == "completed_with_errors"
    failed = client.get(f"/api/v1/jobs/{body['id']}/certificates?status=failed").json()["items"]
    assert [c["position"] for c in failed] == [1]
    assert "not supported" in failed[0]["error_message"]


def test_job_fails_when_every_certificate_fails(submit, monkeypatch):
    def always_fail(data, path):
        raise RuntimeError("nope")

    monkeypatch.setattr(job_processor, "render_certificate", always_fail)
    body = submit().json()
    assert body["status"] == "failed"
    assert body["progress"]["failed"] == 3


def test_reprocessing_a_finished_job_does_not_regenerate(submit, monkeypatch):
    job_id = submit().json()["id"]
    calls = []
    monkeypatch.setattr(job_processor, "render_certificate", lambda d, p: calls.append(d))
    job_processor.process_job(job_id)
    assert calls == []


def test_resuming_an_interrupted_job_only_generates_pending_certificates(client, submit, db, monkeypatch):
    # Simulate a crash: job created but never processed.
    monkeypatch.setattr("app.routers.jobs.dispatch", lambda job_id: None)
    job_id = submit().json()["id"]

    # One certificate was already done before the "crash".
    first = db.query(Certificate).filter_by(job_id=job_id, position=0).one()
    job_processor._generate_one(db.get(Job, job_id), first)
    db.commit()

    rendered = []
    real = job_processor.render_certificate
    monkeypatch.setattr(job_processor, "render_certificate", lambda d, p: (rendered.append(d.recipient_name), real(d, p))[1])
    job_processor.process_job(job_id)

    assert len(rendered) == 2  # only the two that were still pending
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "completed"
