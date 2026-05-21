"""Backlinks module — CRUD, decision logic, rel detection, recheck."""
from __future__ import annotations

import httpx
import pytest
import respx

from career_os import backlinks as bl_lib
from career_os.backlinks.recheck import recheck_all, summarize
from career_os.db import Store


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'bl.db'}")


# ---- helpers -------------------------------------------------------------

def test_domain_of_strips_www():
    assert bl_lib._domain_of("https://www.example.com/x") == "example.com"
    assert bl_lib._domain_of("https://example.com/x") == "example.com"
    assert bl_lib._domain_of("not-a-url") == ""


# ---- CRUD ----------------------------------------------------------------

def test_upsert_creates_new(store):
    bl = bl_lib.upsert_backlink(
        store,
        source_url="https://news.ycombinator.com/item?id=123",
        target_url="https://bak-dev.com/blog/career-os",
        anchor_text="Career-OS",
    )
    assert bl.id > 0
    assert bl.source_domain == "news.ycombinator.com"
    assert bl.status == "live"
    assert bl.rel == "dofollow"


def test_upsert_is_idempotent_on_same_pair(store):
    a = bl_lib.upsert_backlink(
        store, source_url="https://a/1", target_url="https://t",
        anchor_text="original",
    )
    b = bl_lib.upsert_backlink(
        store, source_url="https://a/1", target_url="https://t",
        anchor_text="updated", rel="nofollow",
    )
    assert a.id == b.id
    assert b.anchor_text == "updated"
    assert b.rel == "nofollow"
    assert len(bl_lib.list_backlinks(store)) == 1


def test_upsert_rejects_unknown_rel(store):
    with pytest.raises(ValueError):
        bl_lib.upsert_backlink(
            store, source_url="https://a", target_url="https://b",
            rel="dofollow-but-also-sponsored",
        )


def test_upsert_rejects_unknown_status(store):
    with pytest.raises(ValueError):
        bl_lib.upsert_backlink(
            store, source_url="https://a", target_url="https://b",
            status="schrodinger",
        )


def test_list_filters_by_status(store):
    bl_lib.upsert_backlink(store, source_url="https://a/1",
                          target_url="https://t", status="live")
    bl_lib.upsert_backlink(store, source_url="https://a/2",
                          target_url="https://t", status="dead")
    live = bl_lib.list_backlinks(store, status="live")
    dead = bl_lib.list_backlinks(store, status="dead")
    assert {b.status for b in live} == {"live"}
    assert {b.status for b in dead} == {"dead"}


def test_list_filters_by_rel(store):
    bl_lib.upsert_backlink(store, source_url="https://a/1",
                          target_url="https://t", rel="dofollow")
    bl_lib.upsert_backlink(store, source_url="https://a/2",
                          target_url="https://t", rel="nofollow")
    df = bl_lib.list_backlinks(store, rel="dofollow")
    assert {b.rel for b in df} == {"dofollow"}


def test_list_filters_by_min_da(store):
    bl_lib.upsert_backlink(store, source_url="https://lo/1",
                          target_url="https://t", da_estimate=20)
    bl_lib.upsert_backlink(store, source_url="https://hi/2",
                          target_url="https://t", da_estimate=70)
    hi = bl_lib.list_backlinks(store, min_da=50)
    assert {b.source_url for b in hi} == {"https://hi/2"}


def test_delete(store):
    bl = bl_lib.upsert_backlink(
        store, source_url="https://a", target_url="https://t",
    )
    assert bl_lib.delete_backlink(store, bl.id) is True
    assert bl_lib.list_backlinks(store) == []
    assert bl_lib.delete_backlink(store, bl.id) is False


# ---- update_status -------------------------------------------------------

def test_update_status_resets_attempts(store):
    bl = bl_lib.upsert_backlink(
        store, source_url="https://a", target_url="https://t",
    )
    bl_lib.update_status(store, bl.id, "live", attempts_delta=1)
    bl_lib.update_status(store, bl.id, "live", attempts_delta=1)
    refreshed = bl_lib.update_status(store, bl.id, "live")
    # delta=0 path → reset to 0
    assert refreshed.recheck_attempts == 0


def test_update_status_bumps_attempts(store):
    bl = bl_lib.upsert_backlink(
        store, source_url="https://a", target_url="https://t",
    )
    bl_lib.update_status(store, bl.id, "live", attempts_delta=1)
    bumped = bl_lib.update_status(store, bl.id, "live", attempts_delta=1)
    assert bumped.recheck_attempts == 2


def test_update_rel(store):
    bl = bl_lib.upsert_backlink(
        store, source_url="https://a", target_url="https://t",
    )
    new = bl_lib.update_rel(store, bl.id, "nofollow")
    assert new.rel == "nofollow"


# ---- aggregates ----------------------------------------------------------

