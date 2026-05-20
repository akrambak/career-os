from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime
from html import unescape

import httpx

from ..models import Channel, JobPost
from ..salary import parse as parse_salary
from ..watermark import WatermarkCtx
from .base import Scraper

ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
ALGOLIA_ITEM = "https://hn.algolia.com/api/v1/items/{}"


class HNFreelancerScraper(Scraper):
    """
    HN monthly 'Freelancer? Seeking freelancer?' thread — top-level comments
    starting with SEEKING WORK are freelancers; SEEKING FREELANCER are clients.

    For Career-OS we mine SEEKING FREELANCER (the actual leads) — these are
    SMB / startup founders posting briefs we can pitch.
    """

    key = "hn_freelancer"

    async def fetch(
        self,
        client: httpx.AsyncClient,
        watermarks: WatermarkCtx | None = None,
    ) -> AsyncIterator[JobPost]:
        story_id = await self._find_latest_thread(client)
        if story_id is None:
            return

        # Watermark per story_id: thread roll-over (new month) → fresh state.
        # Algolia /items/<id> doesn't accept numericFilters server-side, so
        # we filter created_at_i client-side using the cursor.
        wm_key = f"{self.key}:{story_id}"
        prior = watermarks.get(wm_key) if watermarks else None
        cursor = _safe_int(prior.last_cursor) if prior else None

        r = await client.get(
            ALGOLIA_ITEM.format(story_id),
            headers=self._client_headers(),
            timeout=30.0,
        )
        r.raise_for_status()
        thread = r.json()
        max_created_at = cursor or 0
        yielded_any = False
        for child in thread.get("children", []) or []:
            created_at_i = _safe_int(child.get("created_at_i"))
            if cursor is not None and created_at_i is not None and created_at_i <= cursor:
                continue
            job = self._parse(child, story_id)
            if job:
                yielded_any = True
                yield job
                if created_at_i is not None and created_at_i > max_created_at:
                    max_created_at = created_at_i

        if watermarks:
            status = "ok" if yielded_any else ("unchanged" if cursor else "ok")
            watermarks.record(
                wm_key, status=status,
                last_cursor=str(max_created_at) if max_created_at else None,
            )

    async def _find_latest_thread(self, client: httpx.AsyncClient) -> int | None:
        params = {
            "query": "Freelancer? Seeking freelancer?",
            "tags": "story,author_whoishiring",
            "hitsPerPage": 5,
        }
        r = await client.get(
            ALGOLIA_SEARCH,
            params=params,
            headers=self._client_headers(),
            timeout=30.0,
        )
        r.raise_for_status()
        for hit in r.json().get("hits", []):
            if "Seeking freelancer" in (hit.get("title") or ""):
                return int(hit["objectID"])
        return None

    def _parse(self, comment: dict, story_id: int) -> JobPost | None:
        text = comment.get("text") or ""
        if not text:
            return None
        plain = unescape(re.sub(r"<[^>]+>", " ", text))
        plain = re.sub(r"\s+", " ", plain).strip()
        if not plain.upper().startswith("SEEKING FREELANCER"):
            return None
        cid = comment.get("id")
        if not cid:
            return None
        created = comment.get("created_at")
        posted_at: datetime | None = None
        if created:
            try:
                posted_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None
        extracted = _extract_fields(plain)
        title = _first_line(plain, max_len=120) or "HN Freelance lead"
        tags = ["freelance", "hn"] + extracted["stack"]
        parsed_comp = (
            parse_salary(extracted["budget"]) if extracted["budget"] else None
        )
        return JobPost(
            source=self.key,
            external_id=str(cid),
            url=f"https://news.ycombinator.com/item?id={cid}",
            title=title,
            company=comment.get("author"),
            location=extracted["location"] or "Remote",
            description=_structured_description(plain, extracted),
            tags=tags,
            channel=Channel.FREELANCE,
            compensation=extracted["budget"],
            parsed_compensation=parsed_comp if parsed_comp and parsed_comp.known else None,
            posted_at=posted_at,
        )


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_line(text: str, max_len: int) -> str:
    after = text[len("SEEKING FREELANCER"):].lstrip(" |:-")
    for sep in [".", "|", " - ", "—"]:
        if sep in after:
            after = after.split(sep, 1)[0].strip()
            break
    return after[:max_len].strip()


