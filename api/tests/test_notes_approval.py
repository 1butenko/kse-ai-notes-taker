"""Teacher decisions bind to saved topic identity and immutable render revisions."""
# Reusing pytest fixtures from the adjacent revision suite shadows test parameters.
# ruff: noqa: F401, F811

import pytest
from fastapi.testclient import TestClient

from app.note_approval import approval_fingerprint, is_teacher_approved
from app.note_assets import import_asset
from app.notes import EvidenceItem, NotationEntry, NotesDocument
from app.notes_revisions import ApprovalAction, InvalidEdit, RevisionConflict, RevisionStore
from app.worker.render import to_quarto, topic_to_quarto
from tests.test_notes_references import image_bytes
from tests.test_notes_revisions import client, model_calls, revision_cli, saved_run, url


def action(base: int, choice: str = "approve") -> ApprovalAction:
    return ApprovalAction(
        base_revision=base, action=choice, reviewer="  Teacher  ", comment=" Check "
    )


def first(document: NotesDocument):
    return document.sections[0].topics[0]


def test_decision_history_render_and_restore(saved_run):
    directory, original = saved_run
    store = RevisionStore(directory)
    approved = store.decide("T1", action(0))
    assert approved.info.origin == "teacher_approval"
    assert approved.info.teacher_topic == "T1"
    assert approved.info.teacher_decision.reviewer == "Teacher"
    assert approved.info.teacher_decision.comment == "Check"
    assert approved.info.teacher_decision.at == first(approved.document).teacher_decision.at
    assert is_teacher_approved(approved.document, first(approved.document))
    section = approved.document.sections[0]
    qmd = topic_to_quarto(approved.document, section, first(approved.document), "en", "html")
    assert "callout-caution" not in qmd
    assert "Thin evidence" not in qmd
    assert "Teacher" not in qmd
    assert first(approved.document).open_issues == first(original).open_issues

    revoked = store.decide("T1", action(1, "revoke"))
    assert revoked.info.origin == "teacher_revocation"
    assert not is_teacher_approved(revoked.document, first(revoked.document))
    assert "callout-caution" in topic_to_quarto(
        revoked.document, revoked.document.sections[0], first(revoked.document), "en", "html"
    )
    assert is_teacher_approved(store.read(1).document, first(store.read(1).document))
    # A metadata-only approved snapshot cannot undo a revocation by restore.
    assert store.restore(1, 2).info.revision == 2
    assert not is_teacher_approved(store.current().document, first(store.current().document))

    with store.transaction(2) as current:
        changed = current.document.model_copy(deep=True)
        first(changed).blocks[0].content = "A different explanation"
        edited = store.commit(current, changed, "manual", ["T1"])
    assert first(edited.document).teacher_decision is None
    restored = store.restore(1, 3)
    assert restored.info.origin == "restore"
    assert first(restored.document).blocks == first(approved.document).blocks
    assert first(restored.document).teacher_decision is None
    assert "callout-caution" in to_quarto(restored.document, "en", "html")


def test_other_topic_and_metadata_only_verify_keep_approval(saved_run):
    directory, _ = saved_run
    store = RevisionStore(directory)
    store.decide("T1", action(0))
    with store.transaction(1) as current:
        changed = current.document.model_copy(deep=True)
        changed.sections[0].topics[1].blocks[0].content = "Other text"
        view = store.commit(current, changed, "manual", ["T2"])
    assert is_teacher_approved(view.document, first(view.document))
    with store.transaction(2) as current:
        changed = current.document.model_copy(deep=True)
        first(changed).rounds += 1
        first(changed).open_issues = []
        first(changed).status = "unresolved"
        view = store.commit(current, changed, "verification", [])
    assert is_teacher_approved(view.document, first(view.document))
    with store.transaction(3) as current:
        changed = current.document.model_copy(deep=True)
        first(changed).evidence.append(
            EvidenceItem(
                chunk_id="c2",
                source=1,
                title="New excerpt",
                page=None,
                role="background",
                relevance=4,
                reason="Fresh",
                text="New evidence",
            )
        )
        view = store.commit(current, changed, "verification", [])
    assert first(view.document).teacher_decision is None


