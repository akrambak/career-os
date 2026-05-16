from __future__ import annotations

from .models import Channel, Profile

DEFAULT_PROFILE = Profile(
    headline=(
        "Senior Fullstack Engineer (8y) layering AI agents on top of production "
        "e-commerce / SMB work. Claude SDK + OSS LLMs. Building Career-OS in public."
    ),
    years_experience=8,
    proven_stack=[
        "PHP", "Laravel", "CodeIgniter",
        "PrestaShop (1.6 / 1.7 / 8.x, modules + themes)",
        "Vue", "modern JS", "HTML5/CSS3",
        "Flutter", "Dart", "Firebase",
        "REST APIs", "Postgres", "MySQL",
    ],
    new_stack=[
        "Python", "Anthropic Claude SDK", "agentic patterns", "MCP",
        "Ollama", "vLLM", "evaluations / prompt regression testing",
    ],
    target_channels=[Channel.FT, Channel.FREELANCE],
    deal_breakers=[
        "On-site required",
        "Crypto / web3 speculative projects",
        "Hourly < $60/hr equivalent for freelance",
        "Roles requiring legacy .NET / Java enterprise only",
    ],
    nice_to_haves=[
        "AI / LLM in the brief",
        "E-commerce, SMB tooling, or developer tooling domain",
        "Async-first culture",
        "European time zones (FR/EN bilingual)",
        "Freelance: retainer or fixed scope, 2+ weeks",
    ],
)
