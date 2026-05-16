from __future__ import annotations

from .base import Scraper
from .hn_freelancer import HNFreelancerScraper
from .hn_whoishiring import HNWhoIsHiringScraper
from .remoteok import RemoteOKScraper
from .remotive import RemotiveScraper
from .weworkremotely import WeWorkRemotelyScraper

REGISTRY: dict[str, type[Scraper]] = {
    cls.key: cls
    for cls in (
        RemoteOKScraper,
        WeWorkRemotelyScraper,
        RemotiveScraper,
        HNFreelancerScraper,
        HNWhoIsHiringScraper,
    )
}


def get_scraper(key: str) -> Scraper:
    if key not in REGISTRY:
        raise KeyError(f"Unknown scraper: {key!r}. Known: {sorted(REGISTRY)}")
    return REGISTRY[key]()
