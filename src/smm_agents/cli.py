from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from langfuse import get_client

from smm_agents.config import load_config
from smm_agents.graph import build_graph
from smm_agents.llm import build_llm
from smm_agents.observability import (
    flush_langfuse_with_logs,
    langfuse_enabled,
    log_langfuse_status,
    observe_if_enabled,
)
from smm_agents.state import SmmState


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _append_log(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def _format_posts(posts: list[str]) -> str:
    return "\n\n---\n\n".join(
        f"## Публикация {index}\n\n{post}"
        for index, post in enumerate(posts, start=1)
    )


def _build_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("smm_agents")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


@observe_if_enabled(name="smm_pipeline", as_type="chain", capture_input=False, capture_output=False)
def _run_pipeline(
    graph,
    initial_state: SmmState,
    run_id: str,
    model_name: str,
    logger: logging.Logger,
) -> SmmState:
    langfuse = get_client() if langfuse_enabled() else None
    if langfuse:
        logger.info("Langfuse pipeline span started: name=smm_pipeline run_id=%s", run_id)
        langfuse.update_current_span(
            input={
                "request": initial_state["user_request"],
                "platform": initial_state["platform"],
            },
            metadata={
                "run_id": run_id,
                "model": model_name,
                "max_revision_cycles": initial_state["max_revision_cycles"],
            },
        )
    else:
        logger.info("Langfuse pipeline span skipped: tracing is disabled.")
    final_state = graph.invoke(initial_state)
    if langfuse:
        langfuse.update_current_span(
            output={
                "published_posts_count": len(final_state["published_posts"]),
                "content_plan_count": len(final_state["content_plan"]),
            }
        )
        logger.info(
            "Langfuse pipeline span finished: published_posts=%s content_plan=%s",
            len(final_state["published_posts"]),
            len(final_state["content_plan"]),
        )
    return final_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SMM multi-agent LangGraph workflow.")
    parser.add_argument("request", nargs="?", help="User request for the SMM team.")
    parser.add_argument("--request-file", type=Path, help="Read request text from a file.")
    parser.add_argument("--config", type=Path, default=_project_root() / "config.json")
    parser.add_argument("--platform", default=None, help="Target social platform, for example VK.")
    parser.add_argument("--runs-dir", type=Path, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    user_request = args.request_file.read_text(encoding="utf-8").strip() if args.request_file else args.request
    if not user_request:
        raise SystemExit("Pass request text as an argument or via --request-file.")

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    runs_dir = args.runs_dir or (_project_root() / config.output.runs_dir)
    run_dir = runs_dir / run_id
    log_path = run_dir / config.output.log_file
    platform = args.platform or config.workflow.default_platform
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = _build_logger(log_path)
    log_langfuse_status(logger)

    def on_progress(node: str, state: SmmState) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        line = (
            f"[{datetime.now().isoformat(timespec='seconds')}] "
            f"{node}: task={state['current_task_num'] + 1}/{max(len(state['content_plan']), 1)} "
            f"decision={state.get('editor_decision', '-')} "
            f"revisions={state['revision_cycles']}/{state['max_revision_cycles']} "
            f"published={len(state['published_posts'])}"
        )
        print(line, flush=True)
        _append_log(log_path, line)
        if node == "Strategist":
            _append_log(log_path, f"--- short_analysis ---\n{state['short_analysis']}\n")
            _append_log(log_path, "--- content_plan ---\n" + "\n".join(state["content_plan"]) + "\n")
        elif node == "BriefCreator":
            _append_log(log_path, f"--- content_brief ---\n{state['content_brief']}\n")
        elif node == "Copywriter":
            _append_log(log_path, f"--- draft_post ---\n{state['draft_post']}\n")
        elif node == "Editor":
            _append_log(log_path, f"--- editor_feedback ---\n{state.get('editor_feedback', '')}\n")
        elif node == "Publisher":
            _append_log(log_path, f"--- final_post ---\n{state.get('final_post', '')}\n")
            post_index = len(state["published_posts"])
            _atomic_write(
                run_dir / "posts" / f"post_{post_index:03d}.md",
                state["final_post"],
            )
            _atomic_write(run_dir / "final.md", _format_posts(state["published_posts"]))
            print(
                f"Saved post {post_index}: {run_dir / 'posts' / f'post_{post_index:03d}.md'}",
                flush=True,
            )
        _atomic_write(
            run_dir / "state.partial.json",
            json.dumps(state, ensure_ascii=False, indent=2),
        )

    llm = build_llm(config.model)
    graph = build_graph(llm, on_progress=on_progress)

    initial_state: SmmState = {
        "user_request": user_request,
        "platform": platform,
        "short_analysis": "",
        "content_plan": [],
        "current_task_num": 0,
        "content_brief": "",
        "draft_post": "",
        "revision_cycles": 0,
        "max_revision_cycles": config.workflow.max_revision_cycles,
        "editor_decision": "",
        "editor_feedback": "",
        "final_post": "",
        "published_posts": [],
    }

    print(f"Run id: {run_id}")
    print(f"Log: {log_path}")
    try:
        final_state = _run_pipeline(graph, initial_state, run_id, config.model.model, logger)
    finally:
        flush_langfuse_with_logs(logger)

    final_text = _format_posts(final_state["published_posts"])
    _atomic_write(run_dir / "final.md", final_text)
    _atomic_write(run_dir / "state.json", json.dumps(final_state, ensure_ascii=False, indent=2))

    print("\nFinal post saved to:", run_dir / "final.md")
    print("Full state saved to:", run_dir / "state.json")
    print("\n" + final_text)


if __name__ == "__main__":
    main()
