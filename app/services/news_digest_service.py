"""
Personalized news digest service.

Generates topic queries from the user's profile and core memory,
fetches recent news articles via SearchService, and formats them
as an LLM-ready context block that ProactiveFlows injects into
the morning (or dedicated news) flow prompt.
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.users import User
from .search_service import SearchService


# Topics used when the user profile gives us nothing to work with
_FALLBACK_TOPICS = [
    "technology AI news today",
    "science discoveries today",
    "global economy news today",
]

# Fact text markers that hint at a user interest or professional area
_INTEREST_MARKERS = (
    "интерес",
    "interest",
    "увлечение",
    "hobby",
    "хобби",
    "изучает",
    "studying",
    "работает",
    "works",
    "любит",
    "likes",
    "follow",
    "следит",
    "занимается",
    "profession",
    "профессия",
    "специализация",
)


class NewsDigestService:
    """
    Builds a personalised news digest for a user.

    The digest is returned as a structured text block ready to be injected
    into a ProactiveFlows prompt so the LLM can curate, comment, and
    summarise the articles using the user's full memory context.
    """

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @classmethod
    async def build_digest_context(
        cls,
        session: AsyncSession,
        user: User,
        num_topics: int = 3,
        results_per_topic: int = 3,
    ) -> str:
        """
        Fetch news for ``num_topics`` personalised queries and return a
        formatted text block.  Returns an empty string if no articles
        are found (e.g. API key missing).
        """
        queries = await cls._build_queries(session, user, num_topics)
        grouped: list[dict] = []

        for query in queries:
            try:
                articles = await SearchService.search(
                    query=query,
                    num_results=results_per_topic,
                    search_type="news",
                )
                if articles:
                    grouped.append({"topic": query, "articles": articles})
            except Exception as e:
                logger.warning(
                    "News fetch failed for topic '{}' (user {}): {}", query, user.id, e
                )

        if not grouped:
            logger.info("No news articles found for user {}", user.id)
            return ""

        logger.info(
            "News digest built: {} topic groups, {} total articles for user {}",
            len(grouped),
            sum(len(g["articles"]) for g in grouped),
            user.id,
        )
        return cls._format_digest(grouped)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @classmethod
    async def _build_queries(
        cls, session: AsyncSession, user: User, num_topics: int
    ) -> list[str]:
        """
        Derive up to ``num_topics`` search queries from:
          1. User's occupation (most reliable signal)
          2. Core facts that mention interests / hobbies / profession
          3. Fallback general-interest topics
        """
        queries: list[str] = []

        # 1. Occupation-based query
        occupation = getattr(user, "occupation", None)
        if occupation:
            queries.append(f"{occupation} news today")

        # 2. Interest keywords from core facts
        try:
            from .core_memory_service import CoreMemoryService
            from ..embeddings.gemini_embedding_client import GeminiEmbeddings

            core_service = CoreMemoryService(GeminiEmbeddings())
            facts = await core_service.list_facts_for_user(session, user.id)

            for fact in facts[:30]:
                if len(queries) >= num_topics:
                    break
                fact_text: str = ""
                if hasattr(fact, "fact_text"):
                    fact_text = fact.fact_text or ""
                elif hasattr(fact, "text"):
                    fact_text = fact.text or ""

                fact_lower = fact_text.lower()
                if any(marker in fact_lower for marker in _INTEREST_MARKERS):
                    # Use a trimmed version of the fact as the search seed
                    seed = fact_text.strip()[:80]
                    query = f"news about {seed}"
                    if query not in queries:
                        queries.append(query)
        except Exception as e:
            logger.warning(
                "Could not load core facts for news digest (user {}): {}", user.id, e
            )

        # 3. Fallback topics to fill remaining slots
        for fallback in _FALLBACK_TOPICS:
            if len(queries) >= num_topics:
                break
            if fallback not in queries:
                queries.append(fallback)

        return queries[:num_topics]

    @staticmethod
    def _format_digest(grouped: list[dict]) -> str:
        """
        Format grouped news results into a compact, LLM-readable block.
        Wrapped in XML-style tags so the LLM knows it's injected context.
        """
        sections: list[str] = []
        for group in grouped:
            topic = group["topic"]
            articles = group["articles"]
            lines = [f"<topic>{topic}</topic>"]
            for i, art in enumerate(articles, 1):
                pub = f" [{art['published_date']}]" if art.get("published_date") else ""
                snippet = (art.get("snippet") or "")[:250].strip()
                lines.append(
                    f"  {i}. {art['title']}{pub}\n"
                    f"     URL: {art['url']}\n"
                    f"     {snippet}"
                )
            sections.append("\n".join(lines))

        body = "\n\n".join(sections)
        return f"<NewsDigest>\n{body}\n</NewsDigest>"
