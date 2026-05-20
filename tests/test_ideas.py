from __future__ import annotations

import pytest

from career_os.dashboard import ideas as ideas_lib
from career_os.db import Store


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'ideas.db'}")


def test_add_and_list_idea(store):
    idea = ideas_lib.add_idea(
        store, title="Build Career-OS in public", hook="One project, three outcomes",
        channel="blog", tags=["build-in-public", "claude"],
    )
    assert idea.id > 0
    rows = ideas_lib.list_ideas(store)
    assert len(rows) == 1
    assert rows[0].title == "Build Career-OS in public"
    assert rows[0].tags == ["build-in-public", "claude"]
    assert rows[0].archived is False


def test_blank_title_rejected(store):
    with pytest.raises(ValueError):
        ideas_lib.add_idea(store, title="   ")


def test_unknown_channel_rejected(store):
    with pytest.raises(ValueError):
        ideas_lib.add_idea(store, title="ok", channel="snapchat")


def test_update_idea(store):
    idea = ideas_lib.add_idea(store, title="orig", channel="blog")
    updated = ideas_lib.update_idea(
        store, idea.id, title="new title", channel="devto", tags=["x"],
    )
    assert updated.title == "new title"
    assert updated.channel == "devto"
    assert updated.tags == ["x"]


def test_archive_and_filter(store):
    a = ideas_lib.add_idea(store, title="A", channel="blog")
    b = ideas_lib.add_idea(store, title="B", channel="blog")
    ideas_lib.archive(store, a.id)
    active = ideas_lib.list_ideas(store)
    assert [r.id for r in active] == [b.id]
    all_rows = ideas_lib.list_ideas(store, include_archived=True)
    assert {r.id for r in all_rows} == {a.id, b.id}


def test_channel_filter(store):
    ideas_lib.add_idea(store, title="A", channel="blog")
    ideas_lib.add_idea(store, title="B", channel="linkedin")
    ideas_lib.add_idea(store, title="C", channel="linkedin")
    rows = ideas_lib.list_ideas(store, channel="linkedin")
    assert {r.title for r in rows} == {"B", "C"}


def test_delete_idea(store):
    idea = ideas_lib.add_idea(store, title="gone soon", channel="blog")
    assert ideas_lib.delete_idea(store, idea.id) is True
    assert ideas_lib.list_ideas(store) == []
    assert ideas_lib.delete_idea(store, idea.id) is False


def test_counts_by_channel(store):
    ideas_lib.add_idea(store, title="A", channel="blog")
    ideas_lib.add_idea(store, title="B", channel="blog")
    ideas_lib.add_idea(store, title="C", channel="linkedin")
    counts = ideas_lib.counts_by_channel(store)
    assert counts["blog"] == 2
    assert counts["linkedin"] == 1
    assert counts["x"] == 0


# ---- project channel -----------------------------------------------------

def test_project_channel_is_registered():
    assert "project" in ideas_lib.CHANNELS


def test_add_idea_with_project_channel(store):
    idea = ideas_lib.add_idea(
        store, title="OSS Laravel + Claude scaffold",
        hook="One-command starter for AI-agent Laravel apps",
        channel="project", tags=["laravel", "claude", "oss"],
    )
    assert idea.channel == "project"
    rows = ideas_lib.list_ideas(store, channel="project")
    assert [r.id for r in rows] == [idea.id]


def test_counts_by_channel_includes_project(store):
    ideas_lib.add_idea(store, title="A", channel="project")
    ideas_lib.add_idea(store, title="B", channel="project")
    ideas_lib.add_idea(store, title="C", channel="blog")
    counts = ideas_lib.counts_by_channel(store)
    assert counts["project"] == 2
    assert counts["blog"] == 1