def test_unrelated_source_and_asset_catalog_entries_do_not_invalidate(saved_run):
    directory, _ = saved_run
    store = RevisionStore(directory)
    store.decide("T1", action(0))
    with store.transaction(1) as current:
        changed = current.document.model_copy(deep=True)
        other_source = changed.sources[0].model_copy(deep=True)
        other_source.id = 99
        other_source.title = "An unrelated upload"
        changed.sources.append(other_source)
        changed.assets.append(import_asset(directory, image_bytes(), "unused.png"))
        view = store.commit(current, changed, "manual", [])
    assert is_teacher_approved(view.document, first(view.document))
    with store.transaction(2) as current:
        changed = current.document.model_copy(deep=True)
        changed.sources[1].title = "Edited unrelated upload"
        view = store.commit(current, changed, "manual", [])
    assert is_teacher_approved(view.document, first(view.document))


@pytest.mark.parametrize(
    "placement",
    [
        "content",
        "content_period",
        "block_title",
        "topic_title",
        "section_title",
        "document_title",
        "notation",
    ],
)
def test_direct_source_citation_binds_its_source_metadata(saved_run, placement):
    directory, document = saved_run
    extra = document.sources[0].model_copy(deep=True)
    extra.id = 99
    document.sources.append(extra)
    if placement == "content":
        first(document).blocks[0].content += " See [@src-99]."
    elif placement == "content_period":
        first(document).blocks[0].content += " See @src-99."
    elif placement == "block_title":
        first(document).blocks[0].title = "Source @src-99."
    elif placement == "topic_title":
        first(document).title += " @src-99."
    elif placement == "section_title":
        document.sections[0].title += " @src-99."
    elif placement == "notation":
        document.notation.append(NotationEntry(symbol="q", meaning="See @src-99."))
    else:
        document.title += " @src-99."
    (directory / "notes.json").write_text(document.model_dump_json())
    store = RevisionStore(directory)
    store.decide("T1", action(0))
    with store.transaction(1) as current:
        changed = current.document.model_copy(deep=True)
        changed.sources[1].title = "Edited cited source"
        view = store.commit(current, changed, "manual", [])
    assert first(view.document).teacher_decision is None


@pytest.mark.parametrize(
    "placement",
    ["content", "block_title", "topic_title", "section_title", "document_title", "notation"],
)
def test_unknown_direct_source_fails_closed(saved_run, placement):
    directory, document = saved_run
    if placement == "content":
        first(document).blocks[0].content += " See @src-99."
    elif placement == "block_title":
        first(document).blocks[0].title = "Source @src-99."
    elif placement == "topic_title":
        first(document).title += " @src-99."
    elif placement == "section_title":
        document.sections[0].title += " @src-99."
    elif placement == "notation":
        document.notation.append(NotationEntry(symbol="q", meaning="See @src-99."))
    else:
        document.title += " @src-99."
    (directory / "notes.json").write_text(document.model_dump_json())
    store = RevisionStore(directory)
    with pytest.raises(InvalidEdit):
        store.decide("T1", action(0))
    assert store.head_revision() == 0


@pytest.mark.parametrize(
    "change",
    [
        "title",
        "objective",
        "text",
        "formula",
        "order",
        "citation",
        "evidence",
        "source",
        "language",
        "heading",
        "notation",
        "asset",
    ],
)
def test_topic_identity_changes_invalidate(saved_run, change):
    directory, _ = saved_run
    store = RevisionStore(directory)
    store.decide("T1", action(0))
    with store.transaction(1) as current:
        changed = current.document.model_copy(deep=True)
        topic = first(changed)
        if change == "title":
            topic.title += " revised"
        elif change == "objective":
            topic.objectives.append("New objective")
        elif change == "text":
            topic.blocks[0].content += " revision"
        elif change == "formula":
            topic.blocks[0].content += " The identity is $a^2+b^2=c^2$."
        elif change == "order":
            topic.blocks.reverse()
        elif change == "citation":
            topic.blocks[0].citations = []
        elif change == "evidence":
            topic.evidence[0].text += " revised"
        elif change == "source":
            changed.sources[0].title += " revised"
        elif change == "language":
            changed.language = "uk"
        elif change == "heading":
            changed.sections[0].title += " revised"
        elif change == "notation":
            changed.notation.append(NotationEntry(symbol="q", meaning="New meaning"))
        elif change == "asset":
            asset = import_asset(directory, image_bytes(), "figure.png")
            changed.assets.append(asset)
            topic.blocks[0].content += f"\n\n![Diagram]({asset.path}){{#fig-new}}"
        view = store.commit(current, changed, "manual", ["T1"])
    assert not is_teacher_approved(view.document, first(view.document))
    assert first(view.document).teacher_decision is None


