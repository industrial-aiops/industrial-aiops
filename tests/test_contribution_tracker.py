"""Prevent false attribution and conflating closure with upstream acceptance."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "contribution_tracker",
    Path(__file__).parents[1] / "scripts/community/refresh_contribution_tracker.py",
)
tracker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tracker)


def record(kind="pr", role="author"):
    return dict(
        repo="test/project", number=1, kind=kind, role=role, summary="test", next_action="review"
    )


def metadata(**changes):
    result = dict(
        user={"login": "zw008"},
        state="closed",
        draft=False,
        merged_at=None,
        html_url="https://github.com/test/project/pull/1",
        updated_at="2026-11-17T00:00:00Z",
    )
    result.update(changes)
    return result


@pytest.mark.parametrize(
    "changes,status",
    [
        ({}, "closed_unmerged"),
        ({"draft": True}, "closed_unmerged"),
        ({"merged_at": "2026-11-17T00:00:00Z"}, "merged"),
        ({"state": "open", "draft": True}, "draft"),
        ({"state": "open"}, "open"),
    ],
)
def test_pr_state_is_not_inferred_from_closed_alone(monkeypatch, changes, status):
    monkeypatch.setattr(tracker, "api", lambda _: metadata(**changes))
    assert tracker.refresh(record())["status"] == status


def test_other_author_cannot_be_credited_as_ours(monkeypatch):
    monkeypatch.setattr(tracker, "api", lambda _: metadata(user={"login": "other"}))
    with pytest.raises(ValueError, match="Unexpected author"):
        tracker.refresh(record())
    result = tracker.refresh(record(role="related"))
    assert result["actual_author"] == "other"


def test_comment_is_posted_not_merged_when_parent_closed(monkeypatch):
    monkeypatch.setattr(tracker, "api", lambda _: metadata())
    result = tracker.refresh({**record(kind="comment", role="commenter"), "comment_id": 42})
    assert result["status"] == "posted; parent closed"


def test_issue_comment_participation_requires_actual_comment(monkeypatch):
    def get(endpoint):
        return [] if "/comments?" in endpoint else metadata(user={"login": "other"})

    monkeypatch.setattr(tracker, "api", get)
    with pytest.raises(ValueError, match="No account participation"):
        tracker.refresh(record(kind="issue", role="commenter"))
