# Deploying live answers

The public site on GitHub Pages is static. To let visitors ask **new** questions, the
answer server (`frontend/serve.py`) runs on a free **Hugging Face Docker Space**, and the
Pages site sends questions to it. The LLM is **Groq**; its key lives only on the Space.

```
Visitor ──> GitHub Pages (static site) ──/api/ask──> Hugging Face Space ──> Groq LLM
                                                     (search over NASA text)
```

## One-time setup (about 10 minutes)

1. **Create the Space.** On [huggingface.co](https://huggingface.co) → *New Space* →
   name `flamescope`, SDK **Docker**, hardware **CPU basic (free)**, public.
2. **Add the Groq key to the Space.** Space → *Settings* → *Variables and secrets* →
   *New secret*: `GROQ_API_KEY` = your key from [console.groq.com/keys](https://console.groq.com/keys).
   Optional variable: `FIF_CORS_ORIGIN` = `https://md-zaid-10.github.io` (only the site can call the API).
3. **Let GitHub deploy to the Space.** Create a Hugging Face token with *write* access
   ([settings/tokens](https://huggingface.co/settings/tokens)). In the GitHub repo →
   *Settings* → *Secrets and variables* → *Actions*:
   - Secret `HF_TOKEN` = that token
   - Variable `HF_SPACE` = `<your-hf-name>/flamescope`
   - Variable `FLAMESCOPE_API` = `https://<your-hf-name>-flamescope.hf.space`
4. **Run both workflows once:** *Actions* → "Deploy answer server to Hugging Face" →
   *Run workflow*. Wait for the Space to show **Running** (first build ~10 minutes), then
   run "Deploy frontend to GitHub Pages".

From then on every push to `main` updates both.

## Check it

```bash
curl https://<your-hf-name>-flamescope.hf.space/api/health      # {"live": true}
```

Then open the GitHub Pages site and ask a question that is not in the examples.

## Good to know

- **Sleep:** a free Space sleeps after ~48 h without visitors. The first question then
  takes ~30 s while it wakes; the page asks the visitor to retry.
- **Limits:** each visitor may ask 20 new questions per 10 minutes (`FIF_RATE_LIMIT`);
  repeated questions come from cache and are free. Groq's free tier also has its own
  per-minute limit; when it is hit, visitors still get NASA's passages, without the AI summary.
- **The Space itself is a full copy of the site**, so its URL works on its own too.
- **Other hosts:** the `Dockerfile` runs anywhere with ~2 GB RAM (Railway, Fly.io, a VM).
  Set `GROQ_API_KEY` there and point `FLAMESCOPE_API` at it.
