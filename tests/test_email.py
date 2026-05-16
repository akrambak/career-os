from __future__ import annotations

import pytest

from career_os.digest.email import DigestEmailer, _markdown_to_minimal_html


def test_rejects_unknown_provider():
    with pytest.raises(ValueError):
        DigestEmailer(provider="mailchimp", api_key="x", sender="a@x", recipient="b@x")


def test_rejects_empty_key():
    with pytest.raises(ValueError):
        DigestEmailer(provider="resend", api_key="", sender="a@x", recipient="b@x")


def test_rejects_missing_endpoints():
    with pytest.raises(ValueError):
        DigestEmailer(provider="resend", api_key="x", sender="", recipient="b@x")


def test_markdown_to_html_escapes_and_renders():
    md = "# Title\n\n## Sub\n\n- one\n- two\n\nA paragraph with **bold** and < a >.\n"
    html = _markdown_to_minimal_html(md)
    assert "<h1>Title</h1>" in html
    assert "<h2>Sub</h2>" in html
    assert "<ul>" in html and "<li>one</li>" in html
    assert "<strong>bold</strong>" in html
    # Tag-escaped angle brackets:
    assert "&lt; a &gt;" in html
