# src/langchain_agent/langchain_agent_simplified.py
"""
Simplified LangChain Agent - Uses Agent Bridge

This is a MUCH simpler version that leverages the agent bridge.
Instead of defining all tools manually, it just uses get_tools_for_langchain()

Benefits:
1. 50% less code than original LangChain agent
2. Automatic access to ALL your existing functions
3. Multi-file workflow integrated seamlessly
4. Single source of truth (agent_bridge.py)
"""

from typing import Dict, Any
from langchain.agents import AgentExecutor, create_react_agent
from langchain.memory import ConversationBufferMemory
from langchain.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import GEMINI_API_KEY
from src.agent_bridge import get_tools_for_langchain

class SimplifiedLangChainAgent:
    """
    Simplified LangChain agent using the agent bridge
    
    No need to manually define tools - the bridge provides everything!
    """
    
    def __init__(self, temperature: float = 0.7):
        """
        Initialize the agent
        
        Args:
            temperature: LLM temperature (0.0-1.0)
        """
        # Initialize Gemini via LangChain
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=GEMINI_API_KEY,
            temperature=temperature
        )
        
        # Memory for conversation history
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )
        
        # Get ALL tools from the bridge (no manual definition needed!)
        self.tools = get_tools_for_langchain()
        
        # Create agent
        self.agent = self._create_agent()
        
        # Create executor
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            memory=self.memory,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=15
        )
    
    def _create_agent(self):
        """Create the ReAct agent with optimized prompt"""
        
        template = """You are an expert coding assistant with access to powerful tools.

Available Tools:
{tools}

Tool Names: {tool_names}

WORKFLOW:
1. ALWAYS start with get_repo_context to understand the codebase
2. For complex multi-file tasks: use multi_file_execute (it handles everything!)
3. For simple single-file tasks: use create_file or edit_file
4. After making changes: optionally use summarize_repo to update docs

IMPORTANT:
- multi_file_execute is your MAIN tool - it can create/edit multiple files at once
- Only use create_file/edit_file for very simple single-file tasks
- Always get context first to understand existing code structure

Format:
Question: {input}
Thought: I should understand what to do
Action: tool_name
Action Input: input for the tool
Observation: tool result
... (repeat Thought/Action/Observation as needed)
Final Answer: my response to the user

Chat History: {chat_history}
Question: {input}
{agent_scratchpad}
"""
        prompt = PromptTemplate(
            template=template,
            input_variables=["input", "chat_history", "agent_scratchpad"],
            partial_variables={
                "tools": "\n".join([f"- {t.name}: {t.description}" for t in self.tools]),
                "tool_names": ", ".join([t.name for t in self.tools])
            }
        )
        
        return create_react_agent(self.llm, self.tools, prompt)
    
    def execute(self, request: str) -> str:
        """
        Execute a user request
        
        Args:
            request: Natural language request
            
        Returns:
            Agent's response
        """
        try:
            result = self.agent_executor.invoke({"input": request})
            return result['output']
        except Exception as e:
            return f"❌ Error: {e}"
    
    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics"""
        # Get conversation history length
        messages = self.memory.chat_memory.messages
        
        return {
            'total_interactions': len(messages) // 2,  # Divide by 2 (user + assistant)
            'tools_available': len(self.tools),
            'model': 'gemini-2.5-flash',
            'temperature': self.llm.temperature
        }

# ============================================================================
# Factory Function
# ============================================================================

def create_simplified_agent(temperature: float = 0.7) -> SimplifiedLangChainAgent:
    """
    Create a simplified LangChain agent
    
    Args:
        temperature: LLM creativity (0.0 = deterministic, 1.0 = creative)
        
    Returns:
        Configured agent ready to use
        
    Example:
        agent = create_simplified_agent()
        result = agent.execute("create a user authentication module")
    """
    return SimplifiedLangChainAgent(temperature=temperature)

# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    # Create agent
    agent = create_simplified_agent()
    
    # Example: Multi-file task
    print("\n" + "="*60)
    print("Example 1: Multi-file task")
    print("="*60)
    
    result = agent.execute(
        "Create a complete user authentication system with login, "
        "registration, and password hashing"
    )
    print(f"\nResult: {result}\n")
    
    # Example: Single file task
    print("="*60)
    print("Example 2: Single file task")
    print("="*60)
    
    result = agent.execute("Create a simple calculator module")
    print(f"\nResult: {result}\n")
    
    # Show stats
    stats = agent.get_stats()
    print("="*60)
    print("Statistics")
    print("="*60)
    for key, value in stats.items():
        print(f"{key}: {value}")