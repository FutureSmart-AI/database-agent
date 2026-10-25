# Source layout and preservation

This relocates the complete product from private baseline
`97fdcf458424bb5e751922d918f291c5ee9698b7`. Models, prompts, application
behavior, and UI features are preserved.

| Previous location | Current location |
|---|---|
| Root Python packages and entry points | `backend/` |
| Root Alembic and migrations | `backend/alembic.ini`, `backend/migrations/` |
| Standalone auth/bootstrap/baseline | `backend/standalone/` |
| Frozen standalone dependencies | `backend/requirements.txt` |
| Configuration and sample SQL | `deploy/configure.py`, `deploy/sample.sql` |
| ECS renderer | `deploy/aws/render_task.py` |
| Backend/deployment regressions | `tests/backend/`, `tests/deployment/` |
| Real-provider smoke | `tests/evaluation/run.py` |
| UI source | `frontend/` (preserved) |
| Standalone UI build/proxy | `frontend/Dockerfile`, `frontend/nginx.conf` |

Docker contexts, environment discovery, migration resources, tests, and CI
follow this layout. The image retains `/app`, existing Python module names,
and the ASGI entry point. No framework migration is needed.

Internal handoffs, historical benchmarks/results, old docs, and legacy deploy
alternatives were preserved in a private parent archive with original paths,
baseline commit, and byte hashes before removal. Environment variants were
untracked after preserving private copies. No benchmark resources or Git
history were deleted. These materials are not installation inputs.

`source-preservation.json` records unchanged sources with normalized line-ending
hashes, checked by deployment tests. Private receipts and archive indexes stay
outside the product. This does not authorize publication or history sharing.
