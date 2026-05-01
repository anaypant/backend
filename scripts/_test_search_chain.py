"""Quick local end-to-end test of the in-house search pipeline (search → blacklist → scrape → relevance)."""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core", "functions", "runner"))
os.environ["ACS_WEB_SEARCH_BACKEND"] = "duckduckgo"

from clients.web_research.search import search_top_results
from clients.web_research.url_blacklist import filter_results
from clients.web_research.browser_fetch import BrowserFetchSession
from clients.web_research.scrape import scrape_many_concurrent
from clients.web_research.relevance import filter_scraped

query = "Warren Buffett real estate investments biography"
print("Query:", query)
print()

hits, backend = search_top_results(query, fetch_count=12)
print(f"Search backend={backend}  raw_hits={len(hits)}")

filtered = filter_results(hits, limit=8)
print(f"After blacklist: {len(filtered)} URLs")
for r in filtered:
    print("  ", r.get("url"))

print()
print("Scraping first 4 URLs...")
session = BrowserFetchSession()
scraped = scrape_many_concurrent(session, filtered[:4])
print(f"Scraped {len(scraped)} pages")
for s in scraped:
    ok = s.get("ok")
    text_len = len(s.get("text") or "")
    url = (s.get("url") or "")[:70]
    print(f"  ok={ok}  text_len={text_len:>6}  {url}")

print()
print("Relevance filtering...")
kept, rejected = filter_scraped(scraped, query, max_pages=4)
print(f"Kept: {len(kept)}   Rejected: {len(rejected)}")
for p in kept:
    rel = p.get("_relevance")
    tlen = len(p.get("text") or "")
    print(f"  KEPT  rel={rel}  text_len={tlen:>6}  {(p.get('url') or '')[:60]}")
for p in rejected:
    reason = p.get("_reject_reason")
    print(f"  REJ   reason={reason:30}  {(p.get('url') or '')[:60]}")
