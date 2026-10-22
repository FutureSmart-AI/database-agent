# Product architecture

```text
Browser → Next.js static UI / Nginx → FastAPI / LangGraph
                                      ├─ PostgreSQL metadata
                                      ├─ Qdrant vectors
                                      ├─ PostgreSQL / MySQL source
                                      └─ model providers
```

`backend/` contains existing packages, migrations, and standalone auth/bootstrap.
Active helpers retain historical names such as `knowledge` and `chatbot`;
these are local imports, not another required FutureSmart service. SQL, pandas,
chart, CSV, and report processing remain product-owned code.

`frontend/` contains UI, image build, proxy, and UI checks. `deploy/` contains
configuration generation, read-only sample SQL, and ECS rendering. `tests/`
separates backend regressions, deployment checks, and the small evaluation.

Ordinary setup/chat uses API-owned background tasks. Optional reports use the
existing in-process executor in standalone mode. No separate core worker image
is required. The retired external report-consumer lane and optional shared
website widget assets are outside this installation.

Compose is the local path. AWS separates ECS/Fargate API compute from a static
S3/CloudFront UI and private metadata, vector, and source databases. One source
repository does not require one runtime process or scaling unit.
