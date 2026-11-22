from __future__ import annotations

from typing import NotRequired, TypedDict


class SmmState(TypedDict):
    user_request: str
    platform: str
    short_analysis: str
    content_plan: list[str]
    current_task_num: int
    content_brief: str
    draft_post: str
    revision_cycles: int
    max_revision_cycles: int
    editor_decision: NotRequired[str]
    editor_feedback: NotRequired[str]
    final_post: NotRequired[str]
    published_posts: list[str]
