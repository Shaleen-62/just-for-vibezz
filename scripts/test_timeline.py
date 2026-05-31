import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
logging.basicConfig(level=logging.INFO)

from app.scraper import scrape_wikipedia
from app.timeline import build_master_timeline

print("--- Scraping Wikipedia ---")
text = scrape_wikipedia("Brexit")
print(f"Got {len(text)} chars\n")

print("--- Building timeline ---")
result = build_master_timeline("Brexit", {"wikipedia": text})

print(f"\nConfidence score : {result['confidence_score']}")
print(f"LLM time         : {result['llm_time_ms']}ms")
print(f"\nTIMELINE (first 600 chars):\n{result['content'][:600]}")
print(f"\nGAPS:\n{result['gaps'][:300] if result['gaps'] else 'None'}")