def test_counts_by_status(store):
    bl_lib.upsert_backlink(store, source_url="https://a/1",
                          target_url="https://t", status="live")
    bl_lib.upsert_backlink(store, source_url="https://a/2",
                          target_url="https://t", status="live")
    bl_lib.upsert_backlink(store, source_url="https://b/1",
                          target_url="https://t", status="dead")
    counts = bl_lib.counts_by_status(store)
    assert counts["live"] == 2
    assert counts["dead"] == 1
    assert counts["removed"] == 0


def test_dofollow_ratio(store):
    bl_lib.upsert_backlink(store, source_url="https://a/1",
                          target_url="https://t", rel="dofollow")
    bl_lib.upsert_backlink(store, source_url="https://a/2",
                          target_url="https://t", rel="dofollow")
    bl_lib.upsert_backlink(store, source_url="https://b/1",
                          target_url="https://t", rel="nofollow")
    # 2/3 ≈ 0.6667
    ratio = bl_lib.dofollow_ratio(store)
    assert 0.66 < ratio < 0.67


def test_dofollow_ratio_zero_when_empty(store):
    assert bl_lib.dofollow_ratio(store) == 0.0


def test_unique_referring_domains(store):
    bl_lib.upsert_backlink(store, source_url="https://example.com/1",
                          target_url="https://t")
    bl_lib.upsert_backlink(store, source_url="https://example.com/2",
                          target_url="https://t")
    bl_lib.upsert_backlink(store, source_url="https://other.com/3",
                          target_url="https://t")
    assert bl_lib.unique_referring_domains(store) == 2


# ---- decision logic ------------------------------------------------------

def test_decide_404_is_dead():
    decision, _ = bl_lib.decide_from_response(
        target_url="https://t", status_code=404, body=None,
    )
    assert decision == "dead"


def test_decide_410_is_dead():
    decision, _ = bl_lib.decide_from_response(
        target_url="https://t", status_code=410, body=None,
    )
    assert decision == "dead"


def test_decide_200_with_link_is_live():
    decision, _ = bl_lib.decide_from_response(
        target_url="https://t/page",
        status_code=200,
        body="<a href=\"https://t/page\">click</a>",
    )
    assert decision == "live"


def test_decide_200_without_link_is_removed():
    decision, _ = bl_lib.decide_from_response(
        target_url="https://t/page", status_code=200,
        body="<p>nothing here</p>",
    )
    assert decision == "removed"


def test_decide_5xx_is_transient():
    decision, _ = bl_lib.decide_from_response(
        target_url="https://t", status_code=503, body=None,
    )
    assert decision == "transient"


def test_decide_300_is_redirect():
    decision, _ = bl_lib.decide_from_response(
        target_url="https://t", status_code=301, body=None,
        final_url="https://other.com",
    )
    assert decision == "redirect"


def test_decide_http_https_swap_still_live():
    decision, _ = bl_lib.decide_from_response(
        target_url="https://t/page", status_code=200,
        body="link to http://t/page works too",
    )
    assert decision == "live"


# ---- rel detection -------------------------------------------------------

def test_detect_rel_dofollow_default():
    body = '<a href="https://t/page">hi</a>'
    assert bl_lib.detect_rel(body, "https://t/page") == "dofollow"


def test_detect_rel_nofollow():
    body = '<a href="https://t/page" rel="nofollow">hi</a>'
    assert bl_lib.detect_rel(body, "https://t/page") == "nofollow"


def test_detect_rel_sponsored_wins_over_nofollow():
    body = '<a href="https://t/page" rel="nofollow sponsored">hi</a>'
    assert bl_lib.detect_rel(body, "https://t/page") == "sponsored"


def test_detect_rel_ugc():
    body = '<a href="https://t/page" rel="ugc noopener">hi</a>'
    assert bl_lib.detect_rel(body, "https://t/page") == "ugc"


def test_detect_rel_returns_none_when_anchor_missing():
    body = "<p>no link here</p>"
    assert bl_lib.detect_rel(body, "https://t/page") is None


# ---- recheck candidates --------------------------------------------------

def test_candidates_for_recheck_respects_max_age(store):
    from datetime import UTC, datetime, timedelta
    bl_fresh = bl_lib.upsert_backlink(
        store, source_url="https://fresh", target_url="https://t",
    )
    bl_stale = bl_lib.upsert_backlink(
        store, source_url="https://stale", target_url="https://t",
    )
    with store._conn() as c:
        c.execute(
            "UPDATE backlinks SET last_checked_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), bl_fresh.id),
        )
        c.execute(
            "UPDATE backlinks SET last_checked_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(days=30)).isoformat(), bl_stale.id),
        )
    candidates = bl_lib.candidates_for_recheck(store, max_age_days=7)
    assert {b.id for b in candidates} == {bl_stale.id}


