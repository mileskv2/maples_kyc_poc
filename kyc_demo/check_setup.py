"""Run once after setting GEMINI_API_KEY: checks the key works and finds a model that answers right now.
Each model gets one attempt with a 30-second timeout, so this finishes in a few minutes at most."""
import os
import sys
import time

print("Loading libraries...", flush=True)
from google import genai
from google.genai import types

from extractor import DEFAULT_MODEL, FALLBACK_MODELS

key = os.environ.get("GEMINI_API_KEY", "")
if not key:
    sys.exit("GEMINI_API_KEY is not set. Run: export GEMINI_API_KEY=\"your-key\"")
print(f"Key loaded (starts with {key[:4]}..., length {len(key)}). Trying models in order...\n", flush=True)

client = genai.Client(
    api_key=key,
    http_options=types.HttpOptions(timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)),
)
prompt = "Translate to English: 营业执照 / سجل تجاري"
for m in [DEFAULT_MODEL] + [x for x in FALLBACK_MODELS if x != DEFAULT_MODEL]:
    print(f"  trying {m} ...", flush=True)
    t0 = time.time()
    try:
        r = client.models.generate_content(model=m, contents=prompt)
        print(f"✅ {m} works ({time.time() - t0:.0f}s): {r.text.strip()[:200]}", flush=True)
        break
    except Exception as e:
        print(f"❌ {m} ({time.time() - t0:.0f}s) {type(e).__name__}: {str(e)[:160]}", flush=True)
else:
    print("\nNo model answered. If every error says 503/UNAVAILABLE, wait a minute and retry.\n"
          "If it says API key not valid / 400 / 401 / 403, copy the key again from aistudio.google.com.\n"
          "If it says timeout, check your internet connection.", flush=True)
