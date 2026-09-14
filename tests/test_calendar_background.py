import unittest
from unittest.mock import Mock, patch

from annie import calendar_service as calendar


class CalendarTests(unittest.TestCase):
    def test_background_credentials_never_launch_oauth(self):
        with patch.object(calendar.os.path, 'exists', return_value=True), \
                patch.object(calendar.Credentials, 'from_authorized_user_file', side_effect=ValueError('invalid test token')), \
                patch.object(calendar.InstalledAppFlow, 'from_client_secrets_file') as oauth:
            self.assertIsNone(calendar.get_calendar_credentials(interactive=False))
            oauth.assert_not_called()

    def test_reminders_build_only_one_noninteractive_service(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {'items': []}
        with patch.object(calendar, 'get_service', return_value=service) as get_service:
            self.assertEqual(calendar.check_upcoming_reminders(), [])
            get_service.assert_called_once_with(interactive=False)

    def test_calendar_transport_has_timeout(self):
        with patch.object(calendar, 'get_calendar_credentials', return_value=object()), \
                patch.object(calendar, 'AuthorizedHttp'), \
                patch.object(calendar.httplib2, 'Http') as http, \
                patch.object(calendar, 'build'):
            calendar.get_service(interactive=False)
            http.assert_called_once_with(timeout=10)


if __name__ == '__main__':
    unittest.main()
