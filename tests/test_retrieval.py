import csv
import io
import zipfile

from app.services import job_processor


def test_list_certificates_with_filter_and_pagination(client, submit):
    body = submit(recipients=[{"name": f"U{i}", "email": f"u{i}@example.com"} for i in range(5)]).json()
    base = f"/api/v1/jobs/{body['id']}/certificates"

    page = client.get(base, params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5
    assert [c["position"] for c in page["items"]] == [2, 3]

    assert client.get(base, params={"status": "failed"}).json()["total"] == 0
    assert client.get(base, params={"status": "bogus"}).status_code == 422


def test_download_single_certificate(client, submit):
    body = submit().json()
    item = client.get(body["links"]["certificates"]).json()["items"][0]
    resp = client.get(item["download_url"])
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    assert "attachment" in resp.headers["content-disposition"]
    assert ".pdf" in resp.headers["content-disposition"]


def test_download_of_failed_certificate_is_409_with_reason(client, submit):
    body = submit(recipients=[{"name": "Ok", "email": "ok@example.com"}, {"name": "Bad"}]).json()
    failed = client.get(body["links"]["certificates"], params={"status": "failed"}).json()["items"][0]
    resp = client.get(f"/api/v1/jobs/{body['id']}/certificates/{failed['id']}/download")
    assert resp.status_code == 409
    assert "not generated" in resp.json()["detail"]


def test_download_unknown_or_foreign_certificate_is_404(client, submit):
    job_a = submit().json()
    job_b = submit().json()
    cert_of_a = client.get(job_a["links"]["certificates"]).json()["items"][0]
    # right certificate id, wrong job
    assert client.get(f"/api/v1/jobs/{job_b['id']}/certificates/{cert_of_a['id']}/download").status_code == 404
    assert client.get(f"/api/v1/jobs/{job_a['id']}/certificates/nope/download").status_code == 404
    assert client.get("/api/v1/jobs/nope/certificates").status_code == 404


def test_download_all_as_zip_includes_pdfs_and_manifest(client, submit):
    body = submit(recipients=[
        {"name": "Asha Verma", "email": "asha@example.com"},
        {"name": "Ravi Kumar", "email": "ravi@example.com"},
        {"name": "Broken", "email": "nope"},
    ]).json()
    resp = client.get(body["links"]["download_all"])
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    pdfs = [n for n in names if n.endswith(".pdf")]
    assert len(pdfs) == 2
    assert all(zf.read(n).startswith(b"%PDF") for n in pdfs)

    rows = list(csv.DictReader(io.StringIO(zf.read("manifest.csv").decode())))
    assert [r["status"] for r in rows] == ["success", "success", "failed"]
    assert rows[2]["filename"] == "" and "email" in rows[2]["error"]


def test_download_all_is_409_while_job_unfinished(client, submit, monkeypatch):
    monkeypatch.setattr("app.routers.jobs.dispatch", lambda job_id: None)
    body = submit().json()
    resp = client.get(body["links"]["download_all"])
    assert resp.status_code == 409

    job_processor.process_job(body["id"])
    assert client.get(body["links"]["download_all"]).status_code == 200


def test_download_all_404_when_nothing_was_generated(client, submit):
    body = submit(recipients=[{"name": "x"}]).json()
    assert client.get(body["links"]["download_all"]).status_code == 404


def test_download_all_unknown_job_404(client):
    assert client.get("/api/v1/jobs/nope/download").status_code == 404
