import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from standalone.auth import router


class StandaloneLoginTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "MODE": "standalone", "STANDALONE_OWNER_EMAIL": "operator@example.test",
            "STANDALONE_LOGIN_PASSWORD": "test-local-only", "STANDALONE_ORIGIN": "http://testserver",
        })
        self.environment.start()
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-signing-secret", session_cookie="database_agent_session")
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.environment.stop()

    def test_cookie_login_profile_and_logout(self):
        self.assertEqual(self.client.get("/v1/local-auth/user/me").status_code, 401)
        login = self.client.post("/v1/local-auth/login", json={"password": "test-local-only"})
        self.assertEqual(login.status_code, 200)
        self.assertIn("httponly", login.headers["set-cookie"].lower())
        self.assertNotIn("test-local-only", login.headers["set-cookie"])
        self.assertEqual(self.client.get("/v1/local-auth/user/me").json()["email"], "operator@example.test")
        self.client.post("/v1/local-auth/logout")
        self.assertEqual(self.client.get("/v1/local-auth/user/me").status_code, 401)

    def test_invalid_password_and_cross_origin_are_denied(self):
        self.assertEqual(self.client.post("/v1/local-auth/login", json={"password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/v1/local-auth/login", json={"password": "test-local-only"}, headers={"Origin": "https://untrusted.invalid"}).status_code, 403)

    def test_forged_cookie_is_denied(self):
        self.client.cookies.set("database_agent_session", "forged")
        self.assertEqual(self.client.get("/v1/local-auth/user/me").status_code, 401)

    def test_hosted_mode_has_no_local_login(self):
        os.environ["MODE"] = "prod"
        self.assertEqual(self.client.post("/v1/local-auth/login", json={"password": "test-local-only"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
