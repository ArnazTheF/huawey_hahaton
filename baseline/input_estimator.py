"""Online prompt-size calibration using provider usage, never local model weights."""
import json
import math
import re
from collections import defaultdict, deque


def prompt_bytes(messages):
    return len(json.dumps(messages, ensure_ascii=False).encode())


class InputEstimator:
    def __init__(self, mode='legacy'):
        self.mode = mode
        self.ratios = defaultdict(lambda: deque(maxlen=32))

    def estimate(self, messages, model='default'):
        size = prompt_bytes(messages)
        samples = self.ratios[model]
        if self.mode == 'legacy' or not samples:
            return size + 256
        # Conservative envelope of recent observations, plus formatting slack.
        # This is an estimate, NOT an exact tokenizer or a guaranteed upper bound.
        serialized = json.dumps(messages, ensure_ascii=False)
        # Digits and punctuation often tokenize much more densely than prose.
        # A second, independent heuristic avoids extrapolating prose calibration
        # blindly to CSV, IDs, code, and multilingual text. No exact-token claim.
        units = sum(math.ceil(len(part.encode()) / 4) if part.isalpha() else 1
                    for part in re.findall(r"[^\W\d_]+|[0-9]|[^\w\s]|_", serialized))
        lexical_guard = math.ceil(units * 1.10 + 64)
        return max(lexical_guard, math.ceil(size * max(samples) * 1.15 + 64))

    def observe(self, messages, input_tokens, model='default'):
        if self.mode != 'calibrated':
            return
        if isinstance(input_tokens, bool) or not isinstance(input_tokens, (int, float)):
            return
        if not math.isfinite(input_tokens) or input_tokens <= 0:
            return
        self.ratios[model].append(input_tokens / max(1, prompt_bytes(messages)))
