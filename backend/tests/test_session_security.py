import os
import subprocess
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from app.security import AUTH_EXPIRED_MESSAGE, decode_token
from app.schemas import TokenResponse


class SessionSecurityTest(unittest.TestCase):
    def test_token_response_includes_expiration_timestamp(self):
        expires_at = datetime.now(UTC) + timedelta(minutes=30)
        response = TokenResponse(access_token='access', refresh_token='refresh', expires_at=expires_at)

        payload = response.model_dump(mode='json')

        self.assertEqual(expires_at.isoformat().replace('+00:00', 'Z'), payload['expires_at'])

    def test_invalid_access_token_uses_structured_friendly_auth_error(self):
        with self.assertRaises(HTTPException) as raised:
            decode_token('not-a-jwt', 'access')

        self.assertEqual(401, raised.exception.status_code)
        self.assertEqual('auth_invalid_token', raised.exception.detail['error'])
        self.assertEqual(AUTH_EXPIRED_MESSAGE, raised.exception.detail['message'])

    def test_same_signing_secret_decodes_token_after_backend_module_reload(self):
        repo_root = Path(__file__).resolve().parents[1]
        env = {**os.environ, 'PYTHONPATH': str(repo_root), 'JWT_SECRET_KEY': 'stable-test-secret'}
        script = """
import importlib
from app import config, security
first = security.create_access_token('user-1')
importlib.reload(config)
importlib.reload(security)
payload = security.decode_token(first, 'access')
assert payload['sub'] == 'user-1'
"""
        result = subprocess.run([sys.executable, '-c', script], env=env, cwd=repo_root, capture_output=True, text=True)

        self.assertEqual(0, result.returncode, result.stderr)

    def test_missing_production_signing_secret_fails_startup_safely(self):
        repo_root = Path(__file__).resolve().parents[1]
        env = {key: value for key, value in os.environ.items() if key != 'JWT_SECRET_KEY'}
        env.update({'PYTHONPATH': str(repo_root), 'ENVIRONMENT': 'production'})
        result = subprocess.run([sys.executable, '-c', 'import app.config'], env=env, cwd=repo_root, capture_output=True, text=True)

        self.assertNotEqual(0, result.returncode)
        self.assertIn('JWT_SECRET_KEY must be set to a stable value in production environments.', result.stderr)


if __name__ == '__main__':
    unittest.main()
