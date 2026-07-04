"""Agent Tool implementation for using agents as tools."""

from typing import Dict, Any, List, Optional
from langchain_core.tools import BaseTool
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field
import asyncio
import logging

logger = logging.getLogger(__name__)

class AgentToolInput(BaseModel):
    """Input schema for agent tools."""
    query: str = Field(description="The query or task to send to the agent")
    context: Optional[str] = Field(default=None, description="Additional context for the agent")

class AgentTool(BaseTool):
    """A tool that wraps an agent to allow it to be used by other agents."""
    
    name: str
    description: str
    agent: Any
    max_response_length: int = 2000
    call_stack: List[str] = Field(default_factory=list)
    
    def __init__(self, agent: Any, name: str = None, description: str = None):
        """Initialize the agent tool.
        
        Args:
            agent: The agent instance to wrap
            name: Custom name for the tool (defaults to agent name)
            description: Custom description (defaults to agent description)
        """
        if name is None:
            name = getattr(agent, 'name', 'agent_tool').replace(' ', '_').lower()
        
        if description is None:
            description = getattr(agent, 'description', f'Tool that uses {name} agent')
        
        # Initialize with all required fields
        super().__init__(
            name=name,
            description=description,
            args_schema=AgentToolInput,
            agent=agent
        )
        
        self.call_stack = []
    
    def _run(self, query: str, context: Optional[str] = None) -> str:
        """Run the agent tool synchronously."""
        return asyncio.run(self._arun(query, context))
    
    async def _arun(self, query: str, context: Optional[str] = None) -> str:
        """Run the agent tool asynchronously."""
        try:
            # Check for potential infinite loops
            current_agent_name = getattr(self.agent, 'name', 'unknown')
            if current_agent_name in self.call_stack:
                logger.warning(f"Potential infinite loop detected: {current_agent_name} already in call stack {self.call_stack}")
                return f"Error: Cannot call {current_agent_name} agent - would cause infinite loop. Current call chain: {' -> '.join(self.call_stack)}"
            
            # Add current agent to call stack
            self.call_stack.append(current_agent_name)
            
            try:
                # Prepare messages for the agent
                messages = [HumanMessage(content=query)]
                
                # Add context if provided
                if context:
                    context_message = HumanMessage(content=f"Additional Context: {context}")
                    messages.insert(0, context_message)
                
                # Invoke the agent
                result = await self.agent.invoke(messages)
                
                # Extract response
                response = ""
                if isinstance(result, dict):
                    if 'response' in result:
                        response = result['response']
                    elif 'messages' in result and result['messages']:
                        last_message = result['messages'][-1]
                        if hasattr(last_message, 'content'):
                            response = last_message.content
                        else:
                            response = str(last_message)
                    else:
                        response = str(result)
                else:
                    response = str(result)
                
                # Truncate if too long
                if len(response) > self.max_response_length:
                    response = response[:self.max_response_length] + "...[truncated]"
                
                return response
                
            finally:
                # Remove current agent from call stack
                if current_agent_name in self.call_stack:
                    self.call_stack.remove(current_agent_name)
                    
        except Exception as e:
            logger.error(f"Error in agent tool {self.name}: {str(e)}")
            return f"Error executing {self.name} agent: {str(e)}"
    
    def get_call_stack(self) -> List[str]:
        """Get the current call stack for debugging."""
        return self.call_stack.copy()
    
    def clear_call_stack(self):
        """Clear the call stack (useful for testing or reset)."""
        self.call_stack.clear()

def create_agent_tool(agent: Any, name: str = None, description: str = None) -> AgentTool:
    """Factory function to create an agent tool.
    
    Args:
        agent: The agent instance to wrap
        name: Custom name for the tool
        description: Custom description
        
    Returns:
        AgentTool instance
    """
    return AgentTool(agent=agent, name=name, description=description)
