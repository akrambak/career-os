"""Pillar 2 — automations runtime tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from career_os import automations as auto_lib
from career_os.automations import HandlerResult, register_handler
from career_os.db import Store


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'auto.db'}")


def _seed(store):
    """Helper: seed defaults explicitly for tests that need them."""
    auto_lib.seed_defaults(store)


# ---- seeding -------------------------------------------------------------

def test_seed_defaults_inserts_rows(store):
    _seed(store)
    rows = auto_lib.list_automations(store)
    names = {a.name for a in rows}
    assert "fetch_hourly" in names
    assert "inbox_generators_15min" in names


def test_seed_defaults_is_idempotent(store):
    _seed(store)
    before = len(auto_lib.list_automations(store))
    auto_lib.seed_defaults(store)
    auto_lib.seed_defaults(store)
    after = len(auto_lib.list_automations(store))
    assert before == after


# ---- CRUD ----------------------------------------------------------------

def test_set_armed_toggles_flag(store):
    _seed(store)
    a = auto_lib.set_armed(store, "fetch_hourly", False)
    assert a.is_armed is False
    a = auto_lib.set_armed(store, "fetch_hourly", True)
    assert a.is_armed is True


def test_update_config_persists(store):
    _seed(store)
    a = auto_lib.update_config(
        store, "score_after_fetch", config={"limit": 100}, interval_minutes=60,
    )
    assert a.config == {"limit": 100}
    assert a.interval_minutes == 60


def test_get_by_name_returns_none_when_missing(store):
    assert auto_lib.get_by_name(store, "nonexistent") is None


# ---- handler registry + execution ---------------------------------------

def test_fire_records_run_and_updates_parent(store):
    # Install a dummy handler we can control.
    @register_handler("test_dummy_ok")
    def _ok(store, config):
        return HandlerResult("ok", "did the thing")

    # Inject a row referencing it.
    now = datetime.now(UTC).isoformat()
    with store._conn() as c:
        c.execute(
            """INSERT INTO automations (name, kind, interval_minutes, config,
               is_armed, created_at, updated_at)
               VALUES ('dummy_a', 'test_dummy_ok', 30, '{}', 1, ?, ?)""",
            (now, now),
        )
    result = auto_lib.fire(store, "dummy_a")
    assert result.status == "ok"
    assert result.summary == "did the thing"
    refreshed = auto_lib.get_by_name(store, "dummy_a")
    assert refreshed.last_status == "ok"
    assert refreshed.next_run_due_at is not None
    runs = auto_lib.list_runs(store, "dummy_a")
    assert len(runs) == 1
    assert runs[0].status == "ok"


def test_fire_records_failure_when_handler_raises(store):
    @register_handler("test_dummy_raise")
    def _bad(store, config):
        raise RuntimeError("boom")

    now = datetime.now(UTC).isoformat()
    with store._conn() as c:
        c.execute(
            """INSERT INTO automations (name, kind, interval_minutes, config,
               is_armed, created_at, updated_at)
               VALUES ('dummy_bad', 'test_dummy_raise', 5, '{}', 1, ?, ?)""",
            (now, now),
        )
    result = auto_lib.fire(store, "dummy_bad")
    assert result.status == "failed"
    # Summary includes the exception type; detail has the message.
    assert "RuntimeError" in result.summary
    assert "boom" in (result.error_detail or "")


def test_fire_unknown_kind_fails_gracefully(store):
    now = datetime.now(UTC).isoformat()
    with store._conn() as c:
        c.execute(
            """INSERT INTO automations (name, kind, interval_minutes, config,
               is_armed, created_at, updated_at)
               VALUES ('orphan', 'not_a_real_kind', 5, '{}', 1, ?, ?)""",
            (now, now),
        )
    result = auto_lib.fire(store, "orphan")
    assert result.status == "failed"
    assert "no handler" in result.summary


def test_fire_skipped_when_handler_returns_skipped(store):
    @register_handler("test_dummy_skip")
    def _skip(store, config):
        return HandlerResult("skipped", "env var missing")

    now = datetime.now(UTC).isoformat()
    with store._conn() as c:
        c.execute(
            """INSERT INTO automations (name, kind, interval_minutes, config,
               is_armed, created_at, updated_at)
               VALUES ('dummy_skip', 'test_dummy_skip', 5, '{}', 1, ?, ?)""",
            (now, now),
        )
    result = auto_lib.fire(store, "dummy_skip")
    assert result.status == "skipped"


# ---- run_due -------------------------------------------------------------

def test_run_due_only_armed_and_overdue(store):
    @register_handler("test_due")
    def _ok(store, config):
        return HandlerResult("ok", "ran")

    # Seed three rows:
    #   armed + overdue → fires
    #   armed + future → skipped
    #   disarmed + overdue → skipped
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    now = datetime.now(UTC).isoformat()
    with store._conn() as c:
        for name, armed, due in [
            ("a_overdue", 1, past),
            ("b_future", 1, future),
            ("c_disarmed", 0, past),
        ]:
            c.execute(
                """INSERT INTO automations (name, kind, interval_minutes, config,
                   is_armed, next_run_due_at, created_at, updated_at)
                   VALUES (?, 'test_due', 30, '{}', ?, ?, ?, ?)""",
                (name, armed, due, now, now),
            )
    results = auto_lib.run_due(store)
    assert set(results.keys()) == {"a_overdue"}


def test_run_due_with_null_next_due_fires(store):
    """A row with next_run_due_at=NULL should also fire (just-created)."""
    @register_handler("test_null_due")
    def _ok(store, config):
        return HandlerResult("ok", "fresh row")

    now = datetime.now(UTC).isoformat()
    with store._conn() as c:
        c.execute(
            """INSERT INTO automations (name, kind, interval_minutes, config,
               is_armed, next_run_due_at, created_at, updated_at)
               VALUES ('fresh', 'test_null_due', 30, '{}', 1, NULL, ?, ?)""",
            (now, now),
        )
    results = auto_lib.run_due(store)
    assert "fresh" in results


def test_run_due_advances_next_run_due_at(store):
    @register_handler("test_advance")
    def _ok(store, config):
        return HandlerResult("ok", "x")

    past = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    now = datetime.now(UTC).isoformat()
    with store._conn() as c:
        c.execute(
            """INSERT INTO automations (name, kind, interval_minutes, config,
               is_armed, next_run_due_at, created_at, updated_at)
               VALUES ('adv', 'test_advance', 60, '{}', 1, ?, ?, ?)""",
            (past, now, now),
        )
    auto_lib.run_due(store)
    refreshed = auto_lib.get_by_name(store, "adv")
    assert refreshed.next_run_due_at > datetime.now(UTC)


# ---- built-in handlers --------------------------------------------------

def test_handler_run_action_generators_returns_ok(store):
    """The action-generators handler is wired to actions.run_generators —
    should always return 'ok' even with zero counts."""
    from career_os.automations import _h_run_action_generators
    result = _h_run_action_generators(store, {})
    assert result.status == "ok"
    assert "0 actions touched" in result.summary or "actions touched" in result.summary


def test_handler_score_skips_when_no_api_key(store, monkeypatch):
    """Patch Settings.load to bypass the .env file, then verify skip."""
    from career_os import automations as auto_mod
    from career_os.config import Settings

    def _stub_load():
        return Settings(
            anthropic_api_key=None, database_url="sqlite:///x.db",
            smtp_provider=None, smtp_api_key=None,
            smtp_from="x", smtp_to="x",
        )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: _stub_load()))
    result = auto_mod._h_score(store, {})
    assert result.status == "skipped"


def test_handler_digest_skips_when_no_smtp(store, monkeypatch):
    from career_os import automations as auto_mod
    from career_os.config import Settings

    def _stub_load():
        return Settings(
            anthropic_api_key=None, database_url="sqlite:///x.db",
            smtp_provider=None, smtp_api_key=None,
            smtp_from="x", smtp_to="x",
        )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: _stub_load()))
    result = auto_mod._h_digest(store, {})
    assert result.status == "skipped"


# ---- known_kinds reports the registry -----------------------------------

def test_known_kinds_includes_builtins():
    kinds = auto_lib.known_kinds()
    for required in ("fetch", "score", "run_action_generators", "recheck", "digest_email"):
        assert required in kinds
