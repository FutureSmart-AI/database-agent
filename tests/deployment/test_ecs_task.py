"""Hosted deployment boundaries, without AWS calls or real secret values."""
import unittest
from deploy.aws.render_task import task_definition


class ECSTaskBoundaryTests(unittest.TestCase):
    def render(self, **changes):
        options = dict(family="disposable-staging", image="registry/product@sha256:" + "0" * 64,
                       execution_role="execution-role", task_role="task-role",
                       runtime_secret="managed-runtime-secret-reference",
                       metadata_host="isolated-postgres", vector_url="http://isolated-vector:6333",
                       origin="https://staging.example.test", artifact_bucket="isolated-artifacts",
                       log_group="/ecs/isolated")
        return task_definition(**(options | changes))

    def test_rejects_mutable_image(self):
        with self.assertRaises(ValueError):
            self.render(image="registry/product:latest")

    def test_rejects_plaintext_browser_origin(self):
        with self.assertRaises(ValueError):
            self.render(origin="http://staging.example.test")

    def test_secrets_use_runtime_references_without_admin_credentials(self):
        container = self.render()["containerDefinitions"][0]
        plain = {v["name"]: v["value"] for v in container["environment"]}
        injected = {v["name"]: v["valueFrom"] for v in container["secrets"]}
        for key in ("OPENAI_API_KEY", "POSTGRES_PASSWORD", "STANDALONE_LOGIN_PASSWORD", "APP_MASTER_KEY", "HASH_SALT", "FASTAPI_SECRET_KEY"):
            self.assertNotIn(key, plain)
            self.assertTrue(injected[key].endswith(":" + key + "::"))
        self.assertFalse({"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"} & (plain.keys() | injected.keys()))
        self.assertEqual(plain["STANDALONE_COOKIE_SECURE"], "true")
        self.assertEqual(plain["POSTGRES_HOST"], "isolated-postgres")

    def test_default_requires_only_openai_provider_secret(self):
        names = {item["name"] for item in self.render()["containerDefinitions"][0]["secrets"]}
        self.assertEqual(names, {"POSTGRES_PASSWORD", "FASTAPI_SECRET_KEY", "APP_MASTER_KEY",
                                 "HASH_SALT", "STANDALONE_LOGIN_PASSWORD", "OPENAI_API_KEY"})

    def test_optional_provider_is_explicit_and_admin_secret_is_rejected(self):
        names = {item["name"] for item in self.render(provider_secrets=["GROQ_API_KEY"])["containerDefinitions"][0]["secrets"]}
        self.assertIn("GROQ_API_KEY", names)
        self.assertNotIn("GOOGLE_API_KEY", names)
        with self.assertRaises(ValueError):
            self.render(provider_secrets=["OPENAI_ADMIN_API_KEY"])

    def test_initialization_is_separate_from_serving(self):
        serving = self.render()["containerDefinitions"][0]
        self.assertEqual(serving["command"][0], "uvicorn")
        init = self.render(initialize=True)["containerDefinitions"][0]
        self.assertEqual(init["command"], ["python", "-m", "standalone.bootstrap"])
        self.assertNotIn("healthCheck", init)


if __name__ == "__main__":
    unittest.main()
