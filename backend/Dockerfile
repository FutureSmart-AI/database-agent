# The official Docker Hub image, served from AWS's public mirror: identical
# content, and no anonymous pull limit (CodeBuild hit Docker Hub's 429).
FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# The BM25 encoder used to index high-cardinality values ships in the image, so the first
# profiling job of a container does not download it (DA-MEM-002).
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding('Qdrant/bm25')"

COPY . .

ENV PYTHONPATH=/app
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS\" = \"true\" ]; then alembic upgrade head; else uvicorn main:app --host 0.0.0.0 --port 8000; fi"]