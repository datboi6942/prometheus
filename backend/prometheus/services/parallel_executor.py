import asyncio
from typing import Any, List, Dict, Tuple, Set

class ParallelExecutor:
    """Classifies and executes tool calls in parallel batches where possible."""

    def __init__(self, max_parallel: int = 5):
        self.max_parallel = max_parallel

    def classify_dependencies(self, tool_calls: List[Dict[str, Any]]) -> Tuple[List[List[Dict[str, Any]]], List[Dict[str, Any]]]:
        """Classify tool calls into parallelizable batches and sequential calls.
        
        Rules:
        - READ tools (filesystem_read, grep, filesystem_list) are independent.
        - WRITE tools to DIFFERENT files are independent.
        - WRITE tools to the SAME file must be sequential.
        - shell_execute is sequential (side effects).
        
        Args:
            tool_calls: List of tool calls from the model.
            
        Returns:
            Tuple containing:
            - List of batches (each batch is a list of tool calls that can run in parallel)
            - List of sequential tool calls (that must run one after another)
        """
        read_tools = {'filesystem_read', 'grep', 'filesystem_list', 'read_diagnostics', 'glob_search', 'codebase_search'}
        write_tools = {'filesystem_write', 'filesystem_replace_lines', 'filesystem_insert', 'filesystem_search_replace', 'filesystem_delete'}
        
        parallel_batches: List[List[Dict[str, Any]]] = []
        current_parallel_batch: List[Dict[str, Any]] = []
        sequential_calls: List[Dict[str, Any]] = []
        
        # Track files being written to in current batch to avoid overlaps
        files_in_current_batch: Set[str] = set()
        
        for tc in tool_calls:
            tool_name = tc.get("tool")
            args = tc.get("args", {})
            path = args.get("path") or args.get("file")
            
            if tool_name in read_tools:
                # Read tools are always parallelizable
                if len(current_parallel_batch) >= self.max_parallel:
                    parallel_batches.append(current_parallel_batch)
                    current_parallel_batch = []
                current_parallel_batch.append(tc)
            
            elif tool_name in write_tools:
                if path and path not in files_in_current_batch:
                    # Write to a new file in this batch - parallelizable
                    if len(current_parallel_batch) >= self.max_parallel:
                        parallel_batches.append(current_parallel_batch)
                        current_parallel_batch = []
                        files_in_current_batch = set()
                    
                    current_parallel_batch.append(tc)
                    files_in_current_batch.add(path)
                else:
                    # Overlapping file or no path - sequential
                    sequential_calls.append(tc)
            
            else:
                # Other tools (shell_execute, etc.) - sequential
                sequential_calls.append(tc)
        
        if current_parallel_batch:
            parallel_batches.append(current_parallel_batch)
            
        return parallel_batches, sequential_calls

    async def execute_parallel(self, tool_calls: List[Dict[str, Any]], execute_func) -> List[Tuple[str, Dict[str, Any], str, Dict[str, Any]]]:
        """Execute tool calls in parallel batches.
        
        Args:
            tool_calls: List of tool calls.
            execute_func: Async function to execute a single tool call.
            
        Returns:
            List of results from all executed tools.
        """
        batches, sequential = self.classify_dependencies(tool_calls)
        all_results = []
        
        # Execute parallel batches
        for batch in batches:
            results = await asyncio.gather(*[execute_func(tc) for tc in batch])
            all_results.extend(results)
            
        # Execute sequential calls
        for tc in sequential:
            result = await execute_func(tc)
            all_results.append(result)
            
        return all_results
