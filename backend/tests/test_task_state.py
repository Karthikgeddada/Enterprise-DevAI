import pytest
from workflows.task_state import TaskState, can_transition, is_terminal, can_resume


class TestTaskState:

    def test_valid_transition_pending_to_running(self):
        assert can_transition('pending', 'running')

    def test_valid_transition_running_to_awaiting_review(self):
        assert can_transition('running', 'awaiting_review')

    def test_valid_transition_awaiting_review_to_completed(self):
        assert can_transition('awaiting_review', 'completed')

    def test_valid_transition_failed_to_pending(self):
        assert can_transition('failed', 'pending')

    def test_valid_transition_paused_to_running(self):
        assert can_transition('paused', 'running')

    def test_invalid_transition_pending_to_completed(self):
        assert not can_transition('pending', 'completed')

    def test_invalid_transition_completed_to_running(self):
        assert not can_transition('completed', 'running')

    def test_invalid_state(self):
        assert not can_transition('invalid_state', 'running')
        assert not can_transition('running', 'invalid_state')

    def test_terminal_states(self):
        assert is_terminal('completed')
        assert is_terminal('cancelled')

    def test_non_terminal_states(self):
        assert not is_terminal('pending')
        assert not is_terminal('running')
        assert not is_terminal('paused')
        assert not is_terminal('failed')

    def test_can_resume_paused(self):
        assert can_resume('paused')

    def test_can_resume_failed(self):
        assert can_resume('failed')

    def test_cannot_resume_completed(self):
        assert not can_resume('completed')
        assert not can_resume('running')
        assert not can_resume('pending')

    def test_all_task_states_exist(self):
        states = [s.value for s in TaskState]
        assert 'pending' in states
        assert 'running' in states
        assert 'awaiting_review' in states
        assert 'validating' in states
        assert 'completed' in states
        assert 'failed' in states
        assert 'paused' in states
        assert 'cancelled' in states