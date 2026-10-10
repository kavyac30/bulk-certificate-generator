from app.models import Certificate, Job
from tests.conftest import make_recipients


def test_create_job_returns_202_with_job_details(submit):
    resp = submit()
    assert resp.status_code == 202
    body = resp.json()
    assert body["id"]
    assert body["course_name"] == "Advanced Python Programming"
    assert body["progress"]["total"] == 3
    assert body["links"]["self"] == f"/api/v1/jobs/{body['id']}"


def test_create_job_persists_job_and_one_row_per_recipient(submit, db):
    job_id = submit().json()["id"]
    assert db.get(Job, job_id) is not None
    assert db.query(Certificate).filter_by(job_id=job_id).count() == 3


def test_bulk_request_in_a_single_call(submit):
    resp = submit(recipients=make_recipients(250))
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "completed"
    assert body["progress"] == {
        "total": 250, "succeeded": 250, "failed": 0, "pending": 0, "percent_complete": 100.0
    }


def test_issue_date_defaults_to_today(client, payload):
    payload.pop("issue_date")
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code == 202
    assert resp.json()["issue_date"]


def test_list_jobs(client, submit):
    submit()
    submit()
    resp = client.get("/api/v1/jobs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_unknown_job_returns_404(client):
    assert client.get("/api/v1/jobs/does-not-exist").status_code == 404
