"""Shared response contract. Parsing/validation has no side effects."""
import json

FIELDS = {'facts', 'hypotheses', 'rejected', 'open_questions', 'artifacts'}
RESPONSE_RULES = '''Response protocol: unified-v1.
Return exactly one JSON object, without prose or Markdown fences.
The required action is an object, for example:
{"action":{"action":"bash","command":"python3 -c 'print(1+1)'"}}
{"action":{"action":"read","path":"library.py"}}
{"action":{"action":"write","path":"library.py","content":"..."}}
{"action":{"action":"final","answer":"42"}}
{"action":{"action":"skip","reason":"missing required data"}}
The optional state_patch is an object. Omission or {} means no change.
When a state block is provided, retain only information useful for future actions.
Without a state block, omit state_patch. Never repeat unchanged entries.
State fields: facts, hypotheses, rejected, open_questions, artifacts.
Each field maps short keys to strings (max 8 entries, key 1..48 chars, value <=240
chars); null deletes an entry. Omitted entries remain. Example:
{"action":{"action":"read","path":"x.py"},"state_patch":{"hypotheses":{"h1":"Check empty input"}}}
Facts are your evidence-backed notes, NOT authoritative verified facts; cite
observation IDs. Keep hypotheses separate. Record observed outcomes, never assume
that a proposed action succeeded. Runtime fields cannot be changed.
Files can be reread. No extra reasoning text is required.'''


def parse_json(text):
    """Accept complete JSON or a single fenced JSON block; never extract arbitrary prose."""
    if not isinstance(text, str):
        raise ValueError('Response must be text')
    text = text.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if len(lines) < 3 or lines[0] not in ('```', '```json') or lines[-1] != '```':
            raise ValueError('Expected one JSON object')
        text = '\n'.join(lines[1:-1])
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    result = json.loads(text, object_pairs_hook=unique_keys)
    if not isinstance(result, dict):
        raise ValueError('Expected a JSON object')
    return result


def validate_action(action, allow_edit=False):
    if not isinstance(action, dict) or not isinstance(action.get('action'), str):
        raise ValueError('Invalid action object')
    kind = action['action']
    required = {'bash': ('command',), 'read': ('path',), 'write': ('path','content'),
                'final': ('answer',), 'skip': ()}
    if allow_edit:
        required['edit']=('path','old','new')
    if kind not in required:
        raise ValueError('Unknown action')
    allowed = {'action', *required[kind]} | ({'reason'} if kind == 'skip' else set())
    if set(action)-allowed or any(not isinstance(action.get(key), str) for key in required[kind]):
        raise ValueError('Invalid action arguments')
    if 'reason' in action and not isinstance(action['reason'], str):
        raise ValueError('Skip reason must be a string')
    if kind == 'final' and (not action['answer'].strip() or len(action['answer']) > 10000):
        raise ValueError('Answer must be a nonempty string <=10000 characters')
    if kind == 'edit' and not action['old']:
        raise ValueError('edit.old must be nonempty')
    return action


def validate_response(response, allow_edit=False):
    if not isinstance(response, dict) or 'action' not in response or set(response)-{'action','state_patch'}:
        raise ValueError('Required action object; only optional state_patch is allowed')
    action=validate_action(response['action'],allow_edit)
    patch = response.get('state_patch', {})
    if not isinstance(patch, dict) or set(patch)-FIELDS:
        raise ValueError('Unknown state fields; runtime is read-only')
    for entries in patch.values():
        if not isinstance(entries, dict):
            raise ValueError('State fields must be dictionaries; delete entries, not whole fields')
        for key, value in entries.items():
            if not isinstance(key, str) or not 1 <= len(key) <= 48:
                raise ValueError('State key length must be 1..48')
            if value is not None and (not isinstance(value, str) or len(value) > 240):
                raise ValueError('State values must be strings <=240 chars or null')
    return action, patch


EDIT_RULES = '''Additional action: {"action":{"action":"edit","path":"library.py","old":"exact existing text","new":"replacement text"}}.
The old text must match exactly once; ambiguity or absence makes no change.
Prefer a small edit to rewriting an entire file. Never edit test files.'''
