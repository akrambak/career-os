from __future__ import annotations

import pytest

from career_os.dashboard import posts as posts_lib
from career_os.db import Store


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'posts.db'}")


def test_add_and_list_post(store):
    post = posts_lib.add_post(
        store, title="First milestone", channel="blog", body="# Hi\n",
    )
    assert post.id > 0
    assert post.status == "drafting"
    assert post.posted_at is None
    rows = posts_lib.list_posts(store)
    assert len(rows) == 1
    assert rows[0].title == "First milestone"


def test_blank_title_rejected(store):
    with pytest.raises(ValueError):
        posts_lib.add_post(store, title="  ")


def test_unknown_channel_rejected(store):
    with pytest.raises(ValueError):
        posts_lib.add_post(store, title="ok", channel="myspace")


def test_status_advance_and_filter(store):
    a = posts_lib.add_post(store, title="A")
    b = posts_lib.add_post(store, title="B")
    posts_lib.set_status(store, a.id, "ready")
    drafting = posts_lib.list_posts(store, status="drafting")
    ready = posts_lib.list_posts(store, status="ready")
    assert [r.id for r in drafting] == [b.id]
    assert [r.id for r in ready] == [a.id]


def test_posted_sets_posted_at(store):
    p = posts_lib.add_post(store, title="X")
    updated = posts_lib.set_status(store, p.id, "posted")
    assert updated.status == "posted"
    assert updated.posted_at is not None


def test_unknown_status_rejected(store):
    p = posts_lib.add_post(store, title="X")
    with pytest.raises(ValueError):
        posts_lib.set_status(store, p.id, "trashed")


def test_update_body(store):
    p = posts_lib.add_post(store, title="X", body="old")
    updated = posts_lib.update_post(store, p.id, body="new body")
    assert updated.body == "new body"


def test_delete_post(store):
    p = posts_lib.add_post(store, title="X")
    assert posts_lib.delete_post(store, p.id) is True
    assert posts_lib.list_posts(store) == []
    assert posts_lib.get_post(store, p.id) is None


def test_counts_by_status(store):
    a = posts_lib.add_post(store, title="A")
    b = posts_lib.add_post(store, title="B")
    posts_lib.set_status(store, a.id, "ready")
    posts_lib.set_status(store, b.id, "posted")
    counts = posts_lib.counts_by_status(store)
    assert counts["drafting"] == 0
    assert counts["ready"] == 1
    assert counts["posted"] == 1
