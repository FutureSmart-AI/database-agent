# AWS deployment

The supported hosted topology is an ECS/Fargate API behind an ALB, a static
S3/CloudFront UI, PostgreSQL metadata, and Qdrant. Build both images from this
repository. Ordinary background tasks run in the API; standalone reports use
the existing in-process executor. The root README is the local Compose path.

This guide wires an installation to AWS resources you control. It does not
provision a VPC, databases, buckets, or IAM roles automatically. Use the existing
deployment's resources for upgrades; keep an isolated installation separate.
The CLI examples below use Bash and the operator's authenticated AWS CLI.

## Prepare the installation

Provide these resources and record their identifiers privately:

- An ECR repository, ECS cluster, and CloudWatch log group.
- PostgreSQL metadata reachable on port 5432 and Qdrant on port 6333 from the API.
- A source database reachable on its configured port with a read-only account.
- An ALB target group on port 8000, health path `/nl2sql/api/health`, and API task
  security group accepting requests only from the ALB. Datastore security groups
  accept only the API task network. Provide outbound access for images, secrets,
  logs, and model providers through the deployment's NAT/endpoints/public-IP setup.
- A private S3 UI bucket, CloudFront origin access control, and HTTPS hostname.
  Optional result exports use a separate private artifact bucket.
- An ECS execution role for ECR pull, log delivery, and the selected runtime
  secret; an application task role scoped to its own optional artifact storage.
  Do not supply static AWS keys to the image or ordinary configuration files.

Store a Secrets Manager JSON object with these fields:

| Fields | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Metadata user `metadata`, database `database_agent` |
| `FASTAPI_SECRET_KEY` | API authentication/session signing |
| `APP_MASTER_KEY`, `HASH_SALT` | Durable provider/source credential encryption |
| `STANDALONE_LOGIN_PASSWORD` | Single-operator browser login |
| `OPENAI_API_KEY` | Required by the recommended profile; other provider keys only for explicit overrides |

For a fresh installation, `deploy/configure.py` generates independent local
signing/encryption/login values; transfer them privately to the managed secret.
Keep provider values in the vault, outside source, logs, image build arguments,
and frontend configuration. Retain the encryption material with database backups.
Configure `STANDALONE_ORIGIN` to the exact HTTPS browser origin and secure cookies.

## Build an immutable API image

Set `RELEASE` to the reviewed source commit and `API_REPOSITORY` to your ECR URI.

```sh
docker build -t "$API_REPOSITORY:$RELEASE" backend
aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$ECR_REGISTRY"
docker push "$API_REPOSITORY:$RELEASE"
```

Resolve the pushed ECR digest and set `API_IMAGE` to `repository@sha256:...`.
The renderer rejects mutable image tags. The backend keeps `/app` as its working
directory and `uvicorn main:app` as the ordinary entry point.

```sh
mkdir -p .private
python deploy/aws/render_task.py \
  --family "$TASK_FAMILY" --image "$API_IMAGE" \
  --execution-role "$EXECUTION_ROLE_ARN" --task-role "$TASK_ROLE_ARN" \
  --runtime-secret "$RUNTIME_SECRET_ARN" --metadata-host "$METADATA_HOST" \
  --vector-url "$QDRANT_URL" --origin "$UI_ORIGIN" \
  --artifact-bucket "$ARTIFACT_BUCKET" --log-group "$LOG_GROUP" \
  --region "$AWS_REGION" > .private/task-api.json
```

The rendered task uses standalone login, task roles, runtime secret references,
disabled external tracing/usage mirroring, and the in-process report executor.
Its default validation allocation is 1 vCPU / 2 GiB. Preserve an existing
production allocation during upgrades unless deliberately changing it.
The metadata username/database/port are fixed as listed above; Qdrant needs a
private network boundary. An installation requiring vector API-key auth should
add that runtime secret reference to its reviewed task definition.

The renderer selects JSON fields from the secret's current version. Record the
version in release evidence; pin references in the reviewed task JSON when
required using `secret-arn:FIELD::version-id`. Task JSON contains references,
never provider or encryption values. Keep generated deployment files private.

## Initialize a fresh metadata database

Render a separate one-shot task using the same arguments plus `--initialize`,
writing `.private/task-init.json`. Give it a separate family name. Its command
is `python -m standalone.bootstrap`; it has no API health check.

