"""Guard credentials at the metadata and hosted-auth logging boundaries."""
import ast
import logging
from pathlib import Path
import unittest

from runtime_config import ROOT


class CredentialLoggingTests(unittest.TestCase):
    def test_metadata_engines_hide_bound_parameters_in_errors(self):
        for component in ("agent", "chatbot_management", "database_connection", "knowledge", "session"):
            tree = ast.parse((ROOT / component / "services/sqlmodel_session.py").read_text())
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name)
                     and n.func.id in {"create_engine", "create_async_engine"}]
            self.assertEqual(len(calls), 2)
            for call in calls:
                options = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
                self.assertIs(options["echo"], False)
                self.assertIs(options["hide_parameters"], True)

    def test_http_client_does_not_log_credential_bearing_request_urls(self):
        import logger  # noqa: F401
        for name in ("httpx", "httpcore"):
            self.assertFalse(logging.getLogger(name).isEnabledFor(logging.INFO))


if __name__ == "__main__":
    unittest.main()
