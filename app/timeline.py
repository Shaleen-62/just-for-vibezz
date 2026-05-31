import logging
import re
import time

from app.llm import call_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_BUILD_PROMPT = """
You are building a comprehensive historical timeline for a news topic.

You will receive scraped content from multiple sources. Some accounts may conflict.
Rules:
- Identify facts all sources agree on.
- Where narratives diverge, note it neutrally with the label [DISPUTED].
- Build the timeline from agreed facts only.
- Format each entry as: [DATE] — [EVENT DESCRIPTION]
- Be specific with dates where possible; use approximate ranges (e.g. "Early 2018") only if needed.

TOPIC: {topic}

SOURCE CONTENT:
{source_block}

Respond in EXACTLY this format (do not add any other sections or headers):

TIMELINE:
[your chronological timeline entries here]

CONFIDENCE: [a single integer from 1 to 10 rating how complete and reliable this timeline is]

GAPS:
[list the key pieces of information that are missing or uncertain]
"""

_MERGE_PROMPT = """
You are updating an existing historical timeline with new information.

TOPIC: {topic}

EXISTING TIMELINE:
{existing_content}

NEW SOURCE CONTENT (scraped since the last build):
{source_block}

Rules:
- Insert new events into the correct chronological position.
- Where new sources conflict with the existing timeline, note it with [DISPUTED].
- Do not remove existing entries unless they are directly contradicted by multiple new sources.
- Keep the same [DATE] — [EVENT] format throughout.

Respond in EXACTLY this format:

TIMELINE:
[the updated chronological timeline]

CONFIDENCE: [a single integer from 1 to 10]

GAPS:
[updated list of key gaps or uncertainties]
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_sources(scraped_content: dict[str, str]) -> str:
    """Formats the scraped dict into a clearly labelled block for the LLM."""
    blocks = []
    for source, text in scraped_content.items():
        blocks.append(f"--- SOURCE: {source} ---\n{text.strip()}\n")
    return "\n".join(blocks)


def _parse_response(raw: str) -> dict:
    """
    Parses the LLM response into {content, confidence_score, gaps}.
    Falls back gracefully if the LLM doesn't follow the format exactly.
    """
    content = raw.strip()
    confidence_score = None
    gaps = None

    # Extract CONFIDENCE
    conf_match = re.search(r"CONFIDENCE:\s*(\d+)", raw, re.IGNORECASE)
    if conf_match:
        confidence_score = int(conf_match.group(1))

    # Extract GAPS block
    gaps_match = re.search(r"GAPS:\s*(.*?)(?:CONFIDENCE:|$)", raw, re.IGNORECASE | re.DOTALL)
    if gaps_match:
        gaps = gaps_match.group(1).strip()

    # Extract TIMELINE block (everything between TIMELINE: and CONFIDENCE:)
    timeline_match = re.search(r"TIMELINE:\s*(.*?)(?:CONFIDENCE:|$)", raw, re.IGNORECASE | re.DOTALL)
    if timeline_match:
        content = timeline_match.group(1).strip()

    return {
        "content": content,
        "confidence_score": confidence_score,
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def build_master_timeline(topic: str, scraped_content: dict[str, str]) -> dict:
    """
    Builds a master timeline from scraped content using the LLM.

    Returns:
        {
            "content": str,           — the full timeline text
            "confidence_score": int,  — LLM self-rated 1-10
            "gaps": str,              — what the LLM flagged as missing
            "llm_time_ms": int,       — time spent on the LLM call
        }
    """
    logger.info("Building master timeline for: %s (%d sources)", topic, len(scraped_content))
    source_block = _format_sources(scraped_content)
    prompt = _BUILD_PROMPT.format(topic=topic, source_block=source_block)

    t0 = time.time()
    raw = call_llm(prompt)
    llm_time_ms = int((time.time() - t0) * 1000)

    result = _parse_response(raw)
    result["llm_time_ms"] = llm_time_ms

    logger.info(
        "Timeline built in %dms — confidence: %s, gaps: %s",
        llm_time_ms,
        result["confidence_score"],
        "yes" if result["gaps"] else "none",
    )
    return result


def merge_timeline(
    topic: str,
    existing_content: str,
    new_scraped_content: dict[str, str],
) -> dict:
    """
    Merges new scraped content into an existing master timeline (Pipeline C).

    Returns the same shape as build_master_timeline.
    """
    logger.info("Merging timeline for: %s (%d new sources)", topic, len(new_scraped_content))
    source_block = _format_sources(new_scraped_content)
    prompt = _MERGE_PROMPT.format(
        topic=topic,
        existing_content=existing_content,
        source_block=source_block,
    )

    t0 = time.time()
    raw = call_llm(prompt)
    llm_time_ms = int((time.time() - t0) * 1000)

    result = _parse_response(raw)
    result["llm_time_ms"] = llm_time_ms

    logger.info("Timeline merged in %dms — confidence: %s", llm_time_ms, result["confidence_score"])
    return result
