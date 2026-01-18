# AI Parsing Cost Analysis for Daily Runs

## Data Volume
- ~700 location rows per day
- Average prompt: ~200-300 tokens (location string + instructions)
- Average response: ~100-200 tokens (structured JSON)

## Cost Estimates (Daily)

### Option 1: OpenAI GPT-4o-mini (Recommended for Cost)
- **Input**: $0.15 per 1M tokens
- **Output**: $0.60 per 1M tokens
- **Daily cost**: 
  - Input: 700 rows × 250 tokens = 175K tokens = **$0.026/day**
  - Output: 700 rows × 150 tokens = 105K tokens = **$0.063/day**
  - **Total: ~$0.09/day = $2.70/month = $32/year**

### Option 2: OpenAI GPT-3.5-turbo
- **Input**: $0.50 per 1M tokens
- **Output**: $1.50 per 1M tokens
- **Daily cost**: ~$0.30/day = **$9/month = $108/year**

### Option 3: Anthropic Claude 3 Haiku
- **Input**: $0.25 per 1M tokens
- **Output**: $1.25 per 1M tokens
- **Daily cost**: ~$0.18/day = **$5.40/month = $65/year**

### Option 4: Google Gemini Flash
- **Input**: $0.075 per 1M tokens
- **Output**: $0.30 per 1M tokens
- **Daily cost**: ~$0.06/day = **$1.80/month = $22/year** ⭐ CHEAPEST

## FREE Options

### Option A: Ollama (Local LLM) - 100% FREE
- **Cost**: $0 (runs locally)
- **Models**: Llama 3.1, Mistral, etc.
- **Requirements**: 
  - Docker container with GPU (or CPU, slower)
  - ~4-8GB RAM for smaller models
- **Speed**: Slower than API (5-10 seconds per row on CPU)
- **Quality**: Good for structured extraction tasks
- **Best for**: Pro-bono projects, privacy, no ongoing costs

### Option B: Hugging Face Inference API (Free Tier)
- **Free tier**: 1,000 requests/month
- **Cost**: $0 for first 1,000, then pay-as-you-go
- **Problem**: Only ~14 days of daily runs (700 rows × 30 days = 21,000 rows)
- **Not viable** for daily runs

### Option C: Groq (Fast & Free-ish) ⚠️ CAUTION
- **Free tier**: 30 requests/minute, 14,400 requests/day
- **Speed**: Extremely fast (uses LPU, not GPU)
- **Models**: Llama 3.1, Mixtral
- **Cost**: Free tier should cover daily runs (700 rows/day = well under limit)
- **How long free**: Since early/mid 2025 (~6-8 months as of early 2026)
- **Risk**: Free tier could change/disappear (no guarantees)
- **Best for**: Speed + free (but not guaranteed long-term)

### Option D: Together AI (Free Credits)
- **Free credits**: $25 free credits for new accounts
- **Cost**: Similar to OpenAI pricing after credits
- **Good for**: Testing, but not long-term free

## Hybrid Approach Cost

If we use traditional parser + AI fallback:
- Assume 80% success rate with traditional parser
- Only 20% need AI: 140 rows/day
- **Cost with GPT-4o-mini**: ~$0.02/day = **$0.60/month**
- **Cost with Gemini Flash**: ~$0.01/day = **$0.30/month**

## Recommendation for Pro-Bono Project

### Best Option: **Ollama (Local LLM)**
- ✅ 100% free forever
- ✅ No API rate limits
- ✅ Privacy (data stays local)
- ✅ Works in Docker
- ⚠️ Slower (but acceptable for daily batch job)
- ⚠️ Requires more resources

### Second Best: **Google Gemini Flash**
- ✅ Very cheap ($22/year)
- ✅ High quality
- ✅ Reliable
- ✅ Established pricing (less likely to change)
- ⚠️ Small ongoing cost

### Third: **Groq API** (risky for long-term)
- ✅ Free tier covers daily usage (for now)
- ✅ Extremely fast
- ✅ Easy Python integration
- ⚠️ **Only free since early 2025** (~6-8 months)
- ⚠️ **No guarantee it stays free** (could change anytime)
- ⚠️ Rate limits (30 RPM) - might need batching for 700 rows
- ⚠️ **Not recommended for pro-bono projects** (uncertain future)

## Implementation Complexity

### Ollama Setup:
```python
# Install in Docker
# docker run -d -v ollama:/root/.ollama -p 11434:11434 ollama/ollama

import requests

def parse_with_ollama(location_str):
    response = requests.post('http://localhost:11434/api/generate', json={
        'model': 'llama3.1:8b',
        'prompt': f"Parse this Lithuanian location: {location_str}...",
        'stream': False
    })
    return response.json()
```

### Groq Setup:
```python
from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
response = client.chat.completions.create(
    model="llama-3.1-70b-versatile",
    messages=[{"role": "user", "content": prompt}]
)
```

### Gemini Flash Setup:
```python
import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')
response = model.generate_content(prompt)
```

## Comparison with Approach #1 (Lock Raw Data)

### Approach #1 Benefits:
- ✅ Zero parsing cost
- ✅ No API dependencies
- ✅ Fast
- ✅ Reliable
- ✅ Can improve parsing later

### Approach #1 Drawbacks:
- ⚠️ Users see raw messy data
- ⚠️ Search/filter harder
- ⚠️ Need manual parsing for features

### Hybrid Approach Benefits:
- ✅ Clean structured data
- ✅ Better UX
- ✅ Low cost (especially with Ollama)
- ✅ Can still store raw data as backup

## Final Recommendation

For a **pro-bono community project**:

1. **Short term**: Use **Ollama** (100% free, local)
2. **If Ollama too slow**: Use **Groq** (free tier)
3. **If need highest quality**: Use **Gemini Flash** ($22/year is reasonable)

All three work in Docker with Python.