def test_candidates_for_recheck_excludes_dead(store):
    bl_lib.upsert_backlink(store, source_url="https://dead",
                          target_url="https://t", status="dead")
    bl_lib.upsert_backlink(store, source_url="https://live",
                          target_url="https://t", status="live")
    candidates = bl_lib.candidates_for_recheck(store)
    sources = {b.source_url for b in candidates}
    assert "https://dead" not in sources
    assert "https://live" in sources


# ---- recheck_all (integration) ------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_recheck_all_marks_404_dead(store):
    bl_lib.upsert_backlink(
        store, source_url="https://a/dead", target_url="https://bak-dev.com/x",
    )
    respx.get("https://a/dead").mock(return_value=httpx.Response(404))
    outcomes = await recheck_all(store)
    assert len(outcomes) == 1
    assert outcomes[0].decision == "dead"
    rows = bl_lib.list_backlinks(store)
    assert rows[0].status == "dead"


@pytest.mark.asyncio
@respx.mock
async def test_recheck_all_keeps_live_when_link_present(store):
    bl_lib.upsert_backlink(
        store, source_url="https://a/live", target_url="https://bak-dev.com/x",
    )
    respx.get("https://a/live").mock(return_value=httpx.Response(
        200, text='<a href="https://bak-dev.com/x">go</a>',
    ))
    outcomes = await recheck_all(store)
    assert outcomes[0].decision == "live"
    rows = bl_lib.list_backlinks(store)
    assert rows[0].status == "live"


@pytest.mark.asyncio
@respx.mock
async def test_recheck_all_marks_removed_when_link_absent(store):
    bl_lib.upsert_backlink(
        store, source_url="https://a/page", target_url="https://bak-dev.com/x",
    )
    respx.get("https://a/page").mock(return_value=httpx.Response(
        200, text="<p>article exists but no link to us</p>",
    ))
    outcomes = await recheck_all(store)
    assert outcomes[0].decision == "removed"


@pytest.mark.asyncio
@respx.mock
async def test_recheck_all_detects_rel_change(store):
    """A once-dofollow link going nofollow updates rel in place."""
    bl = bl_lib.upsert_backlink(
        store, source_url="https://a/page", target_url="https://t/x",
        rel="dofollow",
    )
    respx.get("https://a/page").mock(return_value=httpx.Response(
        200,
        text='<a href="https://t/x" rel="nofollow">link</a>',
    ))
    await recheck_all(store)
    refreshed = bl_lib.get_backlink(store, bl.id)
    assert refreshed.rel == "nofollow"


@pytest.mark.asyncio
@respx.mock
async def test_three_transient_strikes_marks_dead(store):
    bl_lib.upsert_backlink(
        store, source_url="https://a/flaky", target_url="https://t",
    )
    respx.get("https://a/flaky").mock(return_value=httpx.Response(503))
    for _ in range(bl_lib.TRANSIENT_STRIKE_LIMIT):
        await recheck_all(store, max_age_days=-1)
    rows = bl_lib.list_backlinks(store)
    assert rows[0].status == "dead"


def test_summarize_buckets():
    from career_os.backlinks import RecheckOutcome
    outs = [
        RecheckOutcome(1, "live", 200, None),
        RecheckOutcome(2, "dead", 404, "gone"),
        RecheckOutcome(3, "dead", 404, "gone"),
        RecheckOutcome(4, "transient", 503, "flaky"),
    ]
    s = summarize(outs)
    assert s == {"live": 1, "dead": 2, "transient": 1}


# ---- action generator + automation handler -------------------------------

def test_gen_dead_backlinks_emits_actions(store):
    from career_os import actions as actions_lib

    bl_lib.upsert_backlink(
        store, source_url="https://hi-da/page",
        target_url="https://t", status="dead", da_estimate=60,
    )
    bl_lib.upsert_backlink(
        store, source_url="https://lo-da/page",
        target_url="https://t", status="removed", da_estimate=10,
    )
    out = actions_lib.gen_dead_backlinks(store)
    severities = {a.severity for a in out}
    assert "urgent" in severities
    assert "normal" in severities


def test_gen_dead_backlinks_idempotent(store):
    from career_os import actions as actions_lib

    bl_lib.upsert_backlink(
        store, source_url="https://a/page",
        target_url="https://t", status="dead", da_estimate=50,
    )
    actions_lib.gen_dead_backlinks(store)
    actions_lib.gen_dead_backlinks(store)
    rows = actions_lib.list_actions(store, kind="dead_backlink")
    assert len(rows) == 1


def test_backlinks_recheck_handler_registered():
    from career_os import automations
    assert "backlinks_recheck" in automations.known_kinds()


def test_backlinks_recheck_in_default_automations():
    from career_os import automations
    names = [row[0] for row in automations.DEFAULT_AUTOMATIONS]
    assert "backlinks_recheck_weekly" in names
