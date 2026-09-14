import types
import unittest
from unittest.mock import patch


class SlideAnalysisTests(unittest.TestCase):
    @patch('annie.meeting.types.Part.from_bytes')
    @patch('annie.meeting.genai.Client')
    def test_png_uses_correct_mime_and_falls_back_after_503(self, client_type, from_bytes):
        from annie.meeting import analyze_lecture_slide

        image_part = object()
        from_bytes.return_value = image_part
        client = client_type.return_value
        client.models.generate_content.side_effect = [
            RuntimeError('503 UNAVAILABLE'),
            types.SimpleNamespace(text='Recovered slide analysis'),
        ]

        result = analyze_lecture_slide(b'\x89PNG\r\n\x1a\nimage-data')

        self.assertEqual(result, 'Recovered slide analysis')
        from_bytes.assert_called_once_with(
            data=b'\x89PNG\r\n\x1a\nimage-data', mime_type='image/png'
        )
        calls = client.models.generate_content.call_args_list
        self.assertEqual(calls[0].kwargs['model'], 'gemini-3.6-flash')
        self.assertEqual(calls[1].kwargs['model'], 'gemini-3.8-flash')
        self.assertEqual(calls[1].kwargs['contents'][1], image_part)

    @patch('annie.meeting.types.Part.from_bytes')
    @patch('annie.meeting.genai.Client')
    def test_all_model_failures_raise_instead_of_becoming_notes(self, client_type, from_bytes):
        from annie.meeting import analyze_lecture_slide

        from_bytes.return_value = object()
        client_type.return_value.models.generate_content.side_effect = RuntimeError('503 UNAVAILABLE')

        with self.assertRaisesRegex(RuntimeError, 'all model fallbacks'):
            analyze_lecture_slide(b'\xff\xd8\xffimage-data')


if __name__ == '__main__':
    unittest.main()
