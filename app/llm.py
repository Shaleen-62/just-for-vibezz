import logging
import os

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
_MODEL = "llama-3.3-70b-versatile"


def call_llm(prompt: str) -> str:
    """Single entry point for all LLM calls. Swap provider here if needed."""
    logger.debug("Sending prompt to LLM (%d chars)", len(prompt))
    response = _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
