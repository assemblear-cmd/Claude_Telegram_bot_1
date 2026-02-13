"""Pipeline transition table: maps current state to (agent_key, next_state)."""

from __future__ import annotations

from src.orchestrator.state import PipelineState

# Map: current_state -> (agent_key, next_state_on_success)
TRANSITIONS: dict[PipelineState, tuple[str, PipelineState]] = {
    PipelineState.CREATED: ("source_researcher", PipelineState.RESEARCHING),
    PipelineState.RESEARCHING: ("content_parser", PipelineState.PARSING),
    PipelineState.PARSING: ("content_writer", PipelineState.WRITING),
    PipelineState.WRITING: ("fact_checker", PipelineState.FACT_CHECKING),
    PipelineState.FACT_CHECKING: ("link_inserter", PipelineState.INSERTING_LINKS),
    PipelineState.INSERTING_LINKS: ("publisher", PipelineState.PENDING_REVIEW),
    PipelineState.SCHEDULING: ("post_scheduler", PipelineState.SCHEDULED),
}
