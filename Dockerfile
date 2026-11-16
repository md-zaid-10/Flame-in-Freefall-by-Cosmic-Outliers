# FlameScope answer server, full search quality, for any container host with ~2 GB RAM.
# The free Render setup does not use this file; it uses render.yaml (lite search).
# The LLM runs on Groq: set GROQ_API_KEY as a secret on the host, never in this file.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    HOST=0.0.0.0 \
    PORT=7860 \
    FIF_LLM=groq

WORKDIR /app

# CPU-only PyTorch keeps the image ~1.5 GB smaller; the search model needs no GPU.
COPY requirements.txt .
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt

COPY . .

# Download the embedding model and compute passage embeddings at build time,
# so the first visitor does not wait about a minute. Some hosts run the
# container as a non-root user, so the app folder must be writable.
RUN python -c "import sys; sys.path.insert(0, '.'); from rag.retrieve import Retriever; r = Retriever(); assert r.emb is not None, 'embeddings missing'" \
 && chmod -R a+rwX /app

EXPOSE 7860
CMD ["python", "frontend/serve.py"]
