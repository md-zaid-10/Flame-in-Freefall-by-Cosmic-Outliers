# Deploying live answers (free)

The public site on GitHub Pages is static. To let visitors ask **new** questions, the
answer server (`frontend/serve.py`) runs on **Render's free plan**, and the Pages site
sends questions to it. The LLM is **Groq**; its key lives only on Render.

```
Visitor ──> GitHub Pages (static site) ──/api/ask──> Render (search over NASA text) ──> Groq LLM
```

The free server has 512 MB of memory, so it runs **lite search** (`FIF_EMBEDDINGS=0`):
keyword search (BM25 + TF-IDF) without the semantic model, which avoids PyTorch. Tested
at ~270 MB. Answers are still cited and checked, but slightly less precise than the
local version. Settings are in [`render.yaml`](../render.yaml).

## One-time setup (about 10 minutes, no credit card)

1. **Groq key:** [console.groq.com/keys](https://console.groq.com/keys) → *Create API Key*.
2. **Render account:** [dashboard.render.com/register](https://dashboard.render.com/register)
   → sign up with GitHub.
3. **Create the service:** Render → *New* → *Blueprint* → connect the GitHub repo
   `Flame-in-Freefall-by-Cosmic-Outliers` → Render reads `render.yaml` → paste the
   Groq key when it asks for `GROQ_API_KEY` → *Apply*. The first build takes ~3 minutes.
4. **Copy the service URL** from the Render dashboard, e.g. `https://flamescope.onrender.com`.
   Check `https://<url>/api/health` shows `{"live": true}`.
5. **Point the site at it:** GitHub repo → *Settings* → *Secrets and variables* → *Actions*
   → *Variables* → *New repository variable*: `FLAMESCOPE_API` = the URL from step 4
   (no trailing slash).
6. **Redeploy the site:** GitHub → *Actions* → "Deploy frontend to GitHub Pages" →
   *Run workflow*.

From then on, every push to `main` updates both Render and GitHub Pages.

## Good to know

- **Sleep:** the free server sleeps after 15 minutes without visitors. The first question
  after that takes ~1 minute while it wakes; the page asks the visitor to retry.
  Before a demo, open `<url>/api/health` once to wake it.
- **Limits:** each visitor may ask 20 new questions per 10 minutes (`FIF_RATE_LIMIT`);
  repeated questions are cached. Groq's free tier also has a per-minute limit; when it is
  hit, visitors still get NASA's passages without the AI summary.
- **The Render URL is a full copy of the site**, so it works on its own too.
- **Full search quality** needs ~2 GB of memory: use the [`Dockerfile`](../Dockerfile) on a
  larger host (Render paid, Google Cloud Run, a VM) and set `GROQ_API_KEY` there.
