"""
Tool for marking work item status.
"""

from typing import Dict, Any, Optional, Callable, Literal
from pydantic import BaseModel, Field
from mas.elements.tools.common.base_tool import BaseTool
from mas.elements.nodes.common.workload import WorkItemStatus, WorkItemKind
from mas.elements.nodes.common.agent.constants import ToolNames


class MarkStatusArgs(BaseModel):
    """Arguments for marking work item status."""
    item_id: str = Field(
        ..., 
        description="ID of the work item to update (get from work plan context)"
    )
    status: Literal['done', 'failed'] = Field(
        ..., 
        description="""Final status for the work item. Only two valid values:
        - 'done': Task completed successfully
        - 'failed': Task failed and cannot be completed
        
        Note: 
        - IN_PROGRESS is set automatically by DelegateTaskTool (not manual)
        - PENDING is the initial state (not set via this tool)
        - LOCAL items use RecordLocalExecutionTool (auto-marks DONE)"""
    )
    notes: Optional[str] = Field(
        None, 
        description="Explanation of the status change. REQUIRED for 'failed' to explain what went wrong. Helpful for 'done' to summarize accomplishments."
    )


class MarkWorkItemStatusTool(BaseTool):
    """Mark work item as DONE or FAILED after completion."""
    
    name = ToolNames.WORKPLAN_MARK
    description = """Mark work item status as DONE or FAILED.

    Use this when:
    - 'done': Work is complete, requirements met, quality acceptable
    - 'failed': Work cannot be completed (retries exhausted, fundamentally impossible)
    
    DO NOT use this for:
    - Setting IN_PROGRESS (DelegateTaskTool does this automatically)
    - Setting PENDING (initial state only)
    
    For REMOTE items: Review responses first, then mark done/failed
    For LOCAL items: RecordLocalExecutionTool auto-marks DONE (rarely need this tool)
    
    ⚠️ DON'T MARK 'DONE' ON A RESPONSE THAT MISSES THE REQUIREMENT, BUT DON'T LOOP EITHER:
    - If response is incomplete, unclear or partial → ask ONE precise follow-up with DelegateTaskTool
    - If the response addresses the requirement (even if long, or worded differently than you would) → mark 'done'
    - Never re-ask the same question: asking again returns the same answer and costs a full agent turn
    - An item can be delegated only a few times; after that it is closed with the answers it has"""
    args_schema = MarkStatusArgs
    
    def __init__(
        self,
        get_thread_id: Callable[[], str],
        get_owner_uid: Callable[[], str],
        get_workload_service: Callable[[], Any]
    ):
        self._get_thread_id = get_thread_id
        self._get_owner_uid = get_owner_uid
        self._get_workload_service = get_workload_service
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """Mark work item status (thread-safe)."""
        args = MarkStatusArgs(**kwargs)
        
        thread_id = self._get_thread_id()
        owner_uid = self._get_owner_uid()
        workload_service = self._get_workload_service()
        workspace_service = workload_service.get_workspace_service()
        
        # VALIDATION: Check constraints before marking status
        if args.status in [WorkItemStatus.DONE, WorkItemStatus.FAILED]:
            # Load the work item to check state
            plan = workspace_service.load_work_plan(thread_id, owner_uid)
            if not plan or args.item_id not in plan.items:
                return {"success": False, "error": "Work item not found"}
            
            item = plan.items[args.item_id]
            
            # Validate state transitions
            
            # 1. LOCAL items must record execution before marking DONE
            #    (FAILED is allowed without recording, for cases where execution wasn't attempted)
            if item.kind == WorkItemKind.LOCAL and args.status == 'done':
                # Check if execution has been recorded
                if not item.result or not item.result.local_execution:
                    return {
                        "success": False,
                        "error": (
                            f"Cannot mark LOCAL item '{args.item_id}' as DONE without recording execution first. "
                            f"This validation should not trigger since RecordLocalExecutionTool automatically marks as DONE. "
                            f"If you see this error, there's a bug in the workflow."
                        )
                    }
            
            # 2. Check if trying to mark DONE while still waiting for response
            if (args.status == 'done' and
                item.status == WorkItemStatus.IN_PROGRESS and 
                item.kind == WorkItemKind.REMOTE):
                
                # Check if we have pending delegation (waiting for response)
                if item.result and item.result.pending_exchange:
                    pending_ex = item.result.pending_exchange
                    return {
                        "success": False,
                        "error": f"Cannot mark '{args.item_id}' as DONE - still waiting for response from {pending_ex.delegated_to}. DO NOT RETRY - the response will arrive in a future cycle. Either wait (finish this cycle) or use status='failed' to give up."
                    }
                
                # Check for unprocessed responses (responses that need LLM interpretation)
                # This is OK - LLM is marking DONE after interpreting the responses
                # The processed flag will be set below when status changes
        
        def update_status(item, plan):
            """Update function for atomic status change."""
            # Convert string literal to WorkItemStatus enum
            item.status = WorkItemStatus.DONE if args.status == 'done' else WorkItemStatus.FAILED
            
            if args.status == 'failed' and args.notes:
                item.error = args.notes
            
            # Mark all delegation exchanges as processed (LLM has acted by marking status)
            if item.result and item.result.delegations:
                for exchange in item.result.delegations:
                    exchange.processed = True
            
            # Store final summary if provided
            if args.notes and item.result:
                item.result.final_summary = args.notes
            
            # Mark success flag when marking DONE
            if args.status == 'done' and item.result:
                item.result.success = True
        
        success = workspace_service.atomic_update_work_item(thread_id, owner_uid, args.item_id, update_status)
        
        if not success:
            return {"success": False, "error": "Work plan or work item not found"}
        
        result = {
            "success": True,
            "item_id": args.item_id,
            "new_status": args.status  # Already a string literal ('done' or 'failed')
        }
        return result
