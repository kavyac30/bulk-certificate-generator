import pytest

from app.config import settings
from tests.conftest import make_recipients

@pytest.mark.parametrize(
    "overrides",
    [
        {"recipients": []},                      # empty list
        {"recipients": "not-a-list"},            # wrong type
        {"course_name": ""},                     # blank
        {"course_name": "   "},                  # whitespace only
        {"issued_by": ""},
        {"issue_date": "not-a-date"},
        {"course_name": "x" * 151},              # too long
    ],
)
def test_invalid_request_is_rejected(submit, overrides):
    assert submit(**overrides).status_code == 422


@pytest.mark.parametrize("missing", ["course_name", "issued_by", "recipients"])
def test_missing_required_field_is_rejected(client, payload, missing):
    payload.pop(missing)
    assert client.post("/api/v1/jobs", json=payload).status_code == 422


def test_too_many_recipients_is_rejected(submit):
    too_many = [{"name": "A", "email": "a@example.com"}] * (settings.max_recipients_per_job + 1)
    assert submit(recipients=too_many).status_code == 422


# ---- Recipient-level validation: bad entries fail, good ones still succeed -- #
def test_invalid_recipients_are_reported_but_valid_ones_still_generated(client, submit):
    recipients = [
        {"name": "Valid One", "email": "valid1@example.com"},       # 0 ok
        {"name": "No Email"},                                       # 1 missing email
        {"name": "", "email": "blank@example.com"},                 # 2 blank name
        {"name": "Bad Email", "email": "not-an-email"},             # 3 invalid email
        {"name": 12345, "email": "num@example.com"},                # 4 name not a string
        "just a string",                                            # 5 not an object
        {"name": "Valid Two", "email": "valid2@example.com"},       # 6 ok
    ]
    body = submit(recipients=recipients).json()

    assert body["status"] == "completed_with_errors"
    assert body["progress"]["succeeded"] == 2
    assert body["progress"]["failed"] == 5

    failed = client.get(f"/api/v1/jobs/{body['id']}/certificates?status=failed").json()
    assert [c["position"] for c in failed["items"]] == [1, 2, 3, 4, 5]
    assert all(c["error_message"].startswith("Validation failed") for c in failed["items"])
    assert "email" in failed["items"][0]["error_message"]
    assert all(c["download_url"] is None for c in failed["items"])


def test_duplicate_email_in_same_job_is_rejected(client, submit):
    recipients = [
        {"name": "First", "email": "same@example.com"},
        {"name": "Second", "email": "SAME@example.com"},   # case-insensitive duplicate
    ]
    body = submit(recipients=recipients).json()
    assert body["progress"]["succeeded"] == 1
    failed = client.get(f"/api/v1/jobs/{body['id']}/certificates?status=failed").json()["items"]
    assert failed[0]["position"] == 1
    assert "Duplicate" in failed[0]["error_message"]


def test_whitespace_is_trimmed_and_email_lowercased(client, submit):
    body = submit(recipients=[{"name": "  Asha Verma  ", "email": " ASHA@Example.COM "}]).json()
    item = client.get(f"/api/v1/jobs/{body['id']}/certificates").json()["items"][0]
    assert item["recipient_name"] == "Asha Verma"
    assert item["recipient_email"] == "asha@example.com"


def test_job_with_no_valid_recipients_fails_immediately(submit):
    body = submit(recipients=[{"name": "x"}, {"email": "y@example.com"}]).json()
    assert body["status"] == "failed"
    assert body["progress"]["failed"] == 2
    assert body["completed_at"] is not None


def test_name_too_long_is_a_recipient_error(submit):
    body = submit(recipients=[{"name": "N" * 71, "email": "long@example.com"}]).json()
    assert body["progress"]["failed"] == 1
