"""Bounded explicit execution state, independent of task names and expected answers."""
import copy
import json

FIELDS = {'facts', 'hypotheses', 'rejected', 'open_questions', 'artifacts'}
STATE_RULES = '''Return exactly {"state_patch": {...}, "action": {...}}.
The action object uses the same tool/final/skip schema as above.
state_patch may contain facts, hypotheses, rejected, open_questions, artifacts.
Each field is a dictionary of short named entries. Each entry is a string; null deletes
an entry. Omitted entries remain unchanged. Max 8 entries per field, 240 characters
per value. facts are your evidence-backed notes, NOT authoritative verified facts:
cite observation IDs such as o1. Keep hypotheses separate from observations.
Store only useful changes, not a transcript; {} is valid. Do not rewrite unchanged
state. No extra reasoning text. Runtime fields cannot be changed.
Record what the latest observation established, not hoped-for results of the next action.
Files remain available for rereading. Unknown task types use this same general schema.'''


class Context:
    def __init__(self, mode='history', max_chars=6000, hybrid_turns=1):
        self.mode, self.max_chars, self.hybrid_turns = mode, max_chars, hybrid_turns
        self.state = {key: {} for key in sorted(FIELDS)}
        self.history = []
        self.latest = {'id': 'o0', 'result': 'Workspace ready'}
        self.revision = 0

    def messages(self, system, initial, runtime, history_chars):
        if self.mode == 'history':
            while self.history and sum(len(m['content']) for m in self.history) > history_chars:
                del self.history[:2]
            return [{'role': 'system', 'content': system}, initial, *self.history,
                    {'role': 'user', 'content': json.dumps({'runtime': runtime})}]
        tail = self.history[-2*self.hybrid_turns:] if self.mode == 'hybrid' and self.hybrid_turns else []
        frame = {'state': self.state, 'runtime': runtime, 'latest_observation': self.latest}
        return [{'role': 'system', 'content': system+'\n'+STATE_RULES}, initial, *tail,
                {'role': 'user', 'content': json.dumps(frame, ensure_ascii=False, separators=(',', ':'))}]

    def accept(self, response):
        if self.mode == 'history':
            return response
        if set(response) != {'state_patch', 'action'}:
            raise ValueError('Required keys: state_patch, action')
        patch, action = response['state_patch'], response['action']
        if not isinstance(action, dict) or action.get('action') not in {'bash','read','write','final','skip'}:
            raise ValueError('Invalid action object')
        required = {'bash': ('command',), 'read': ('path',), 'write': ('path','content'),
                    'final': ('answer',), 'skip': ()}[action['action']]
        if any(not isinstance(action.get(key), str) for key in required):
            raise ValueError('Invalid action arguments')
        if not isinstance(patch, dict) or set(patch)-FIELDS:
            raise ValueError('Unknown state fields; runtime is read-only')
        candidate = copy.deepcopy(self.state)
        for field, entries in patch.items():
            if not isinstance(entries, dict):
                raise ValueError('State fields must be dictionaries; delete entries, not whole fields')
            for key, value in entries.items():
                if not isinstance(key, str) or not 1 <= len(key) <= 48:
                    raise ValueError('State key length must be 1..48')
                if value is None:
                    candidate[field].pop(key, None)
                elif isinstance(value, str) and len(value) <= 240:
                    candidate[field][key] = value
                else:
                    raise ValueError('State values must be strings <=240 chars or null')
            if len(candidate[field]) > 8:
                raise ValueError('Maximum 8 entries per state field; delete stale entries')
        if len(json.dumps(candidate, ensure_ascii=False)) > self.max_chars:
            raise ValueError('State size limit exceeded; remove stale entries')
        self.state = candidate
        self.revision += 1
        return action

    def observe(self, action, result, step):
        if action.get('action') == 'invalid_response' and self.mode != 'history':
            self.latest['validation_error'] = result.get('error', 'Invalid response')
            return
        self.latest = {'id': f'o{step+1}', 'action': action, 'result': result}
        response = {'state_patch': {}, 'action': action} if self.mode != 'history' else action
        self.history.extend([{'role': 'assistant', 'content': json.dumps(response, ensure_ascii=False)},
                             {'role': 'user', 'content': json.dumps(self.latest, ensure_ascii=False)}])
        if self.mode != 'history':
            keep = 2*self.hybrid_turns if self.mode == 'hybrid' else 0
            self.history = self.history[-keep:] if keep else []
