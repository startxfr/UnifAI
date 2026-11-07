from mas.elements.common.base_factory import BaseFactory
from mas.elements.common.exceptions import PluginConfigurationError
from .config import OrchestratorNodeConfig
from .orchestrator_node import OrchestratorNode
from .identifiers import Identifier


class OrchestratorNodeFactory(BaseFactory[OrchestratorNodeConfig, OrchestratorNode]):
    """
    Factory for creating OrchestratorNode instances.
    
    Handles dependency injection and configuration validation
    for orchestrator nodes.
    """

    def accepts(self, cfg: OrchestratorNodeConfig, element_type: str) -> bool:
        """Check if this factory can create the requested element type."""
        return element_type == Identifier.TYPE

    def create(self, cfg: OrchestratorNodeConfig, **deps) -> OrchestratorNode:
        """
        Create an OrchestratorNode instance.
        
        Args:
            cfg: Orchestrator node configuration
            **deps: Injected dependencies (llm, tools)
            
        Returns:
            Configured OrchestratorNode instance
            
        Raises:
            PluginConfigurationError: If creation fails
        """
        try:
            element_deps = deps.pop("deps", None)
            tracing_service = element_deps.tracing_service if element_deps else None

            return OrchestratorNode(
                llm=_with_token_cap(deps.pop("llm"), cfg.max_tokens_per_turn),
                tools=deps.pop("tools", []),
                system_message=cfg.system_message,
                max_rounds=cfg.max_rounds,
                history_enabled=cfg.history_enabled,
                history_max_turns=cfg.history_max_turns,
                history_token_budget=cfg.history_token_budget,
                retries=cfg.retries,
                tracing_service=tracing_service,
            )
        except Exception as e:
            raise PluginConfigurationError(
                f"OrchestratorNodeFactory.create failed: {e}",
                cfg.dict()
            ) from e


def _with_token_cap(llm, cap):
    """The node's model client with the per-turn token ceiling of its task (R-543); a client that cannot count keeps
    working without one."""
    return llm.with_token_cap(cap) if cap and hasattr(llm, "with_token_cap") else llm
