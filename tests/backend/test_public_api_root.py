"""The API docs work under the mount and under the canonical public root.

The hosted service is mounted at /nl2sql/api; https://futuresmart.ai/database-agent/api
forwards to the same routes. These tests mount a docs app built from the settings the
real one uses (swaggers.public_root) in a parent app, as main.py does, and read what a
browser would: the docs page must load the schema by a relative URL, and the schema's
server must be the public root when PUBLIC_API_ROOT is set and the mount path when not.
"""
import os
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from swaggers.public_root import docs_app_settings, swagger_page


def client():
    docs_app = FastAPI(**docs_app_settings())

    @docs_app.get("/v1/ping")
    async def ping():
        return {"ok": True}

    @docs_app.get("/docs", include_in_schema=False)
    async def docs():
        return swagger_page("NL2SQL API")

    app = FastAPI()
    app.mount("/nl2sql/api", docs_app)
    return TestClient(app)


class PublicApiRootTest(unittest.TestCase):
    def test_docs_page_loads_schema_by_relative_url(self):
        with mock.patch.dict(os.environ, {"PUBLIC_API_ROOT": ""}):
            html = client().get("/nl2sql/api/docs").text
        self.assertIn("url: 'openapi.json'", html)
        self.assertNotIn("/nl2sql/api/openapi.json", html)

    def test_schema_names_public_root_when_set(self):
        with mock.patch.dict(os.environ, {"PUBLIC_API_ROOT": "https://futuresmart.ai/database-agent/api/"}):
            schema = client().get("/nl2sql/api/openapi.json").json()
        self.assertEqual(schema["servers"], [{"url": "https://futuresmart.ai/database-agent/api"}])
        self.assertIn("/v1/ping", schema["paths"])

    def test_schema_keeps_mount_path_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PUBLIC_API_ROOT", None)
            schema = client().get("/nl2sql/api/openapi.json").json()
        self.assertEqual(schema["servers"], [{"url": "/nl2sql/api"}])

    def test_default_docs_page_is_off(self):
        with mock.patch.dict(os.environ, {"PUBLIC_API_ROOT": ""}):
            self.assertIsNone(docs_app_settings()["docs_url"])


if __name__ == "__main__":
    unittest.main()
