import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from annie.secure_storage import read_secret
from tools.migrate_studio_profile import migrate


class MigrationTests(unittest.TestCase):
    def test_copy_encrypts_secrets_preserves_source_and_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'old'
            source.mkdir()
            original = '{"gemini_api_key":"fake-test-key", "phone_port":8080}'
            (source / 'annie_settings.json').write_text(original)
            (source / 'token.json').write_text('{"refresh_token":"fake-test-token"}')
            with closing(sqlite3.connect(source / 'study_sessions.sqlite3')) as db:
                db.execute('CREATE TABLE sample (hours INTEGER)')
                db.execute('INSERT INTO sample VALUES (3)')
                db.commit()
            target = Path(temporary) / 'private'
            with patch('tools.migrate_studio_profile.active_source_processes', return_value=[]):
                migrate(source, target)
                with self.assertRaises(FileExistsError):
                    migrate(source, target)
            self.assertEqual((source / 'annie_settings.json').read_text(), original)
            self.assertNotIn('fake-test-key', (target / 'annie_settings.json').read_text())
            self.assertEqual(read_secret(target / 'accounts.dpapi')['gemini_api_key'], 'fake-test-key')
            self.assertEqual(read_secret(target / 'calendar.dpapi')['refresh_token'], 'fake-test-token')
            self.assertFalse((target / 'token.json').exists())
            with closing(sqlite3.connect(target / 'study_sessions.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT hours FROM sample').fetchone()[0], 3)

    def test_active_studio_prevents_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'old'
            source.mkdir()
            (source / 'annie_settings.json').write_text('{}')
            target = Path(temporary) / 'private'
            with patch('tools.migrate_studio_profile.active_source_processes', return_value=[123]):
                with self.assertRaises(RuntimeError):
                    migrate(source, target)
            self.assertFalse(target.exists())
