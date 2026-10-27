"""Small Meta Model API client; no SDK or credentials in the repository.

Protocol reference: https://dev.meta.ai/docs/cookbook/structured-output
"""
import json
import os
import time
import urllib.error
import urllib.request


class MetaAPIError(ValueError):
    """A sanitized error that is safe to display in the desktop UI."""


class MetaClient:
    def __init__(self, api_key=None, model=None, *, opener=None, timeout=60):
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
        self.last_usage = {}

    def complete(self, messages, schema):
        if not self.api_key:
            raise MetaAPIError('Add a Meta API key in Accounts & Setup, or set MODEL_API_KEY.')
        body = json.dumps({'model': self.model, 'messages': messages,
                           'max_completion_tokens': 8192,
                           'response_format': {'type': 'json_schema', 'json_schema': {
                               'name': 'lecture_findings', 'schema': schema}}}).encode('utf-8')
        request = urllib.request.Request('https://api.meta.ai/v1/chat/completions', data=body,
                                         headers={'Authorization': f'Bearer {self.api_key}',
                                                  'Content-Type': 'application/json'})
        for attempt in range(3):
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    data = json.loads(response.read(2_000_001))
                choice = data['choices'][0]
                content = choice['message'].get('content')
                if choice.get('finish_reason') != 'stop' or not isinstance(content, str):
                    raise MetaAPIError('Meta returned an incomplete or refused analysis. Try a shorter lecture excerpt.')
                self.last_usage = data.get('usage', {})
                return content
            except urllib.error.HTTPError as exc:
                exc.close()
                if (exc.code == 429 or exc.code >= 500) and attempt < 2:
                    time.sleep(.5 * 2 ** attempt)
                    continue
                messages = {401: 'Meta authentication failed. Check your API key.',
                            403: 'Your Meta account cannot access this model.',
                            429: 'Meta rate limit reached. Try again shortly.',
                            402: 'Meta credits or billing need attention.',
                            400: 'Meta rejected the analysis request. Check the selected model.'}
                raise MetaAPIError(messages.get(exc.code, 'Meta analysis is temporarily unavailable.')) from None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt < 2:
                    time.sleep(.5 * 2 ** attempt)
                    continue
                raise MetaAPIError('Could not reach Meta. Your local lecture is preserved; try again later.') from None
            except (KeyError, IndexError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
                raise MetaAPIError('Meta returned an unreadable analysis. Try again.') from None
