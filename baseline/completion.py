"""Budget reservation and terminal-action policy; no answer synthesis."""
class CompletionPolicy:
    def __init__(self, config):
        self.enabled = getattr(config, 'budget_policy', 'off') == 'reserve'
        self.output_tokens = min(getattr(config, 'finish_output_tokens', 256), getattr(config, 'max_output_tokens', 1500))
        self.seconds = getattr(config, 'finish_seconds', 20)

    def frame(self, steps_left, seconds_left, available, estimated_input):
        if not self.enabled:
            return None
        reserve = estimated_input / 10 + self.output_tokens + 64
        phase = 'work'
        if steps_left <= 1 or seconds_left <= self.seconds or available <= reserve + 32:
            phase = 'submit'
        elif steps_left <= 2:
            phase = 'verify'
        instructions = {
            'work': 'Solve efficiently. Keep the reserved budget for verification and final submission.',
            'verify': 'Verification phase: avoid new exploration. Check the candidate now, or submit if already supported. Never invent an answer.',
            'submit': 'Final submission phase. Return ONLY final with an evidence-supported answer, or skip. Do not call tools. For coding the runtime will rerun unchanged tests before accepting DONE. Skip if you have no justified candidate.',
        }
        return {'phase': phase, 'reserved_cost_estimate': round(reserve, 1),
                'instruction': instructions[phase]}

    def request_budget(self, frame, available):
        if frame is None or frame['phase'] == 'submit':
            return available
        return available - frame['reserved_cost_estimate']

    def validate_action(self, frame, action):
        if frame is not None and frame['phase'] == 'submit' and action.get('action') not in ('final','skip'):
            raise ValueError('Submission phase allows only final or skip; tools cannot use the completion reserve')
