from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from langfuse import get_client
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from smm_agents.prompts import (
    BRIEF_CREATOR_PROMPT,
    COPYWRITER_PROMPT,
    EDITOR_PROMPT,
    PUBLISHER_PROMPT,
    STRATEGIST_PROMPT,
)
from smm_agents.observability import langfuse_enabled, observe_if_enabled
from smm_agents.state import SmmState

ProgressCallback = Callable[[str, SmmState], None]
logger = logging.getLogger("smm_agents")


@observe_if_enabled(name="llm_call", as_type="generation", capture_input=False, capture_output=False)
def _invoke_text(
    llm: BaseChatModel,
    node_name: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    langfuse = get_client() if langfuse_enabled() else None
    if langfuse:
        logger.info("Langfuse LLM generation started: node=%s", node_name)
        langfuse.update_current_generation(
            name=node_name,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=getattr(llm, "model", None),
            model_parameters={
                "temperature": getattr(llm, "temperature", None),
            },
        )
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    text = str(response.content).strip()
    if langfuse:
        langfuse.update_current_generation(output=text)
        logger.info("Langfuse LLM generation finished: node=%s output_chars=%s", node_name, len(text))
    return text


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError(f"Strategist did not return JSON object: {text}") from None
        return json.loads(match.group(0))


def _parse_strategy(text: str) -> tuple[str, list[str]]:
    data = _extract_json_object(text)
    analysis = str(data.get("short_analysis", "")).strip()
    raw_plan = data.get("content_plan", [])
    if not isinstance(raw_plan, list):
        raise ValueError("Strategist JSON field 'content_plan' must be a list.")

    content_plan = [str(item).strip() for item in raw_plan if str(item).strip()]
    if not content_plan:
        raise ValueError("Strategist returned an empty content_plan.")

    return analysis, content_plan


def _parse_editor_decision(text: str) -> str:
    head = text[:300].upper()
    if "DECISION: APPROVE" in head:
        return "APPROVE"
    if "DECISION: REVISE" in head:
        return "REVISE"
    return "REVISE"


def build_graph(llm: BaseChatModel, on_progress: ProgressCallback | None = None):
    def report(node: str, state: SmmState) -> None:
        if on_progress:
            on_progress(node, state)

    def state_for_report(state: SmmState, update: dict) -> SmmState:
        return {**state, **update}

    def strategist(state: SmmState) -> dict:
        text = _invoke_text(
            llm,
            "Strategist",
            STRATEGIST_PROMPT,
            (
                f"Исходный запрос пользователя:\n{state['user_request']}\n\n"
                f"Площадка публикации: {state['platform']}\n\n"
                "Сформируй стратегию и контент-план. Верни только валидный JSON."
            ),
        )
        short_analysis, content_plan = _parse_strategy(text)
        update = {
            "short_analysis": short_analysis,
            "content_plan": content_plan,
            "current_task_num": 0,
        }
        report("Strategist", state_for_report(state, update))
        return update

    def brief_creator(state: SmmState) -> dict:
        task = state["content_plan"][state["current_task_num"]]
        brief = _invoke_text(
            llm,
            "BriefCreator",
            BRIEF_CREATOR_PROMPT,
            (
                f"Исходный запрос пользователя:\n{state['user_request']}\n\n"
                f"Площадка: {state['platform']}\n\n"
                f"Анализ Strategist:\n{state['short_analysis']}\n\n"
                f"Пункт контент-плана #{state['current_task_num'] + 1}:\n{task}\n\n"
                "Составь ТЗ только для этого пункта."
            ),
        )
        update = {
            "content_brief": brief,
            "draft_post": "",
            "editor_decision": "",
            "editor_feedback": "",
            "final_post": "",
            "revision_cycles": 0,
        }
        report("BriefCreator", state_for_report(state, update))
        return update

    def copywriter(state: SmmState) -> dict:
        revision_block = ""
        if state.get("editor_decision") == "REVISE":
            revision_block = (
                f"\n\nЗамечания Editor к предыдущей версии:\n{state.get('editor_feedback', '')}\n\n"
                f"Предыдущий черновик:\n{state['draft_post']}"
            )

        draft = _invoke_text(
            llm,
            "Copywriter",
            COPYWRITER_PROMPT,
            (
                f"Исходный запрос пользователя:\n{state['user_request']}\n\n"
                f"Площадка: {state['platform']}\n\n"
                f"ТЗ Brief Creator:\n{state['content_brief']}"
                f"{revision_block}\n\n"
                "Напиши черновик поста."
            ),
        )
        update = {"draft_post": draft}
        report("Copywriter", state_for_report(state, update))
        return update

    def editor(state: SmmState) -> dict:
        feedback = _invoke_text(
            llm,
            "Editor",
            EDITOR_PROMPT,
            (
                f"Исходный запрос пользователя:\n{state['user_request']}\n\n"
                f"Площадка: {state['platform']}\n\n"
                f"ТЗ Brief Creator:\n{state['content_brief']}\n\n"
                f"Черновик Copywriter:\n{state['draft_post']}\n\n"
                "Проверь черновик и верни решение в заданном формате."
            ),
        )
        decision = _parse_editor_decision(feedback)
        revision_cycles = state["revision_cycles"] + (1 if decision == "REVISE" else 0)
        update = {
            "editor_decision": decision,
            "editor_feedback": feedback,
            "revision_cycles": revision_cycles,
        }
        report("Editor", state_for_report(state, update))
        return update

    def publisher(state: SmmState) -> dict:
        final_post = _invoke_text(
            llm,
            "Publisher",
            PUBLISHER_PROMPT,
            (
                f"Площадка: {state['platform']}\n\n"
                f"ТЗ Brief Creator:\n{state['content_brief']}\n\n"
                f"Одобренный или финальный после лимита черновик:\n{state['draft_post']}\n\n"
                f"Комментарий Editor:\n{state.get('editor_feedback', '')}\n\n"
                "Подготовь финальную публикацию."
            ),
        )
        published_posts = [*state["published_posts"], final_post]
        update = {
            "final_post": final_post,
            "published_posts": published_posts,
            "current_task_num": state["current_task_num"] + 1,
        }
        report("Publisher", state_for_report(state, update))
        return update

    def route_after_publisher(state: SmmState) -> str:
        if state["current_task_num"] < len(state["content_plan"]):
            return "brief_creator"
        return "end"

    def route_after_editor(state: SmmState) -> str:
        if state.get("editor_decision") == "APPROVE":
            return "publisher"
        if state["revision_cycles"] >= state["max_revision_cycles"]:
            return "publisher"
        return "copywriter"

    graph = StateGraph(SmmState)
    graph.add_node("strategist", strategist)
    graph.add_node("brief_creator", brief_creator)
    graph.add_node("copywriter", copywriter)
    graph.add_node("editor", editor)
    graph.add_node("publisher", publisher)

    graph.set_entry_point("strategist")
    graph.add_edge("strategist", "brief_creator")
    graph.add_edge("brief_creator", "copywriter")
    graph.add_edge("copywriter", "editor")
    graph.add_conditional_edges(
        "editor",
        route_after_editor,
        {"copywriter": "copywriter", "publisher": "publisher"},
    )
    graph.add_conditional_edges(
        "publisher",
        route_after_publisher,
        {"brief_creator": "brief_creator", "end": END},
    )
    return graph.compile()
