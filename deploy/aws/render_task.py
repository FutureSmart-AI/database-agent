"""Render an isolated standalone ECS API task; never reads provider secret values."""
import argparse
import json

OPTIONAL_PROVIDER_SECRETS = ("GOOGLE_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY",
                             "DEEPSEEK_API_KEY", "MINIMAX_API_KEY")


def task_definition(*, family, image, execution_role, task_role, runtime_secret,
                    metadata_host, vector_url, origin, artifact_bucket, log_group,
                    region="us-east-1", initialize=False, provider_secrets=()):
    if "@sha256:" not in image:
        raise ValueError("Use an immutable image digest")
    if not origin.startswith("https://"):
        raise ValueError("Hosted standalone login requires an HTTPS origin")
    if any(name not in OPTIONAL_PROVIDER_SECRETS for name in provider_secrets):
        raise ValueError("Unsupported optional provider secret reference")
    environment = {
        "MODE": "standalone", "SERVER": "STAGING", "POSTGRES_HOST": metadata_host,
        "POSTGRES_PORT": "5432", "POSTGRES_USER": "metadata",
        "POSTGRES_DB_NAME": "database_agent", "qdrant_url": vector_url,
        "STANDALONE_ORIGIN": origin.rstrip("/"),
        "STANDALONE_OWNER_EMAIL": "operator@example.test",
        "STANDALONE_COOKIE_SECURE": "true", "REPORTS_EXECUTOR": "inprocess",
        "REPORTS_SCHEDULER_ENABLED": "false", "USAGE_SERVICE_MIRROR": "false",
        "USAGE_API_URL": "", "LANGCHAIN_TRACING_V2": "false",
        "LANGSMITH_TRACING": "false", "OTEL_EXPORTER_ENDPOINT": "",
        "BUCKET_NAME": artifact_bucket, "CSV_USE_PUBLIC_URL": "false",
        "AWS_REGION": region, "AWS_EC2_METADATA_DISABLED": "true",
    }
    secret_names = ("POSTGRES_PASSWORD", "FASTAPI_SECRET_KEY", "APP_MASTER_KEY",
                    "HASH_SALT", "STANDALONE_LOGIN_PASSWORD", "OPENAI_API_KEY") + tuple(dict.fromkeys(provider_secrets))
    result = {
        "family": family, "networkMode": "awsvpc", "requiresCompatibilities": ["FARGATE"],
        "cpu": "1024", "memory": "2048", "executionRoleArn": execution_role,
        "taskRoleArn": task_role, "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
        "containerDefinitions": [{
            "name": "api", "image": image, "essential": True,
            "portMappings": [{"containerPort": 8000, "protocol": "tcp"}],
            "command": (["python", "-m", "standalone.bootstrap"] if initialize else
                        ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]),
            "environment": [{"name": k, "value": v} for k, v in environment.items()],
            "secrets": [{"name": k, "valueFrom": runtime_secret + ":" + k + "::"} for k in secret_names],
            "healthCheck": {"command": ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/nl2sql/api/health', timeout=3)\" || exit 1"], "interval": 15, "timeout": 5, "retries": 3, "startPeriod": 60},
            "logConfiguration": {"logDriver": "awslogs", "options": {"awslogs-group": log_group, "awslogs-region": region, "awslogs-stream-prefix": "api"}},
        }],
    }

    if initialize:
        result["containerDefinitions"][0].pop("healthCheck", None)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("family", "image", "execution-role", "task-role", "runtime-secret",
                 "metadata-host", "vector-url", "origin", "artifact-bucket", "log-group"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--provider-secret", dest="provider_secrets", action="append", default=[],
                        choices=OPTIONAL_PROVIDER_SECRETS, help="Add a runtime secret field for an explicit provider override")
    parser.add_argument("--initialize", action="store_true", help="Render a one-shot fresh-database initialization task")
    print(json.dumps(task_definition(**vars(parser.parse_args())), indent=2))


if __name__ == "__main__":
    main()
