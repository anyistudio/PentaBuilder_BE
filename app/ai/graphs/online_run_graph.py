from langgraph.graph import END, StateGraph

from app.ai.graphs.nodes import generate_result_node, prepare_context_node, validate_result_node
from app.ai.graphs.state import RunGraphState
from app.ai.providers.base import BaseLLMClient
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
        llm_client: BaseLLMClient | None,
    ) -> None:
        graph = StateGraph(RunGraphState)
        graph.add_node("prepare_context", prepare_context_node)
        graph.add_node(
            "generate_result",
            generate_result_node(
                run_type=run_type,
                context=context,
                response_preferences=response_preferences,
                snapshot=snapshot,
                baseline=baseline,
                reference_summary=reference_summary,
                calibration_summary=calibration_summary,
                llm_client=llm_client,
            ),
        )
        graph.add_node("validate_result", validate_result_node)
        graph.set_entry_point("prepare_context")
        graph.add_edge("prepare_context", "generate_result")
        graph.add_edge("generate_result", "validate_result")
        graph.add_edge("validate_result", END)
        self.graph = graph.compile()

    def invoke(self, state: RunGraphState) -> RunGraphState:
        return self.graph.invoke(state)
