"""The actual solver is executed as an openJiuwen workflow component."""
import tempfile
from pathlib import Path

from openjiuwen.core.common.logging.log_config import configure_log_config

# Configure before importing workflow: imports may emit SDK logs.
configure_log_config({
    'level': 'WARNING',
    'log_path': str(Path(tempfile.gettempdir()) / 'baseline-sdk-logs'),
    'output': ['console'],
    'interface_output': ['console'],
    'performance_output': ['console'],
})
from openjiuwen.core.workflow import Workflow, WorkflowComponent, create_workflow_session
from openjiuwen.core.session.constants import WORKFLOW_EXECUTE_TIMEOUT

from .solver import solve


class SolveTask(WorkflowComponent):
    def __init__(self, task, client, budget, trace, config):
        super().__init__()
        self.args = (task, client, budget, trace, config)
        self.result = None
        self.error = None

    async def invoke(self, inputs, session, context):
        try:
            self.result = solve(*self.args)
        except Exception as exc:
            # Preserve typed errors instead of losing them in framework wrapping.
            self.error = exc
            self.result = {'status': 'error', 'reason': type(exc).__name__}
        return {'result': self.result}


class Finish(WorkflowComponent):
    async def invoke(self, inputs, session, context):
        return inputs


async def run_task(task, client, budget, trace, config):
    component = SolveTask(task, client, budget, trace, config)
    workflow = Workflow()
    workflow.set_start_comp('solve', component)
    workflow.set_end_comp('finish', Finish(), inputs_schema={'result': '${solve.result}'})
    workflow.add_connection('solve', 'finish')
    session = create_workflow_session(envs={
        WORKFLOW_EXECUTE_TIMEOUT: min(config.task_seconds + 5, budget.remaining_seconds()),
    })
    await workflow.invoke({}, session)
    if component.error:
        raise component.error
    if component.result is None:
        raise RuntimeError('openJiuwen workflow did not execute the solver')
    return component.result
