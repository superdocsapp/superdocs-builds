import asyncio, os, sys, time
sys.path.insert(0, ".")

async def main():
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        print("GROQ_API_KEY not in environment"); return
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    import httpx
    print(f"python : {sys.version.split()[0]}")
    print(f"httpx  : {httpx.__version__}")
    print(f"model  : {model}\n")

    body = {"model": model,
            "messages": [{"role":"system","content":"Return ONLY a valid JSON object."},
                         {"role":"user","content":'Return {"ok": true} as json.'}],
            "temperature": 0, "max_tokens": 100, "seed": 42,
            "response_format": {"type":"json_object"}}
    url = "https://api.groq.com/openai/v1/chat/completions"
    hdr = {"Authorization": f"Bearer {key}"}

    for label, timeout in (("1. raw httpx (30s)", 30.0), ("2. httpx as client (120s)", 120.0)):
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
                r = await c.post(url, headers=hdr, json=body)
            print(f"{label:<28}: {r.status_code} in {time.monotonic()-t0:.2f}s")
        except Exception as e:
            print(f"{label:<28}: FAILED {time.monotonic()-t0:.2f}s -> {type(e).__name__}: {e}")

    from backend.services.groq_client import GroqClient
    t0 = time.monotonic()
    try:
        c = GroqClient(api_key=key)
        try:
            data, usage, _ = await c.complete_json("Return ONLY a valid JSON object.",
                                                   'Return {"ok": true} as json.')
            print(f"{'3. GroqClient':<28}: ok in {time.monotonic()-t0:.2f}s -> {data} ({usage.total_tokens} tok)")
        finally:
            await c.aclose()
    except Exception as e:
        print(f"{'3. GroqClient':<28}: FAILED {time.monotonic()-t0:.2f}s -> {type(e).__name__}: {e}")

    print("\n4. event loop responsiveness")
    lags = []
    for _ in range(5):
        t = time.monotonic(); await asyncio.sleep(0.05); lags.append(time.monotonic()-t-0.05)
    w = max(lags)
    print(f"   worst overshoot: {w*1000:.1f}ms ({'ok' if w < 0.05 else 'LOOP BLOCKED'})")

    print("\n5. embedder")
    t0 = time.monotonic()
    try:
        from backend.services.vector_store import get_embedder
        e = get_embedder()
        v = e.embed_one("test")
        print(f"   {type(e).__name__} dim={len(v)} in {time.monotonic()-t0:.2f}s")
    except Exception as ex:
        print(f"   FAILED {time.monotonic()-t0:.2f}s -> {type(ex).__name__}: {ex}")

asyncio.run(main())
