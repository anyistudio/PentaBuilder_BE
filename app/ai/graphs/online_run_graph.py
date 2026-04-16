from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.ai.graphs.nodes import (
    decide_tool_need_node,
    generate_result_node,
    prepare_context_node,
    repair_result_node,
    tool_execute_node,
    tool_select_node,
    validate_result_node,
)
from app.ai.graphs.state import RunGraphState
from app.ai.orchestration.prompt_builder import PromptPackage, build_prompt_package
from app.ai.providers.base import BaseLLMClient
from app.ai.tools.catalog_tools import CatalogToolset
from app.catalog.registry import CatalogSnapshot
from app.domain.enums import RunType
from app.domain.match_context import MatchContext, ResponsePreferences


class OnlineRunGraph:
    def __init__(
        self,
        *,
        run_type: RunType,
        context: MatchContext,
        response_preferences: ResponsePreferences,
        snapshot: CatalogSnapshot,
        baseline: dict | None,
        reference_summary: str | None,
        calibration_summary: str | None,
        session_memory_summary: str | None,
        reply_to_run_summary: str | None,
        llm_client: BaseLLMClient | None,
        session: Session,
        toolset: CatalogToolset,
    ) -> None:
        self.run_type = run_type
        self.context = context
        self.response_preferences = response_preferences
        self.snapshot = snapshot
        self.baseline = baseline
        self.reference_summary = reference_summary
        self.calibration_summary = calibration_summary
        self.session_memory_summary = session_memory_summary
        self.reply_to_run_summary = reply_to_run_summary

        self._prepare_context = prepare_context_node
        self._decide_tool_need = decide_tool_need_node(
            run_type=run_type,
            context=context,
            baseline=baseline,
        )
        self._tool_select = tool_select_node(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            baseline=baseline,
            reference_summary=reference_summary,
            calibration_summary=calibration_summary,
            session_memory_summary=session_memory_summary,
            reply_to_run_summary=reply_to_run_summary,
            llm_client=llm_client,
        )
        self._tool_execute = tool_execute_node(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            session=session,
            toolset=toolset,
        )
        self._generate_result = generate_result_node(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            baseline=baseline,
            reference_summary=reference_summary,
            calibration_summary=calibration_summary,
            session_memory_summary=session_memory_summary,
            reply_to_run_summary=reply_to_run_summary,
            llm_client=llm_client,
        )
        self._validate_result = validate_result_node(
            run_type=run_type,
            context=context,
            snapshot=snapshot,
        )
        self._repair_result = repair_result_node(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            baseline=baseline,
            reference_summary=reference_summary,
            calibration_summary=calibration_summary,
            session_memory_summary=session_memory_summary,
            reply_to_run_summary=reply_to_run_summary,
            llm_client=llm_client,
        )

        graph = StateGraph(RunGraphState)
        graph.add_node("prepare_context", self._prepare_context)
        graph.add_node("decide_tool_need", self._decide_tool_need)
        graph.add_node("tool_select", self._tool_select)
        graph.add_node("tool_execute", self._tool_execute)
        graph.add_node("generate_result", self._generate_result)
        graph.add_node("validate_result", self._validate_result)
        graph.add_node("repair_result", self._repair_result)
        graph.set_entry_point("prepare_context")
        graph.add_edge("prepare_context", "decide_tool_need")
        graph.add_conditional_edges(
            "decide_tool_need",
            lambda state: "tool_select" if state.get("need_tools") else "generate_result",
        )
        graph.add_conditional_edges(
            "tool_select",
            lambda state: (
                "tool_execute"
                if state.get("pending_tool_calls")
                else "decide_tool_need"
                if state.get("retry_tool_planning")
                else "generate_result"
            ),
        )
        graph.add_edge("tool_execute", "decide_tool_need")
        graph.add_edge("generate_result", "validate_result")
        graph.add_conditional_edges(
            "validate_result",
            lambda state: "repair_result" if state.get("repair_requested") else END,
        )
        graph.add_edge("repair_result", "validate_result")
        self.graph = graph.compile()

    def invoke(self, state: RunGraphState) -> RunGraphState:
        return self.graph.invoke(state)

    def collect_tool_context(self, state: RunGraphState) -> RunGraphState:
        merged_state: RunGraphState = dict(state)
        merged_state.update(self._prepare_context(merged_state))
        while True:
            merged_state.update(self._decide_tool_need(merged_state))
            if not merged_state.get("need_tools"):
                merged_state["tool_context_ready"] = True
                return merged_state
            merged_state.update(self._tool_select(merged_state))
            if merged_state.get("retry_tool_planning"):
                continue
            if not merged_state.get("pending_tool_calls"):
                merged_state["tool_context_ready"] = True
                return merged_state
            merged_state.update(self._tool_execute(merged_state))

    def build_prompt_package(
        self,
        *,
        operation_context: dict,
        output_mode: str = "json",
        response_schema: dict[str, object] | None = None,
        streamed_text: str | None = None,
        tool_facts: dict[str, list[dict[str, object]]] | None = None,
    ) -> PromptPackage:
        return build_prompt_package(
            run_type=self.run_type,
            context=self.context,
            response_preferences=self.response_preferences,
            operation_context=operation_context,
            baseline=self.baseline,
            reference_summary=self.reference_summary,
            calibration_summary=self.calibration_summary,
            session_memory_summary=self.session_memory_summary,
            reply_to_run_summary=self.reply_to_run_summary,
            snapshot=self.snapshot,
            tool_facts=tool_facts,
            output_mode=output_mode,
            response_schema=response_schema,
            streamed_text=streamed_text,
        )

    def finalize_existing_result(self, state: RunGraphState) -> RunGraphState:
        merged_state: RunGraphState = dict(state)
        merged_state.update(self._prepare_context(merged_state))
        merged_state.update(self._validate_result(merged_state))
        while merged_state.get("repair_requested"):
            merged_state.update(self._repair_result(merged_state))
            merged_state.update(self._validate_result(merged_state))
        return merged_state
