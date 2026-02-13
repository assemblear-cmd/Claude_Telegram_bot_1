"""Pipeline state machine definitions."""

from __future__ import annotations

from enum import Enum


class PipelineState(str, Enum):
    # Creation flow
    CREATED = "created"
    RESEARCHING = "researching"
    PARSING = "parsing"
    WRITING = "writing"
    FACT_CHECKING = "fact_checking"
    INSERTING_LINKS = "inserting_links"

    # Review flow
    PENDING_REVIEW = "pending_review"
    ADMIN_EDITING = "admin_editing"

    # Publication flow
    SCHEDULING = "scheduling"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"

    # Terminal / error
    REJECTED = "rejected"
    FAILED = "failed"


# States where the pipeline pauses and waits for external input
PAUSE_STATES = {
    PipelineState.PENDING_REVIEW,
    PipelineState.SCHEDULED,
    PipelineState.PUBLISHED,
    PipelineState.REJECTED,
    PipelineState.FAILED,
}

# States where admin can take action
ACTIONABLE_STATES = {
    PipelineState.PENDING_REVIEW,
}

# Terminal states (no further transitions possible)
TERMINAL_STATES = {
    PipelineState.PUBLISHED,
    PipelineState.REJECTED,
    PipelineState.FAILED,
}