# Tech-stack tokens we care about — match exactly so we don't false-positive
# on substrings (e.g., "go" inside "google").
_STACK_TOKENS = {
    "python", "django", "flask", "fastapi", "celery",
    "php", "laravel", "symfony", "prestashop", "wordpress", "magento", "shopify",
    "node", "nodejs", "node.js", "typescript", "javascript", "deno", "bun",
    "react", "vue", "svelte", "angular", "nextjs", "next.js", "nuxt",
    "go", "golang", "rust", "ruby", "rails", "elixir", "phoenix",
    "java", "kotlin", "spring", "scala", "clojure",
    "flutter", "dart", "swift", "swiftui", "android", "ios",
    "postgres", "postgresql", "mysql", "mariadb", "sqlite", "mongodb",
    "redis", "elasticsearch", "clickhouse", "kafka",
    "aws", "gcp", "azure", "kubernetes", "k8s", "docker", "terraform",
    "ai", "llm", "openai", "anthropic", "claude", "gpt", "rag",
    "langchain", "llamaindex", "ollama", "vllm", "mcp",
    "graphql", "rest", "websockets", "grpc",
}

_RATE_SUFFIX = r"(?:\s*/\s*(?:hr|hour|h|day|d|week|wk))?"
_RANGE = r"(?:\s*[-–to]+\s*[$€]?\d{2,3}(?:[,.]?\d{3})?)?"

_BUDGET_PATTERNS = [
    re.compile(rf"\$\d{{2,3}}(?:[,.]?\d{{3}})?{_RANGE}{_RATE_SUFFIX}", re.IGNORECASE),
    re.compile(rf"€\d{{2,3}}(?:[,.]?\d{{3}})?{_RANGE}{_RATE_SUFFIX}", re.IGNORECASE),
    re.compile(
        r"\b\d{2,3}\s*[-–]\s*\d{2,3}\s*(?:USD|EUR|GBP)\s*/\s*(?:hr|hour|h|day|d)\b",
        re.IGNORECASE,
    ),
]

_LOCATION_PATTERNS = [
    re.compile(r"\bREMOTE(?:\s+ONLY)?\b", re.IGNORECASE),
    re.compile(r"\bLOCATION\s*:?\s*([A-Z][A-Za-z ,/]+?)(?:\.|$|\||\n)"),
    re.compile(r"\b(EU|EMEA|USA?|UK|US|CA|Canada|Europe|Worldwide)\b"),
]

_EMAIL = r"[\w.+-]+@[\w.-]+\.\w+"
_CONTACT_PATTERNS = [
    re.compile(rf"\bEMAIL\s*:?\s*({_EMAIL})", re.IGNORECASE),
    re.compile(
        rf"\b(?:CONTACT|REACH ME|REACH OUT)\s*(?:AT|VIA)?\s*:?\s*({_EMAIL})",
        re.IGNORECASE,
    ),
    re.compile(rf"\b({_EMAIL})\b"),
]


def _extract_fields(plain: str) -> dict:
    lower = plain.lower()
    stack = sorted({tok for tok in _STACK_TOKENS if re.search(rf"\b{re.escape(tok)}\b", lower)})

    budget: str | None = None
    for pat in _BUDGET_PATTERNS:
        m = pat.search(plain)
        if m:
            budget = m.group(0).strip()
            break

    location: str | None = None
    for pat in _LOCATION_PATTERNS:
        m = pat.search(plain)
        if m:
            location = (m.group(1) if m.lastindex else m.group(0)).strip()
            break

    contact: str | None = None
    for pat in _CONTACT_PATTERNS:
        m = pat.search(plain)
        if m:
            contact = m.group(1).strip()
            break

    return {"stack": stack, "budget": budget, "location": location, "contact": contact}


def _structured_description(plain: str, fields: dict) -> str:
    lines = []
    if fields["stack"]:
        lines.append(f"[stack] {', '.join(fields['stack'])}")
    if fields["budget"]:
        lines.append(f"[budget] {fields['budget']}")
    if fields["location"]:
        lines.append(f"[location] {fields['location']}")
    if fields["contact"]:
        lines.append(f"[contact] {fields['contact']}")
    header = " · ".join(lines)
    return f"{header}\n\n{plain}" if header else plain
