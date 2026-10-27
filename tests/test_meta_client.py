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
        self.assertEqual(payload['max_tokens'], 8192)
        self.assertNotIn('max_completion_tokens', payload)
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

    def test_effort_output_budget_and_strict_are_explicit(self):
        requests = []
        def opener(request, **kwargs):
            requests.append(json.loads(request.data))
            return self.response()
        client = MetaClient('key', 'model', opener=opener, reasoning_effort='medium',
                            max_tokens=4096, strict=True)
        client.complete([], {})
        self.assertEqual(requests[0]['reasoning_effort'], 'medium')
        self.assertEqual(requests[0]['max_tokens'], 4096)
        self.assertTrue(requests[0]['response_format']['json_schema']['strict'])

    def test_invalid_limits_fail_before_any_request(self):
        for kwargs in ({'max_tokens': True}, {'max_tokens': 0}, {'max_tokens': 32769},
                       {'max_attempts': 0}, {'max_attempts': True}, {'max_attempts': 4},
                       {'reasoning_effort': 'none'}, {'strict': 'true'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                MetaClient('key', 'model', **kwargs)

    def test_explicit_single_attempt_and_sanitized_status(self):
        def opener(*args, **kwargs):
            raise urllib.error.HTTPError('secret-key', 402, 'secret response', {}, None)
        client = MetaClient('secret-key', 'model', opener=opener, max_attempts=1)
        with self.assertRaises(MetaAPIError) as caught:
            client.complete([], {})
        self.assertEqual(caught.exception.status_code, 402)
        self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(client.request_count, 1)

    def test_usage_accumulates_but_arbitrary_provider_values_do_not(self):
        client = MetaClient('key', 'model', opener=lambda *a, **k: self.response(
            usage={'total_tokens': 20, 'prompt_tokens': 12, 'completion_tokens': 8,
                   'private': 'credential', 'input_tokens': True, 'output_tokens': -2}))
        client.complete([], {})
        client.complete([], {})
        self.assertEqual(client.total_usage, {'total_tokens': 40, 'prompt_tokens': 24, 'completion_tokens': 16})
        self.assertEqual(client.last_usage['total_tokens'], 20)
        self.assertEqual(client.request_count, 2)

    def test_incomplete_response_still_records_billed_usage(self):
        client = MetaClient('key', 'model', opener=lambda *a, **k: self.response(
            choices=[{'message': {'content': ''}, 'finish_reason': 'length'}]))
        with self.assertRaises(MetaAPIError):
            client.complete([], {})
        self.assertEqual(client.total_usage['total_tokens'], 20)

    def test_oversized_and_wrong_shape_responses_are_sanitized(self):
        for raw in (b' ' * (MetaClient.MAX_RESPONSE_BYTES + 1), b'[]', b'{"choices":[null]}',
                    b'{"choices":[{"message":null}]}', b'{"choices":[]}', b'not-json', b'\xff'):
            client = MetaClient('secret', 'model', opener=lambda *a, data=raw, **k: io.BytesIO(data))
            with self.subTest(size=len(raw)), self.assertRaises(MetaAPIError) as caught:
                client.complete([], {})
            self.assertNotIn('secret', str(caught.exception))

    def test_metadata_resets_after_a_failed_followup(self):
        client = MetaClient('key', 'model', opener=lambda *a, **k: self.response())
        client.complete([], {})
        client.opener = lambda *a, **k: io.BytesIO(b'bad json')
        with self.assertRaises(MetaAPIError):
            client.complete([], {})
        self.assertEqual(client.last_usage, {})
        self.assertEqual(client.total_usage['total_tokens'], 20)

    def test_request_id_uses_only_safe_header_metadata(self):
        response = self.response()
        response.headers = {'x-request-id': 'request-123'}
        client = MetaClient('secret-key', 'model', opener=lambda *a, **k: response)
        client.complete([], {})
        self.assertEqual(client.last_request_id, 'request-123')
        response = self.response()
        response.headers = {'x-request-id': 'secret-key'}
        client.opener = lambda *a, **k: response
        client.complete([], {})
        self.assertIsNone(client.last_request_id)
