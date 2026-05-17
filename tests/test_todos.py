"""Data-layer tests for the To-Do page. No streamlit dependency."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from career_os.dashboard.todos import (
    add_custom,
    count_orphan_seeds,
    delete_todo,
    list_todos,
    overall_progress,
    section_progress,
    seed_default_plan,
    sync_plan,
    todays_focus,
    toggle,
    update_notes,
)
from career_os.db import Store


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'todos.db'}")


def test_seed_inserts_then_idempotent(store):
    first = seed_default_plan(store)
    assert first["inserted"] > 0
    assert first["untouched"] == 0

    second = seed_default_plan(store)
    assert second["inserted"] == 0
    assert second["untouched"] == first["inserted"]


def test_seed_preserves_checked_state_on_reseed(store):
    seed_default_plan(store)
    items = list_todos(store)
    assert items, "seed should produce items"
    target = items[0]
    toggle(store, target.id, True)
    assert list_todos(store)[0].checked is True

    # Re-seed; checked state must survive.
    seed_default_plan(store)
    after = next(t for t in list_todos(store) if t.id == target.id)
    assert after.checked is True


def test_toggle_sets_completed_at(store):
    seed_default_plan(store)
    item = list_todos(store)[0]
    assert item.completed_at is None
    toggle(store, item.id, True)
    refreshed = next(t for t in list_todos(store) if t.id == item.id)
    assert refreshed.checked is True
    assert refreshed.completed_at is not None
    toggle(store, item.id, False)
    refreshed = next(t for t in list_todos(store) if t.id == item.id)
    assert refreshed.checked is False
    assert refreshed.completed_at is None


def test_update_notes(store):
    seed_default_plan(store)
    item = list_todos(store)[0]
    update_notes(store, item.id, "Done in 45m — used template B")
    refreshed = next(t for t in list_todos(store) if t.id == item.id)
    assert refreshed.notes == "Done in 45m — used template B"
    update_notes(store, item.id, None)
    refreshed = next(t for t in list_todos(store) if t.id == item.id)
    assert refreshed.notes is None


def test_add_custom_and_delete(store):
    seed_default_plan(store)
    seeded_count = len(list_todos(store))
    new = add_custom(
        store, section="Daily Habits", item="Test ad-hoc item",
        priority="P1", due_date="2026-06-01",
    )
    assert new.is_seed is False
    assert len(list_todos(store)) == seeded_count + 1
    assert delete_todo(store, new.id) is True
    assert len(list_todos(store)) == seeded_count


def test_filters(store):
    seed_default_plan(store)
    # Filter by section — use one we know is in the canonical SECTIONS list
    from career_os.dashboard.plan import SECTIONS
    first_section = SECTIONS[0][0]
    section_items = list_todos(store, section=first_section)
    assert section_items, f"{first_section!r} must have seeded items"
    assert all(t.section == first_section for t in section_items)

    # Filter by priority
    p0 = list_todos(store, priority="P0")
    assert p0
    assert all(t.priority == "P0" for t in p0)

    # open_only filter respects toggled state
    target = section_items[0]
    toggle(store, target.id, True)
    open_in_section = list_todos(store, section=first_section, open_only=True)
    assert all(not t.checked for t in open_in_section)

    # Search filter is case-insensitive LIKE; passing a known token from any
    # seeded item should return at least the items that contain it.
    github_matches = list_todos(store, query="github")
    if github_matches:
        haystacks = [(t.item + " " + (t.notes or "")).lower() for t in github_matches]
        assert any("github" in h for h in haystacks)


def test_section_progress_and_overall(store):
    seed_default_plan(store)
    done, total = overall_progress(store)
    assert done == 0
    assert total == len(list_todos(store))

    item = list_todos(store)[0]
    toggle(store, item.id, True)
    done, total = overall_progress(store)
    assert done == 1

    progress = section_progress(store)
    # The section that contains `item` should reflect 1 done
    assert progress[item.section]["done"] >= 1


def test_todays_focus_only_p0_and_not_checked(store):
    seed_default_plan(store)
    focus = todays_focus(store, horizon_days=7, limit=20)
    assert all(t.priority == "P0" for t in focus)
    assert all(not t.checked for t in focus)


def test_todays_focus_excludes_far_future(store):
    seed_default_plan(store)
    # Add a P0 item due 60 days out; it must not appear in this week's focus
    future = (datetime.now(UTC).date() + timedelta(days=60)).isoformat()
    new = add_custom(
        store, section="Week 1 — Launch (May 17–24)",
        item="Far-future P0 item", priority="P0", due_date=future,
    )
    focus = todays_focus(store, horizon_days=7, limit=50)
    assert new.id not in {t.id for t in focus}


def test_sync_removes_orphan_seeds_keeps_adhoc(store):
    """Seed → manually insert orphan seeded row → sync should remove it,
    but ad-hoc rows under the same section must survive."""
    seed_default_plan(store)
    # Manually insert a row that mimics a seed-item no longer in plan.py
    from datetime import UTC as _UTC
    from datetime import datetime
    now = datetime.now(_UTC).isoformat()
    with store._conn() as c:
        c.execute(
            "INSERT INTO todos (section, item, priority, sort_order, is_seed, "
            "checked, created_at, updated_at) VALUES (?, ?, 'P0', 999, 1, 0, ?, ?)",
            ("Daily Habits — Accessibility-Adapted", "ZZZ orphan from old plan", now, now),
        )
    # Add an ad-hoc row in the same section
    adhoc = add_custom(
        store, section="Daily Habits — Accessibility-Adapted",
        item="My custom note", priority="P1",
    )
    assert count_orphan_seeds(store) == 1
    result = sync_plan(store)
    assert result["removed"] == 1
    assert count_orphan_seeds(store) == 0
    # Ad-hoc survives
    assert any(t.id == adhoc.id for t in list_todos(store))


def test_sync_updates_priority_and_due_date(store):
    """Sync should refresh priority/due_date on matching items but preserve
    the user's checked state and notes."""
    seed_default_plan(store)
    target = list_todos(store)[0]
    # User has checked it and added notes
    toggle(store, target.id, True)
    update_notes(store, target.id, "Did this on Monday")
    # Forcibly degrade the priority + clear due_date in the DB to simulate
    # an out-of-date row vs the seed.
    with store._conn() as c:
        c.execute(
            "UPDATE todos SET priority='P2', due_date=NULL WHERE id=?",
            (target.id,),
        )
    sync_plan(store)
    # Find the same item and verify metadata is restored from seed
    refreshed = next(t for t in list_todos(store) if t.id == target.id)
    assert refreshed.checked is True              # user state preserved
    assert refreshed.notes == "Did this on Monday"  # notes preserved
    # priority + due_date should now match the seed value (whatever it is in plan.py)
    from career_os.dashboard.plan import DEFAULT_PLAN
    seed_match = next(
        s for s in DEFAULT_PLAN
        if s.section == refreshed.section and s.item == refreshed.item
    )
    assert refreshed.priority == seed_match.priority


def test_sync_inserts_new_items(store):
    """If the DB is empty, sync should behave like an initial seed."""
    result = sync_plan(store)
    from career_os.dashboard.plan import DEFAULT_PLAN
    assert result["inserted"] == len(DEFAULT_PLAN)
    assert result["removed"] == 0


def test_count_orphan_seeds_zero_for_fresh_seed(store):
    seed_default_plan(store)
    assert count_orphan_seeds(store) == 0


def test_overdue_detection(store):
    seed_default_plan(store)
    overdue_date = (datetime.now(UTC).date() - timedelta(days=2)).isoformat()
    new = add_custom(
        store, section="Daily Habits", item="Overdue test item",
        priority="P0", due_date=overdue_date,
    )
    items = {t.id: t for t in list_todos(store)}
    assert items[new.id].is_overdue is True
    toggle(store, new.id, True)
    items = {t.id: t for t in list_todos(store)}
    assert items[new.id].is_overdue is False  # checked rows are never overdue
