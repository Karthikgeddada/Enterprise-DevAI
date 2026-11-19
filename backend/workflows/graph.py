import uuid
import time
from typing import TypedDict, List, Dict, Any, Optional

from agents.planner_agent import planner_agent
from agents.coder_agent import coder_agent
from agents.context_agent import ContextAgent
from providers.registry import get_registry
from providers.errors import ProviderError, ErrorCategory
from services.persistence import get_services


class WorkflowState(TypedDict):
    project_id: str
    user_request: str
    plan_id: str
    task_ids: List[str]
    current_task_idx: int
    status: str
    logs: List[str]
    error: Optional[str]
    provider_name: Optional[str]
    model: Optional[str]


class IncrementalWorkflow:
    """Incremental coding workflow: plan -> execute -> review -> accept -> validate."""

    def __init__(self):
        self.services = get_services()
        self.registry = get_registry()

    async def plan_tasks(self, project_id, user_request, provider_name=None, model=None):
        files = self.services.project_service.list_files(project_id)
        ctx_agent = ContextAgent(files, project_id, self.services.project_service.get_file)
        project_context = ctx_agent.get_project_structure()
        tasks = await planner_agent(user_request, project_context, provider_name, model, project_id=project_id)
        plan_id = str(uuid.uuid4())
        task_records = self.services.task_service.create_plan(project_id, plan_id, tasks)
        from storage.repository import ConversationRecord
        for role, content in [('user', user_request), ('assistant', f'Created plan with {len(task_records)} tasks.')]:
            self.services.repo.save_conversation(ConversationRecord(
                id=str(uuid.uuid4()), project_id=project_id, role=role,
                content=content, created_at=time.time(),
                metadata={'plan_id': plan_id},
            ))
        return {'plan_id': plan_id, 'tasks': [{'id': t.id, 'title': t.title, 'description': t.description, 'status': t.status, 'order': t.order, 'dependencies': t.dependencies, 'acceptance_criteria': t.acceptance_criteria} for t in task_records]}

    async def execute_task(self, project_id, plan_id, task_id, user_request, provider_name=None, model=None):
        task = self.services.task_service.get_task(task_id)
        if not task or task.project_id != project_id:
            return {'success': False, 'error': 'Task not found'}
        # Retry path: failed -> pending -> running (failed -> running is not a valid transition)
        if task.status == 'failed':
            self.services.task_service.transition_task(task_id, 'pending')
        self.services.task_service.transition_task(task_id, 'running')
        try:
            files = self.services.project_service.list_files(project_id)
            ctx_agent = ContextAgent(files, project_id, self.services.project_service.get_file)
            files_affected = task.metadata.get('files_affected', [])
            context = ctx_agent.build_context_string(task.description, files_affected)
            self.services.checkpoint_service.create_checkpoint(project_id, task_id, 'running', {'task_title': task.title})
            generated_files = await coder_agent(user_request, task.title, task.description, context, provider_name, model, project_id=project_id, task_id=task_id)
            diffs = []
            for f in generated_files:
                path = f.get('path', '')
                proposed = f.get('content', '')
                base = self.services.project_service.get_file(project_id, path) or ''
                current = self.services.repo.get_file(project_id, path)
                base_ver = current.version if current else 0
                diff = self.services.diff_service.propose_change(project_id, task_id, path, base, proposed, base_ver)
                if diff:
                    diffs.append({'diff_id': diff.id, 'file_path': path, 'action': f.get('action', 'modify')})
            self.services.task_service.transition_task(task_id, 'awaiting_review')
            return {'success': True, 'task_id': task_id, 'diffs': diffs, 'message': f'Generated {len(diffs)} file changes for review'}
        except ProviderError as e:
            self.services.task_service.transition_task(task_id, 'failed', error=str(e))
            self.services.checkpoint_service.create_checkpoint(project_id, task_id, 'failed', {'error': str(e), 'category': e.category.value})
            return {'success': False, 'error': str(e), 'category': e.category.value}
        except Exception as e:
            self.services.task_service.transition_task(task_id, 'failed', error=str(e))
            self.services.checkpoint_service.create_checkpoint(project_id, task_id, 'failed', {'error': str(e)})
            return {'success': False, 'error': str(e)}

    def accept_task_changes(self, project_id, task_id, reviewer='user'):
        diffs = self.services.diff_service.get_pending_diffs(project_id)
        task_diffs = [d for d in diffs if d.task_id == task_id]
        applied, conflicts = [], []
        for d in task_diffs:
            ok, msg, _ = self.services.diff_service.accept_diff_for_project(project_id, d.id, reviewer)
            if ok: applied.append(d.file_path)
            else: conflicts.append({'file': d.file_path, 'message': msg})
        if conflicts:
            return {'success': False, 'applied': applied, 'conflicts': conflicts, 'message': f'{len(applied)} applied, {len(conflicts)} conflicts'}
        self.services.task_service.transition_task(task_id, 'validating')
        files = self.services.project_service.list_files(project_id)
        all_files = [{'path': f['path'], 'content': c} for f in files if (c := self.services.project_service.get_file(project_id, f['path'])) is not None]
        validation = self.services.validation_service.run_static_validation(project_id, all_files)
        if validation.passed:
            self.services.task_service.transition_task(task_id, 'completed')
            return {'success': True, 'applied': applied, 'validation': {'passed': True, 'summary': validation.summary, 'warnings': validation.warnings}, 'message': f'{len(applied)} files changed and validated'}
        else:
            self.services.task_service.transition_task(task_id, 'failed', error='Validation failed')
            return {'success': False, 'applied': applied, 'validation': {'passed': False, 'errors': validation.errors, 'summary': validation.summary}, 'message': 'Changes applied but validation failed'}

    def reject_task_changes(self, project_id, task_id, reviewer='user'):
        diffs = self.services.diff_service.get_pending_diffs(project_id)
        task_diffs = [d for d in diffs if d.task_id == task_id]
        rejected = [d.file_path for d in task_diffs if self.services.diff_service.reject_diff(project_id, d.id, reviewer)[0]]
        self.services.task_service.transition_task(task_id, 'failed', error='Changes rejected by user')
        return {'success': True, 'rejected': rejected}

    def pause_task(self, project_id, task_id):
        self.services.task_service.transition_task(task_id, 'paused')
        self.services.checkpoint_service.create_checkpoint(project_id, task_id, 'paused', {'reason': 'User paused'})
        return {'success': True, 'message': 'Task paused. Accepted changes preserved.'}

    async def resume_task(self, project_id, plan_id, task_id, user_request, provider_name=None, model=None):
        task = self.services.task_service.get_task(task_id)
        if not task or task.status not in ('paused', 'failed'):
            return {'success': False, 'error': f'Cannot resume task in {task.status if task else "unknown"} state'}
        diffs = self.services.diff_service.get_pending_diffs(project_id)
        task_diffs = [d for d in diffs if d.task_id == task_id]
        if task_diffs:
            # Use only valid transitions: failed->pending->running->awaiting_review
            # or paused->running->awaiting_review (paused->awaiting_review is invalid)
            if task.status == 'failed':
                self.services.task_service.transition_task(task_id, 'pending')
            self.services.task_service.transition_task(task_id, 'running')
            self.services.task_service.transition_task(task_id, 'awaiting_review')
            return {'success': True, 'message': 'Task has pending changes for review', 'diffs': [{'file_path': d.file_path, 'diff_id': d.id} for d in task_diffs]}
        return await self.execute_task(project_id, plan_id, task_id, user_request, provider_name, model)

    def get_next_task(self, project_id, plan_id):
        task = self.services.task_service.get_next_task(project_id, plan_id)
        if not task: return None
        return {'id': task.id, 'title': task.title, 'description': task.description, 'status': task.status, 'order': task.order, 'acceptance_criteria': task.acceptance_criteria}

    def get_plan_summary(self, project_id, plan_id):
        return self.services.task_service.get_plan_summary(project_id, plan_id)


_workflow = None

def get_workflow():
    global _workflow
    if _workflow is None:
        _workflow = IncrementalWorkflow()
    return _workflow

# Legacy compatibility
workflow = None
DevState = WorkflowState