```sh
aws ecs register-task-definition --cli-input-json file://.private/task-init.json
aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE \
  --task-definition "$INIT_TASK_REVISION" \
  --network-configuration file://.private/network.json
```

`network.json` supplies your `awsvpcConfiguration` with subnet IDs, task security
group, and the VPC's outbound connectivity choice. Wait for the task to stop with
exit code 0; inspect the log for baseline creation and Alembic completion. A
repeat initialization of this versioned installation is idempotent. Bootstrap
refuses a nonempty database without migration history.

For an existing installation, inspect Alembic state and a backup first. Do not
bootstrap/stamp an arbitrary production schema. Run reviewed migrations as a
separate one-shot task if needed; do not set `RUN_MIGRATIONS` on the API service.

Register `.private/task-api.json`, then create/update the product ECS service
with that revision, the same task network, and its ALB target group. Wait for
deployment stability, healthy tasks and healthy targets. For an upgrade preserve
the service/container/port identity, resource allocation, datastore addresses,
durable keys, and recorded rollback revision. An unchanged schema needs no reset.

## Build and publish the static UI

The image defaults to standalone login, matching the rendered API task:

```sh
docker build -t "database-agent-ui:$RELEASE" frontend
UI_CONTAINER=$(docker create "database-agent-ui:$RELEASE")
mkdir -p .private/ui
docker cp "$UI_CONTAINER:/usr/share/nginx/html/." .private/ui/
docker rm "$UI_CONTAINER"
printf '%s\n' "$RELEASE" > .private/ui/database-agent/release.txt
aws s3 sync .private/ui/ "s3://$S3_BUCKET/_releases/$RELEASE/" --only-show-errors
S3_BUCKET="$S3_BUCKET" S3_KEY_ROOT="$S3_KEY_ROOT" \
  bash frontend/scripts/promote-release.sh "$RELEASE"
```

Use a dedicated product bucket/prefix and inspect promotion scope first. The
existing script publishes hashed assets before HTML, preserves old hashed
assets, and updates only `database-agent/` and legacy `nl2sql/` route prefixes.
It removes obsolete objects only within those owned HTML prefixes. It never
writes `nl2sql/api/`. The release archive remains available for rollback.

CloudFront must route `/nl2sql/api/*`, `/chart/api/*`, and `/csv/api/*` to the
ALB before static routes, with API caching disabled and authentication cookies,
headers, and query strings forwarded. Support streaming responses and appropriate
proxy timeouts. Static routes need index-document rewriting for the Next.js
export. The UI asset prefix is `/database-agent/_next/`; the promotion script
maps exported `_next/` files there. Keep HTTPS/secure cookies and browser origin
aligned. Invalidate only the product's page/legacy-route paths after promotion.

For an existing FutureSmart SSO deployment, preserve its explicit hosted UI/API
auth settings. The optional manual frontend workflows target that hosted mode;
do not enable them unchanged for a new standalone-password installation. Legacy
automatic deployment/ClickUp publication workflows remain frozen. The optional
voice client setting is public browser configuration, never a provider key.

## Verify and roll back

Confirm the running API digest, task/target health, and UI release marker. Then
sign in through the real browser, create a sample agent, and inspect SQL, returned
rows, answer, and chart. Independently query the same read-only source. Restart
without deleting volumes/data and reopen the saved conversation. Health alone
does not prove the product flow; keep failed chart variants explicit as described
in the root README.

The relocated image has passed fresh Fargate initialization and ordinary API
health with managed secret references. Full sample UI/restart checks were also
performed on the isolated Compose installation. These are distinct checks; they
do not claim a new production rollout or general benchmark accuracy.

Record the prior API revision/digest and UI archive before rollout. API rollback
updates the same service to that prior revision. UI rollback runs the same
promotion script with the prior release, then invalidates only owned product
paths. Preserve encryption keys and data; never reset the metadata database or
Qdrant as a rollback. Review data migration compatibility separately.

Model assignments and advanced overrides use the [single versioned resolver](model-configuration.md).

The task renderer requires only the OpenAI provider-secret field by default.
When using an explicit operation override, repeat `--provider-secret` with the
selected provider's key name, for example `--provider-secret GROQ_API_KEY`.
Other provider fields are not required merely to start the default task.
