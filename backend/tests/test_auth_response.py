import unittest
import uuid

from app.schemas import TokenResponse


ROLE_LEAGUE_ADMIN = 'LEAGUE_ADMIN'


class AuthResponseTest(unittest.TestCase):
    def test_token_response_includes_authenticated_user_role(self):
        user_id = uuid.uuid4()

        response = TokenResponse(
            access_token='access-token',
            refresh_token='refresh-token',
            token_type='bearer',
            user={
                'id': user_id,
                'email': 'admin@example.com',
                'full_name': 'League Admin',
                'role_name': ROLE_LEAGUE_ADMIN,
                'organization_id': None,
            },
        )

        payload = response.model_dump(mode='json')

        self.assertEqual('admin@example.com', payload['user']['email'])
        self.assertEqual(ROLE_LEAGUE_ADMIN, payload['user']['role_name'])
        self.assertIsNone(payload['user']['organization_id'])


if __name__ == '__main__':
    unittest.main()
