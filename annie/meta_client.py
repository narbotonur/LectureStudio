"""Small Meta Model API client; no SDK or credentials in the repository.

Protocol references: https://dev.meta.ai/docs/structured-output and /reasoning.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request


class MetaAPIError(ValueError):
    """A sanitized error that is safe to display in the desktop UI."""

    def __init__(self, message, *, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class MetaClient:
    MAX_RESPONSE_BYTES = 2_000_000
    EFFORTS = ('minimal', 'low', 'medium', 'high', 'xhigh', 'max')

    def __init__(self, api_key=None, model=None, *, opener=None, timeout=60,
                 reasoning_effort=None, max_tokens=8192, strict=False, max_attempts=3):
        if reasoning_effort is not None and reasoning_effort not in self.EFFORTS:
            raise ValueError('Choose a supported Meta reasoning effort.')
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 32768:
            raise ValueError('Meta output token limit must be between 1 and 32768.')
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 3:
            raise ValueError('Meta request attempts must be between 1 and 3.')
        if not isinstance(strict, bool):
            raise ValueError('Meta schema strict must be a boolean.')
        if api_key is None or model is None:
            from annie import config
            if api_key is None:
                api_key = (os.environ.get('META_API_KEY') or os.environ.get('MODEL_API_KEY')
                           or getattr(config, 'META_API_KEY', ''))
            if model is None:
                model = getattr(config, 'META_MODEL', 'muse-spark-1.3')
        self.api_key, self.model = api_key, model
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.strict = strict
        self.max_attempts = max_attempts
        self.last_usage = {}
        self.total_usage = {}
        self.last_request_id = None
        self.request_count = 0

    @staticmethod
    def _usage(value):
        """Retain counters only, never arbitrary provider values in a report."""
        if not isinstance(value, dict):
            return {}
        counters = ('prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens')
        return {name: value[name] for name in counters
                if isinstance(value.get(name), int) and not isinstance(value[name], bool) and value[name] >= 0}

    def _record_metadata(self, data, request_id):
        self.last_usage = self._usage(data.get('usage'))
        for name, count in self.last_usage.items():
            self.total_usage[name] = self.total_usage.get(name, 0) + count
        if (isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9._:-]{1,160}', request_id)
                and 'LLM_' not in request_id and self.api_key not in request_id):
            self.last_request_id = request_id

    def complete(self, messages, schema):
        self.last_usage = {}
        self.last_request_id = None
        if not self.api_key:
            raise MetaAPIError('Add a Meta API key in Accounts & Setup, or set MODEL_API_KEY.')
        payload = {'model': self.model, 'messages': messages,
                   'max_tokens': self.max_tokens,
                   'response_format': {'type': 'json_schema', 'json_schema': {
                       'name': 'lecture_findings', 'schema': schema, 'strict': self.strict}}}
        if self.reasoning_effort is not None:
            payload['reasoning_effort'] = self.reasoning_effort
        body = json.dumps(payload).encode('utf-8')
        request = urllib.request.Request('https://api.meta.ai/v1/chat/completions', data=body,
                                         headers={'Authorization': f'Bearer {self.api_key}',
                                                  'Content-Type': 'application/json'})
        for attempt in range(self.max_attempts):
            try:
                self.request_count += 1
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read(self.MAX_RESPONSE_BYTES + 1)
                    headers = getattr(response, 'headers', {})
                    request_id = headers.get('x-request-id') or headers.get('request-id')
                if len(raw) > self.MAX_RESPONSE_BYTES:
                    raise MetaAPIError('Meta returned an oversized analysis. Try a shorter lecture excerpt.')
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise TypeError
                self._record_metadata(data, request_id)
                choice = data['choices'][0]
                if not isinstance(choice, dict) or not isinstance(choice.get('message'), dict):
                    raise TypeError
                content = choice['message'].get('content')
                if choice.get('finish_reason') != 'stop' or not isinstance(content, str):
                    raise MetaAPIError('Meta returned an incomplete or refused analysis. Try a shorter lecture excerpt.')
                return content
            except urllib.error.HTTPError as exc:
                exc.close()
                if (exc.code == 429 or exc.code >= 500) and attempt + 1 < self.max_attempts:
                    time.sleep(.5 * 2 ** attempt)
                    continue
                messages = {401: 'Meta authentication failed. Check your API key.',
                            403: 'Your Meta account cannot access this model.',
                            429: 'Meta rate limit reached. Try again shortly.',
                            402: 'Meta credits or billing need attention.',
                            400: 'Meta rejected the analysis request. Check the selected model.'}
                raise MetaAPIError(messages.get(exc.code, 'Meta analysis is temporarily unavailable.'),
                                   status_code=exc.code) from None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt + 1 < self.max_attempts:
                    time.sleep(.5 * 2 ** attempt)
                    continue
                raise MetaAPIError('Could not reach Meta. Your local lecture is preserved; try again later.') from None
            except (KeyError, IndexError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
                raise MetaAPIError('Meta returned an unreadable analysis. Try again.') from None
