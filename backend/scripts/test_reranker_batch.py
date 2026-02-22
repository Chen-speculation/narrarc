"""Test whether SiliconFlow Reranker supports multiple documents per request."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx
from narrative_mirror.config import load_config

cfg = load_config(os.path.join(os.path.dirname(__file__), "..", "config.yml"))
r = cfg.reranker

base_url = r.base_url.rstrip("/")
headers = {
    "Authorization": f"Bearer {r.api_key}",
    "Content-Type": "application/json",
}

print(f"Using model: {r.model}")
print(f"Base URL: {base_url}")
print()

# Test 1: Single query + 3 documents
print("=== Test 1: One query + 3 documents ===")
payload = {
    "model": r.model,
    "query": "两个人感情变冷",
    "documents": [
        "他们开始争吵，关系变得紧张",
        "今天天气晴朗",
        "她不再主动发消息，回复也越来越慢",
    ],
}

try:
    resp = httpx.post(
        f"{base_url}/rerank",
        headers=headers,
        json=payload,
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    print(f"Response status: {resp.status_code}")
    print(f"Number of results: {len(results)}")
    print(f"Results: {results}")

    if len(results) == 3:
        print("\n✓ BATCH SUPPORTED: Returns one score per document")
        scores = [x.get("relevance_score") for x in results]
        print(f"Scores: {scores}")
    elif len(results) == 1:
        print("\n✗ BATCH NOT SUPPORTED: Returns only 1 score for 3 documents")
    else:
        print(f"\n? Unexpected: {len(results)} results for 3 documents")

except Exception as e:
    print(f"Error: {e}")

print()

# Test 2: Single query + 1 document (baseline)
print("=== Test 2: One query + 1 document (baseline) ===")
payload2 = {
    "model": r.model,
    "query": "两个人感情变冷",
    "documents": ["他们开始争吵，关系变得紧张"],
}

try:
    resp2 = httpx.post(
        f"{base_url}/rerank",
        headers=headers,
        json=payload2,
        timeout=30.0,
    )
    resp2.raise_for_status()
    data2 = resp2.json()
    results2 = data2.get("results", [])
    print(f"Response status: {resp2.status_code}")
    print(f"Number of results: {len(results2)}")
    print(f"Results: {results2}")

except Exception as e:
    print(f"Error: {e}")
