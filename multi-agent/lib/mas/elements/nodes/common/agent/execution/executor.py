"""
Simplified agent action executor for direct tool execution.

This module provides direct execution of agent actions using ToolExecutorManager
without unnecessary conversion layers. Supports both single and parallel execution.

Design Principles:
- Direct Execution: Uses ToolExecutorManager directly without conversion
- Parallel Support: Can execute multiple actions simultaneously
- Clean Error Handling: Simple, robust error handling
- No Special Tools: Removes unnecessary complexity
"""

import json
import time
import asyncio
from typing import Dict, List, Optional, Tuple, Union
from mas.elements.tools.common.base_tool import BaseTool
from mas.elements.tools.common.execution import ToolExecutorManager, ExecutionMode
from mas.elements.tools.common.execution.models import (
    ToolExecutionRequest, ToolExecutionResponse, BatchToolExecutionResponse
)
from ..primitives import AgentAction, AgentObservation, ActionStatus
from ..constants import ToolExecutionDefaults
from global_utils.utils.async_bridge import get_async_bridge


class AgentActionExecutor:
    """
    Simplified executor for agent actions using ToolExecutorManager.
    
    Provides direct execution of agent actions without conversion layers.
    Supports both single action execution and parallel batch execution.
    
    Features:
    - Direct ToolExecutorManager usage
    - Parallel action execution support
    - Clean error handling without special tools
    - Async and sync interfaces
    
    Example:
        executor = AgentActionExecutor(
            tool_executor_manager=tool_manager,
            validate_args=True
        )
        
        # Single action
        observation = executor.execute(action)
        
        # Multiple actions in parallel
        observations = executor.execute_batch([action1, action2])
    """
    
    def __init__(
        self,
        *,
        tool_executor_manager: ToolExecutorManager,
        validate_args: bool = ToolExecutionDefaults.VALIDATE_ARGS,
        max_identical_calls: int = ToolExecutionDefaults.MAX_IDENTICAL_TOOL_CALLS
    ):
        """
        Initialize agent action executor.
        
        Args:
            tool_executor_manager: ToolExecutorManager instance for tool execution
            validate_args: Whether to validate tool arguments before execution
        """
        self.tool_executor_manager = tool_executor_manager
        self.validate_args = validate_args
        # One executor serves one agent run: identical calls are counted for that run only.
        self.max_identical_calls = max_identical_calls
        self._identical_calls: Dict[str, int] = {}
    
    def execute(self, action: AgentAction) -> AgentObservation:
        """
        Execute a single agent action and return observation.
        
        Args:
            action: Agent action to execute
            
        Returns:
            AgentObservation with execution results
        """
        result = self.execute_batch([action])[0]
        return result
    
    def execute_batch(self, actions: List[AgentAction]) -> List[AgentObservation]:
        """
        Execute multiple agent actions in parallel.
        
        Args:
            actions: List of agent actions to execute
            
        Returns:
            List of AgentObservations in same order as input actions
        """
        if not actions:
            return []
        
        with get_async_bridge() as bridge:
            result = bridge.run(self._execute_batch_async(actions))
            return result
    
    async def _execute_batch_async(self, actions: List[AgentAction]) -> List[AgentObservation]:
        """
        Internal async method for batch execution.
        
        Args:
            actions: List of actions to execute
            
        Returns:
            List of observations in same order as actions
        """
        start_time = time.time()
        
        try:
            # Create ToolExecutionRequests and track missing tools
            requests = []
            missing_tools = []
            repeated = []
            
            for action in actions:
                # Check if tool exists
                if not self.tool_executor_manager.has_tool(action.tool):
                    missing_tools.append(action)
                    continue
                # A model can loop on a tool whose answer never changes (same query, same result): past
                # max_identical_calls the call is not executed and the model is told to answer instead.
                key = self._call_key(action)
                count = self._identical_calls.get(key, 0)
                if count >= self.max_identical_calls:
                    repeated.append((action, count))
                    continue
                self._identical_calls[key] = count + 1
                
                request = ToolExecutionRequest(
                    tool_name=action.tool,
                    tool_call_id=action.id,
                    args=action.tool_input,
                    context={
                        "agent_action": True,
                        "action_id": action.id,
                        "validate_args": self.validate_args
                    }
                )
                requests.append(request)
            
            # Create observations for missing tools
            observations = []
            for action, count in repeated:
                observations.append(AgentObservation(
                    action_id=action.id,
                    tool=action.tool,
                    output=ToolExecutionDefaults.REPEATED_CALL_MESSAGE.format(tool=action.tool, count=count),
                    success=True,
                    execution_time=0.0,
                    metadata={"repeated_call": True}
                ))
            for action in missing_tools:
                observations.append(AgentObservation(
                    action_id=action.id,
                    tool=action.tool,
                    output=None,
                    success=False,
                    error=Exception(f"Tool '{action.tool}' not found"),
                    execution_time=time.time() - start_time
                ))
            
            if requests:
                # Execute via ToolExecutorManager (uses configured execution mode)
                batch_response = await self.tool_executor_manager.execute_requests_async(
                    requests=requests
                    # No mode specified - uses manager's configured execution_mode
                )
                
                # Convert responses to observations for successful tools
                skipped = {a.id for a in missing_tools} | {a.id for a, _ in repeated}
                for action in actions:
                    if action.id in skipped:
                        continue  # Already handled above
                        
                    response = batch_response.get_response(action.id)
                    
                    if response:
                        observation = self._response_to_observation(action, response, start_time)
                    else:
                        # Missing response - shouldn't happen but handle gracefully
                        observation = AgentObservation(
                            action_id=action.id,
                            tool=action.tool,
                            output=None,
                            success=False,
                            error=Exception(f"No response received for tool '{action.tool}'"),
                            execution_time=time.time() - start_time
                        )
                    
                    observations.append(observation)
            
            
            return observations
            
        except Exception as e:
            return [
                AgentObservation(
                    action_id=action.id,
                    tool=action.tool,
                    output=None,
                    success=False,
                    error=e,
                    execution_time=time.time() - start_time,
                    metadata={"error_type": "execution_error"}
                )
                for action in actions
            ]
    
    @staticmethod
    def _call_key(action: AgentAction) -> str:
        try:
            args = json.dumps(action.tool_input, sort_keys=True, default=str)
        except (TypeError, ValueError):
            args = repr(action.tool_input)
        return f"{action.tool}\x00{args}"

    def _response_to_observation(
        self, 
        action: AgentAction, 
        response: ToolExecutionResponse,
        start_time: float
    ) -> AgentObservation:
        """
        Convert ToolExecutionResponse to AgentObservation.
        
        Args:
            action: Original agent action
            response: Tool execution response
            start_time: Execution start time
            
        Returns:
            AgentObservation with converted data
        """
        return AgentObservation(
            action_id=action.id,
            tool=action.tool,
            output=response.result if response.success else None,
            success=response.success,
            error=Exception(str(response.error)) if response.error else None,
            execution_time=time.time() - start_time,
            metadata={
                "tool_execution_time": getattr(response, 'execution_time', None),
                "tool_call_id": response.tool_call_id
            }
        )