def test_missing_references_and_forged_decision_fail_closed(saved_run):
    directory, _ = saved_run
    store = RevisionStore(directory)
    approved = store.decide("T1", action(0)).document
    assert approval_fingerprint(approved, first(approved))
    forged = approved.model_copy(deep=True)
    first(forged).blocks[0].content += " Changed without commit."
    assert not is_teacher_approved(forged, first(forged))
    assert "callout-caution" in topic_to_quarto(
        forged, forged.sections[0], first(forged), "en", "html"
    )
    missing = approved.model_copy(deep=True)
    missing.sources.clear()
    assert approval_fingerprint(missing, first(missing)) is None
    missing = approved.model_copy(deep=True)
    first(missing).blocks[0].content += "\n\n![Missing](assets/" + "0" * 64 + ".png){#fig-nope}"
    assert approval_fingerprint(missing, first(missing)) is None
    legacy = approved.model_dump()
    del legacy["sections"][0]["topics"][0]["teacher_decision"]
    legacy_document = NotesDocument.model_validate(legacy)
    assert not is_teacher_approved(legacy_document, first(legacy_document))


def test_input_validation_and_stale_commands_do_not_write(saved_run):
    directory, _ = saved_run
    store = RevisionStore(directory)
    for reviewer in ("", "  ", "x" * 121):
        with pytest.raises(ValueError):
            ApprovalAction(base_revision=0, action="approve", reviewer=reviewer)
    with pytest.raises(ValueError):
        ApprovalAction(base_revision=0, action="approve", reviewer="A", comment="x" * 2001)
    assert store.head_revision() == 0
    store.decide("T1", action(0))
    with pytest.raises(RevisionConflict):
        store.decide("T1", action(0, "revoke"))
    with pytest.raises(InvalidEdit):
        store.decide("T1", action(1))
    assert store.head_revision() == 1


def test_api_decision_renders_without_model_calls(
    saved_run, client: TestClient, model_calls, revision_cli
):
    directory, original = saved_run
    body = {"base_revision": 0, "action": "approve", "reviewer": " Teacher ", "comment": "Reviewed"}
    response = client.post(url("/topics/T1/approval"), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["render"]["revision"] == 1
    assert client.get(url("/revisions/1/artifacts/html")).status_code == 200
    assert "Thin evidence" not in client.get(url("/revisions/1/topics/T1/artifacts/html")).text
    assert client.post(url("/topics/T1/approval"), json=body).status_code == 409
    revoked = client.post(
        url("/topics/T1/approval"), json={**body, "base_revision": 1, "action": "revoke"}
    )
    assert revoked.status_code == 200
    assert "Thin evidence" in client.get(url("/revisions/2/topics/T1/artifacts/html")).text
    assert "Thin evidence" not in client.get(url("/revisions/1/topics/T1/artifacts/html")).text
    assert RevisionStore(directory).read(0).document == original
    assert model_calls == []


def test_failed_revoke_render_preserves_decision_and_previous_artifact(
    saved_run, client: TestClient, model_calls, revision_cli
):
    directory, _ = saved_run
    approved = client.post(
        url("/topics/T1/approval"),
        json={"base_revision": 0, "action": "approve", "reviewer": "Teacher"},
    )
    assert approved.status_code == 200
    good_quarto = revision_cli.quarto_bin
    revision_cli.quarto_bin = "/not-installed/quarto"
    revoked = client.post(
        url("/topics/T1/approval"),
        json={"base_revision": 1, "action": "revoke", "reviewer": "Teacher"},
    )
    assert revoked.status_code == 200
    failed_job = client.get(url(f"/render-jobs/{revoked.json()['render']['id']}"))
    assert failed_job.json()["status"] == "failed"
    assert RevisionStore(directory).head_revision() == 2
    assert first(RevisionStore(directory).current().document).teacher_decision.decision == "revoked"
    old = client.get(url("/topics/T1/html"))
    assert old.status_code == 200 and old.headers["x-notes-revision"] == "1"
    assert "Thin evidence" not in old.text
    assert client.get(url("/revisions/2/topics/T1/artifacts/html")).status_code == 404
    revision_cli.quarto_bin = good_quarto
    retry = client.post(url("/revisions/2/render"), json={"formats": ["html", "pdf"]})
    assert retry.status_code == 202
    assert client.get(url(f"/render-jobs/{retry.json()['id']}")).json()["status"] == "done"
    assert "Thin evidence" in client.get(url("/revisions/2/topics/T1/artifacts/html")).text
    assert model_calls == []
