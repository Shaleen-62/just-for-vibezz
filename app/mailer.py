import logging
import os
from datetime import datetime

import resend
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

resend.api_key = os.getenv("RESEND_API_KEY", "")


def compile_newsletter(episode_data: list[dict]) -> str:
    """
    Compiles episode data into an HTML newsletter string.

    Each dict in episode_data must have:
        series_title, episode_number, mode, content
    """
    if not episode_data:
        return ""

    date_str = datetime.now().strftime("%B %d, %Y")

    episode_blocks = []
    for ep in episode_data:
        content_html = (ep.get("content") or "").replace("\n", "<br>")
        block = f"""
        <div style="margin-bottom: 48px; border-bottom: 1px solid #e0e0e0; padding-bottom: 32px;">
            <h2 style="margin-bottom: 4px; font-size: 22px;">{ep['series_title']}</h2>
            <p style="color: #888; margin-top: 0; font-size: 14px;">
                Episode {ep['episode_number']} &nbsp;·&nbsp; {ep['mode'].upper()}
            </p>
            <div style="line-height: 1.7; font-size: 16px;">{content_html}</div>
        </div>
        """
        episode_blocks.append(block)

    body = "\n".join(episode_blocks)

    return f"""
    <html>
    <body style="font-family: Georgia, serif; max-width: 620px; margin: 0 auto; padding: 32px 20px; color: #1a1a1a;">
        <h1 style="font-size: 28px; margin-bottom: 4px;">NewsLore Weekly</h1>
        <p style="color: #888; font-size: 14px; margin-top: 0;">{date_str} &nbsp;·&nbsp; {len(episode_data)} {'story' if len(episode_data) == 1 else 'stories'}</p>
        <hr style="border: none; border-top: 2px solid #1a1a1a; margin: 24px 0;">
        {body}
        <p style="color: #aaa; font-size: 12px; margin-top: 40px;">Sent by NewsLore</p>
    </body>
    </html>
    """


def send_newsletter(html_content: str) -> bool:
    """Sends the compiled newsletter via Resend. Returns True on success."""
    from_email = os.getenv("NEWSLETTER_FROM_EMAIL", "newsletter@yourdomain.com")
    to_email = os.getenv("NEWSLETTER_TO_EMAIL", "")

    if not to_email:
        logger.error("NEWSLETTER_TO_EMAIL not set in .env")
        return False
    if not resend.api_key:
        logger.error("RESEND_API_KEY not set in .env")
        return False

    subject = f"NewsLore Weekly — {datetime.now().strftime('%B %d, %Y')}"

    try:
        resend.Emails.send({
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        })
        logger.info("Newsletter sent to %s", to_email)
        return True
    except Exception as e:
        logger.error("Failed to send newsletter: %s", e)
        return False
