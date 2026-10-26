"""A pre-approval F1 proposal cannot cross a teacher decision revision."""
# Reused pytest fixtures shadow test parameters.
# ruff: noqa: F401, F811

from app.notes_revisions import RevisionStore
from tests.test_notes_revisions import saved_run
from tests.test_notes_suggestions import clean_run, client, made, model, replace, url


def test_ready_proposal_conflicts_after_teacher_decision(clean_run, client, model):
    directory, _ = clean_run
    model.suggestion = {"replacements": [replace("T1.1", "Simpler.")], "insertions": []}
    proposal = made(client)
    assert proposal["status"] == "ready"
    before = list(model.calls)
    approved = client.post(
        url("/topics/T1/approval"),
        json={"base_revision": 0, "action": "approve", "reviewer": "Teacher"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["revision"]["origin"] == "teacher_approval"
    assert model.calls == before
    assert client.get(url(f"/suggestions/{proposal['id']}")).json()["compatible"] is False
    refused = client.post(url(f"/suggestions/{proposal['id']}/apply"), json={"base_revision": 0})
    assert refused.status_code == 409
    assert RevisionStore(directory).head_revision() == 1
