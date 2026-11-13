"""Unified response protocol with independently selectable execution memory."""
import json
import copy

from .legacy_context import Context as LegacyContext
from .protocol import FIELDS, RESPONSE_RULES, EDIT_RULES, parse_json, validate_response


class Context(LegacyContext):
    def __init__(self, mode='history', max_chars=6000, hybrid_turns=1):
        super().__init__(mode, max_chars, hybrid_turns)
        self.observations = None
        self.allow_edit = False

    def rules(self):
        return RESPONSE_RULES + ('\n'+EDIT_RULES if self.allow_edit else '')

    def messages(self, system, initial, runtime, history_chars):
        # Exactly the same system prompt and action examples for all memory modes.
        common = system + '\n' + self.rules()
        if self.mode == 'history':
            while self.history and sum(len(m['content']) for m in self.history) > history_chars:
                del self.history[:2]
            frame = {'runtime': runtime}
            if 'validation_error' in self.latest:
                frame['validation_error'] = self.latest['validation_error']
            return [{'role': 'system', 'content': common}, initial, *self.history,
                    {'role': 'user', 'content': json.dumps(frame)}]
        tail = self.history[-2*self.hybrid_turns:] if self.mode == 'hybrid' and self.hybrid_turns else []
        frame = {'state': self.state, 'runtime': runtime, 'latest_observation': self.latest}
        if self.observations is not None:
            memory = self.observations.frame(self.latest.get('id'))
            if memory['records']:
                frame['observation_memory'] = memory
        return [{'role': 'system', 'content': common}, initial, *tail,
                {'role': 'user', 'content': json.dumps(frame, ensure_ascii=False, separators=(',', ':'))}]

    def parse(self, text):
        return parse_json(text)

    def accept(self, response):
        action, patch = validate_response(response,self.allow_edit)
        # The frozen legacy module stays available for controls. The same pure
        # notes merge is independent of newly registered action names.
        candidate=copy.deepcopy(self.state if self.mode!='history' else {key:{} for key in FIELDS})
        for field,entries in patch.items():
            for key,value in entries.items():
                if value is None:candidate[field].pop(key,None)
                else:candidate[field][key]=value
            if len(candidate[field])>8:
                raise ValueError('Maximum 8 entries per state field; delete stale entries')
        if len(json.dumps(candidate,ensure_ascii=False))>self.max_chars:
            raise ValueError('State size limit exceeded; remove stale entries')
        if self.mode!='history':
            self.state=candidate;self.revision+=1
        return action

    def observe(self, action, result, step):
        if action.get('action') == 'invalid_response':
            self.latest['validation_error'] = result.get('error', 'Invalid response')
            return
        self.latest = {'id': f'o{step+1}', 'action': action, 'result': result}
        self.history.extend([{'role': 'assistant', 'content': json.dumps({'action': action}, ensure_ascii=False)},
                             {'role': 'user', 'content': json.dumps(self.latest, ensure_ascii=False)}])
        if self.mode != 'history':
            keep = 2*self.hybrid_turns if self.mode == 'hybrid' else 0
            self.history = self.history[-keep:] if keep else []
