import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from annie.meta_client import MetaAPIError, MetaClient


class MetaClientTests(unittest.TestCase):
    def response(self, **updates):
        data = {'choices': [{'message': {'content': '{"findings": []}'}, 'finish_reason': 'stop'}],
                'usage': {'total_tokens': 20}}
        data.update(updates)
        return io.BytesIO(json.dumps(data).encode())

    def test_documented_endpoint_and_schema_used_without_sdk(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return self.response()
        client = MetaClient('test-key', 'muse-spark-1.3', opener=opener)
        self.assertEqual(client.complete([{'role': 'user', 'content': 'fixture'}], {'type': 'object'}), '{"findings": []}')
        self.assertEqual(requests[0].full_url, 'https://api.meta.ai/v1/chat/completions')
        payload = json.loads(requests[0].data)
        self.assertEqual(payload['response_format']['type'], 'json_schema')
        self.assertEqual(client.last_usage['total_tokens'], 20)

    def test_missing_key_fails_before_network(self):
        with self.assertRaisesRegex(MetaAPIError, 'key'):
            MetaClient('', 'muse-spark-1.3', opener=lambda *_: self.fail()).complete([], {})

    def test_http_error_sanitized_and_not_retried_for_auth(self):
        calls = []
        def opener(*args, **kwargs):
            calls.append(1)
            raise urllib.error.HTTPError('secret-key', 401, 'secret response', {}, None)
        with self.assertRaises(MetaAPIError) as caught:
            MetaClient('secret-key', 'muse-spark-1.3', opener=opener).complete([], {})
        self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(len(calls), 1)

    def test_transient_failure_retries_bounded(self):
        calls = []
        def opener(*args, **kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise urllib.error.HTTPError('url', 429, 'rate limited', {}, None)
            return self.response()
        with patch('annie.meta_client.time.sleep'):
            MetaClient('key', 'model', opener=opener).complete([], {})
        self.assertEqual(len(calls), 3)

    def test_partial_or_refused_response_not_accepted(self):
        opener = lambda *_args, **_kwargs: self.response(choices=[{'message': {'content': 'partial'}, 'finish_reason': 'length'}])
        with self.assertRaisesRegex(MetaAPIError, 'incomplete'):
            MetaClient('key', 'model', opener=opener).complete([], {})
