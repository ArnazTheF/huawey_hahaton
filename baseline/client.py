"""Small OpenAI-compatible HTTP adapter; no implicit retries or SDK telemetry."""
import json
import urllib.error
import urllib.request
import urllib.parse
import time

from .core import StopRun


class Client:
    def __init__(self, base_url, api_key, model, budget, trace, timeout=90,
                 reasoning_mode='included', max_tokens_field='max_tokens', reasoning_budget=None, response_format=None, schema_accounting='conservative'):
        base = base_url.rstrip('/')
        self.url = base if base.endswith('/chat/completions') else base + '/chat/completions'
        self.api_key = api_key
        self.model = model
        self.budget = budget
        self.trace = trace
        self.timeout = timeout
        self.reasoning_mode = reasoning_mode
        self.max_tokens_field = max_tokens_field
        self.reasoning_budget = reasoning_budget
        self.reasoning_spent = 0
        self.response_format = response_format
        self.schema_accounting = schema_accounting
        self.last_finish_reason = None

    def accounting_messages(self, messages):
        # Schema may contribute provider input tokens; count it without injecting
        # fake chat messages into the actual request. Actual usage remains final.
        if self.response_format is None or self.schema_accounting=='messages':
            return messages
        return [*messages, {'role':'system','content':json.dumps({'response_format':self.response_format},separators=(',',':'))}]

    def complete(self, messages, task_id, max_output, task_remaining):
        reasoning_call = not self.model.endswith('-noreason')
        if reasoning_call and self.reasoning_budget is not None:
            if self.reasoning_budget-self.reasoning_spent < 32:
                raise StopRun('reasoning_budget_exhausted')
            task_remaining=min(task_remaining,self.reasoning_budget-self.reasoning_spent)
        accounting = self.accounting_messages(messages)
        cap, estimate = self.budget.allowance(accounting, max_output, task_remaining, self.model)
        payload = {'model': self.model, 'messages': messages, 'stream': False,
                   self.max_tokens_field: cap}
        if self.response_format is not None:
            payload['response_format'] = self.response_format
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + self.api_key, 'Content-Type': 'application/json'})
        self.trace.emit('request', task_id=task_id, model=self.model,
                        messages=messages, max_output=cap, input_estimate=estimate,
                        input_estimator=self.budget.estimator.mode,
                        **({'response_format':self.response_format,'schema_accounting':self.schema_accounting} if self.response_format is not None else {}))
        request_started=time.monotonic()
        try:
            try:
                response = urllib.request.urlopen(request, timeout=min(self.timeout, self.budget.remaining_seconds()))
            except urllib.error.HTTPError as redirect:
                if redirect.code not in (307, 308):
                    raise
                target = urllib.parse.urljoin(self.url, redirect.headers.get('Location', ''))
                original, destination = urllib.parse.urlsplit(self.url), urllib.parse.urlsplit(target)
                if (destination.scheme, destination.netloc) != (original.scheme, original.netloc) or target == self.url:
                    raise
                self.trace.emit('same_origin_redirect', task_id=task_id, status=redirect.code)
                redirect.close()
                request = urllib.request.Request(target, data=json.dumps(payload).encode(),
                    headers={'Authorization': 'Bearer ' + self.api_key, 'Content-Type': 'application/json'})
                response = urllib.request.urlopen(request, timeout=min(self.timeout, self.budget.remaining_seconds()))
            with response:
                body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ValueError('Response too large')
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError('Response must be an object')
        except urllib.error.HTTPError as exc:
            # Do not log headers, credentials, or arbitrary proxy response bodies.
            self.trace.emit('http_error', task_id=task_id, status=exc.code)
            raise StopRun(f'proxy_http_{exc.code}; no automatic retry') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            # The server may have billed a timed-out/malformed response.
            charged = self.budget.charge(None, estimate, cap, self.reasoning_mode)
            if reasoning_call: self.reasoning_spent += charged['cost']
            self.trace.emit('uncertain_request', task_id=task_id,
                            error_class=type(exc).__name__,reason_class=type(getattr(exc,'reason',None)).__name__,
                            elapsed_seconds=round(time.monotonic()-request_started,3),**charged)
            raise StopRun('proxy_transport_or_response_error; charge uncertain, stopped') from None
        charged = self.budget.charge(data.get('usage'), estimate, cap, self.reasoning_mode)
        if reasoning_call:
            self.reasoning_spent += charged['cost']
            self.trace.emit('reasoning_budget',task_id=task_id,model=self.model,spent=self.reasoning_spent,limit=self.reasoning_budget)
        actual_input = (data.get('usage') or {}).get('prompt_tokens', (data.get('usage') or {}).get('input_tokens'))
        self.budget.estimator.observe(accounting, actual_input, self.model)
        try:
            choice = data['choices'][0]
            content = choice['message'].get('content') or ''
            if not isinstance(content, str):
                raise ValueError('content must be text')
        except (KeyError, IndexError, TypeError, ValueError):
            raise StopRun('unsupported_proxy_response_schema') from None
        self.trace.emit('response', task_id=task_id, content=content,
                        finish_reason=choice.get('finish_reason'), usage=data.get('usage'),
                        input_estimate=estimate, input_estimate_error=None if actual_input is None else estimate-actual_input, **charged)
        self.last_finish_reason = choice.get('finish_reason')
        return content
