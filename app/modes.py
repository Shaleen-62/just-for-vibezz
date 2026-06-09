from typing import Optional

MODES = {
    "gossip": (
        "You are a gossipy friend who has been following this story obsessively. "
        "Explain it like you're spilling tea to someone who just tuned in. "
        "Be dramatic, be catty, keep the facts straight."
    ),
    "dramatic": (
        "You are a documentary narrator. Retell this as a gripping chapter in a larger saga. "
        "Use tension, contrast, and weight. Think Ken Burns."
    ),
    "explainer": (
        "You are a patient, witty teacher explaining this to a curious 17-year-old "
        "who knows nothing about it. Simple language, real stakes, no condescension."
    ),
    "cartoon": (
        "You are a children's fable writer. Turn the key players into animal characters, "
        "the conflict into a simple moral story. Keep it accurate underneath the whimsy."
    ),
}


def build_story_prompt(
    series_title: str,
    episode_number: int,
    timeline_content: str,
    mode: str,
    previous_story: Optional[str] = None,
) -> str:
    recap = ""
    if previous_story:
        recap = (
            f"PREVIOUS EPISODE SUMMARY:\n{previous_story}\n\n"
            f"Begin this episode with a one-sentence "
            f"\"Previously on {series_title}...\" recap.\n"
        )

    return f"""
{recap}
MASTER TIMELINE:
{timeline_content}

YOUR TASK:
Write Episode {episode_number} of "{series_title}" in the following style:
{MODES[mode]}

REQUIREMENTS:
- Start with "Previously on..." recap if a previous episode exists.
- Draw from the timeline above — stay factually grounded.
- Focus on one interesting angle or period from the timeline per episode.
  Do not try to cover everything — leave material for future episodes.
- End with: "Next week, we get into..." — hint at what's coming.
- Keep it under 500 words.
""".strip()
