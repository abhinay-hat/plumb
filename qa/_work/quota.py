import os, httpx
from dotenv import load_dotenv; load_dotenv("/Users/padidamabhinay/Projects/Personal/career/Builds/plumb/.env")
r=httpx.post("https://api.groq.com/openai/v1/chat/completions",
  headers={"Authorization":f"Bearer {os.environ['GROQ_API_KEY']}"},
  json={"model":"openai/gpt-oss-20b","messages":[{"role":"user","content":"hi"}],"max_tokens":5},timeout=30)
print("status", r.status_code)
for k,v in r.headers.items():
    if "ratelimit" in k: print(" ",k,v)
if r.status_code!=200: print(r.text[:300])
