"""Retailer robots.txt fetcher and parser.

Respects retailer crawl directives per EV-3 from PRD Section 9.5:
- Do not crawl disallowed paths
- Honour crawl-delay directives
- Cache robots.txt for the session duration

Per PRD Section 9.5 (EV-3).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    pass


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class RobotsDotTxt:
    """Parsed robots.txt content for a single retailer host.

    Attributes:
        host: The retailer host, e.g. "target.com".
        raw: The raw robots.txt text.
        rules: Mapping of user-agent (lowercased, "*" = all) to list of
            disallow/allow patterns.
        crawl_delay: Optional crawl delay in seconds per request.
        user_agents: Set of all user-agent strings declared in the file.
    """

    host: str
    raw: str
    rules: dict[str, list[str]] = field(default_factory=dict)
    crawl_delay: float | None = None
    user_agents: set[str] = field(default_factory=set)
    _allow_cache: dict[tuple[str, str], bool] = field(default_factory=dict)

    def is_allowed(self, path: str, user_agent: str = "*") -> bool:
        """Return True if the path is allowed for the given user-agent.

        Follows Google-style precedence:
        1. Most specific allow/disallow rule wins for the matching UA
        2. '*' rules apply when no UA-specific rule exists
        3. If no rule matches, the path is allowed by default
        """
        cache_key = (path, user_agent.lower())
        if cache_key in self._allow_cache:
            return self._allow_cache[cache_key]

        applicable: list[str] = []
        ua_key = user_agent.lower()
        if ua_key in self.rules:
            applicable.extend(self.rules[ua_key])
        elif "*" in self.rules:
            applicable.extend(self.rules["*"])

        result = self._match_rules(path, applicable)
        self._allow_cache[cache_key] = result
        return result

    def get_crawl_delay(self, user_agent: str = "*") -> float | None:
        """Return the crawl delay in seconds for the given user-agent."""
        ua_key = user_agent.lower()
        if ua_key in self._crawl_delays:
            return self._crawl_delays[ua_key]
        if "*" in self._crawl_delays:
            return self._crawl_delays["*"]
        return None

    _crawl_delays: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def _match_rules(path: str, patterns: list[str]) -> bool:
        """Return True if path is allowed given a list of patterns.

        Patterns are processed in order; most specific match wins.
        """
        allowed = True  # Default allow when no rule matches

        for pattern in patterns:
            clean = pattern.strip()
            if not clean or clean.startswith("#"):
                continue
            lower = clean.lower()
            if lower.startswith("disallow:"):
                clean = clean.split(":", 1)[1].strip()
            elif lower.startswith("allow:"):
                clean = clean.split(":", 1)[1].strip()
            # else: bare pattern treated as disallow if not empty

            if not clean:
                # Empty disallow = allow all
                continue

            if _path_matches(path, clean):
                if lower.startswith("allow:"):
                    allowed = True
                else:
                    allowed = False

        return allowed


# ── Compiled pattern helpers ───────────────────────────────────────────────────


_pattern_cache: dict[str, re.Pattern[str]] = {}


def _compile_pattern(pattern: str) -> re.Pattern[str]:
    """Convert a robots.txt glob pattern to a regex.

    robots.txt supports two wildcard forms:
    - ``*``  — matches any sequence of characters EXCEPT ``/``
    - ``**`` — matches any sequence of characters INCLUDING ``/``

    The ``$`` anchor pins the pattern to the end of the path.
    """
    escaped = re.escape(pattern)
    # ``**`` → ``.*``  (match any characters including slashes)
    # Handle ``**`` FIRST so it isn't caught by the single-asterisk handler
    if chr(92) + "*" + chr(92) + "*" in escaped:
        escaped = escaped.replace(chr(92) + "*" + chr(92) + "*", ".*")
    else:
        # ``*`` → ``[^/]*`` (match any characters except slash)
        # re.escape('*') produces backslash-asterisk, so replace that pair
        escaped = escaped.replace(chr(92) + "*", r"[^/]*")
    # ``$`` — end-of-string anchor
    escaped = escaped.replace(chr(92) + "$", "$")
    return re.compile(escaped)


def _path_matches(path: str, pattern: str) -> bool:
    """Return True if path matches the robots.txt pattern."""
    if pattern not in _pattern_cache:
        _pattern_cache[pattern] = _compile_pattern(pattern)
    return _pattern_cache[pattern].match(path) is not None


# ── Parser ───────────────────────────────────────────────────────────────────


def parse_robots_txt(raw: str, host: str) -> RobotsDotTxt:
    """Parse raw robots.txt text into a RobotsDotTxt dataclass."""
    rules: dict[str, list[str]] = {}
    crawl_delays: dict[str, float] = {}
    user_agents: set[str] = set()
    current_ua: str | None = None

    for line in raw.splitlines():
        original = line.rstrip()
        line_lower = original.lower().strip()

        if not line_lower or line_lower.startswith("#"):
            continue

        if line_lower.startswith("user-agent:"):
            ua = line_lower.split(":", 1)[1].strip()
            current_ua = ua
            if ua not in rules:
                rules[ua] = []
            user_agents.add(ua)
        elif line_lower.startswith("disallow:") or line_lower.startswith("allow:"):
            directive_lower, _, value = original.partition(":")
            value = value.strip()
            if current_ua:
                rules[current_ua].append(f"{directive_lower}:{value}")
            elif "*" in rules:
                rules["*"].append(f"{directive_lower}:{value}")
            else:
                rules.setdefault("*", []).append(f"{directive_lower}:{value}")
        elif line_lower.startswith("crawl-delay:"):
            _, _, delay_str = original.partition(":")
            try:
                delay = float(delay_str.strip())
                if current_ua:
                    crawl_delays[current_ua] = delay
                else:
                    crawl_delays["*"] = delay
            except ValueError:
                pass
        # Ignore all other directives (sitemap, host, etc.)

    rt = RobotsDotTxt(host=host, raw=raw)
    rt.rules = rules
    rt.user_agents = user_agents
    rt._crawl_delays = crawl_delays
    return rt


# ── Manager ───────────────────────────────────────────────────────────────────


class RobotsDotTxtManager:
    """Fetches and caches robots.txt per retailer host.

    Fetches robots.txt on first request, caches for ``cache_ttl_seconds``.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        cache_ttl_seconds: float = 3600.0,
    ) -> None:
        self._client = http_client
        self._cache: dict[str, RobotsDotTxt] = {}
        self._cache_ttl = cache_ttl_seconds
        self._cache_timestamps: dict[str, float] = {}

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
            headers={"User-Agent": "PokeDropBot/1.0 (robots.txt fetcher)"},
        )

    async def get(self, base_url: str) -> RobotsDotTxt | None:
        """Fetch and cache robots.txt for the host in ``base_url``."""
        host = _extract_host(base_url)
        if not host:
            return None

        if self._is_cached(host):
            return self._cache[host]

        rt = await self._fetch(host, base_url)
        if rt is not None:
            self._cache[host] = rt
            self._cache_timestamps[host] = time.monotonic()
        return rt

    async def is_url_allowed(self, url: str, user_agent: str = "*") -> bool:
        """Return True if the URL path is allowed to be crawled.

        Returns True when robots.txt cannot be fetched (fail open).
        """
        rt = await self.get(url)
        if rt is None:
            return True  # Fail open
        return rt.is_allowed(_extract_path(url), user_agent=user_agent)

    async def get_crawl_delay(
        self, base_url: str, user_agent: str = "*"
    ) -> float | None:
        """Return crawl delay in seconds, or None if not specified."""
        rt = await self.get(base_url)
        if rt is None:
            return None
        return rt.get_crawl_delay(user_agent=user_agent)

    def _is_cached(self, host: str) -> bool:
        if host not in self._cache:
            return False
        age = time.monotonic() - self._cache_timestamps.get(host, 0)
        return age < self._cache_ttl

    async def _fetch(self, host: str, base_url: str) -> RobotsDotTxt | None:
        """Fetch robots.txt from the standard location."""
        robots_url = f"{_normalize_url(base_url)}/robots.txt"
        client = self._client or self._default_client()
        close_client = self._client is None

        try:
            response = await client.get(robots_url)
            if response.status_code == 404:
                return RobotsDotTxt(host=host, raw="", rules={})
            response.raise_for_status()
            return parse_robots_txt(response.text, host)
        except Exception:
            return None
        finally:
            if close_client:
                await client.aclose()

    async def _invalidate(self, base_url: str) -> None:
        """Clear cache entry for the given base URL (test hook)."""
        host = _extract_host(base_url)
        if host is None:
            return
        self._cache.pop(host, None)
        self._cache_timestamps.pop(host, None)


# ── URL helpers ───────────────────────────────────────────────────────────────


def _extract_host(url: str) -> str | None:
    """Extract host from a URL, e.g. 'https://www.target.com/foo' → 'www.target.com'."""
    try:
        return httpx.URL(url).host
    except Exception:
        return None


def _extract_path(url: str) -> str:
    """Extract path+query from a URL, e.g. 'https://target.com/a/b?x=1' → '/a/b?x=1'."""
    try:
        parsed = httpx.URL(url)
        path = str(parsed.path)
        query = parsed.query.decode() if parsed.query else ""
        return path + ("?" + query if query else "")
    except Exception:
        return "/"


def _normalize_url(url: str) -> str:
    """Return scheme+host for a URL, e.g. 'https://www.target.com:8080/a' → 'https://www.target.com'."""
    try:
        parsed = httpx.URL(url)
        return f"{parsed.scheme}://{parsed.host}"
    except Exception:
        return url


__all__ = [
    "RobotsDotTxt",
    "RobotsDotTxtManager",
    "parse_robots_txt",
]
