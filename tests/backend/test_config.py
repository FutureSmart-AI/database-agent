import os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from runtime_config import load_environment, metadata_url

class ConfigurationTests(unittest.TestCase):
 def test_explicit_env_and_process_precedence(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'test.env';p.write_text('MODE=prod\nPOSTGRES_HOST=never-use\n')
   with patch.dict(os.environ, {'ENV_FILE':str(p), 'MODE':'standalone','POSTGRES_HOST':'isolated'}, clear=True):
    load_environment();self.assertEqual(os.environ['POSTGRES_HOST'],'isolated');self.assertEqual(os.environ['MODE'],'standalone')
 def test_one_address_both_drivers(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'empty';p.touch()
   with patch.dict(os.environ, {'ENV_FILE':str(p),'DATABASE_URL':'postgresql://local:p%40ss%25@127.0.0.1:15432/disposable','POSTGRES_HOST':'wrong'},clear=True):
    a=metadata_url();b=metadata_url('psycopg2');self.assertEqual(a.set(drivername='postgresql'),b.set(drivername='postgresql'));self.assertEqual(a.password,'p@ss%');self.assertEqual(a.host,'127.0.0.1')
 def test_components_escape_password(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'empty';p.touch()
   with patch.dict(os.environ, {'ENV_FILE':str(p),'POSTGRES_USER':'local','POSTGRES_PASSWORD':'p@ss%','POSTGRES_HOST':'127.0.0.1','POSTGRES_PORT':'15432','POSTGRES_DB_NAME':'disposable'},clear=True):
    self.assertEqual(metadata_url().password,'p@ss%')
 def test_missing_explicit_env_fails(self):
  with patch.dict(os.environ, {'ENV_FILE':'does-not-exist.env'},clear=True):
   with self.assertRaises(ValueError): load_environment()

if __name__=='__main__': unittest.main()
