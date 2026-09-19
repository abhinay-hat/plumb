import os
from dotenv import load_dotenv; load_dotenv("/Users/padidamabhinay/Projects/Personal/career/Builds/plumb/.env")
import httpx
key=os.environ["GROQ_API_KEY"]
for m in ["llama-3.3-70b-versatile","openai/gpt-oss-20b","llama-3.1-8b-instant"]:
    r=httpx.post("https://api.groq.com/openai/v1/chat/completions",headers={"Authorization":f"Bearer {key}"},
      json={"model":m,"messages":[{"role":"user","content":"hi"}],"max_tokens":5},timeout=30)
    print(m, r.status_code, r.text[:200].replace("\n"," "))
    print("   TPM limit header:", r.headers.get("x-ratelimit-limit-tokens"))
