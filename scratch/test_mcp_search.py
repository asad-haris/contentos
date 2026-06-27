"""Test MCP Search Tool in isolation.

Loads environment variables, validates keys, initializes connection parameters,
and executes a direct web search query to inspect the raw server output.
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

# Load env
load_dotenv()

# Add project root to sys.path
sys.path.append(os.getcwd())

from config.mcp_config import web_search, get_session_manager

async def test_search():
    print("--- MCP WEB SEARCH TOOL ISOLATION TEST ---")
    
    # 1. Check API keys loaded from .env
    search_key = os.environ.get("MCP_SEARCH_API_KEY", "")
    google_key = os.environ.get("GOOGLE_API_KEY", "")
    
    print("\n[Step 1] Verifying environment variables:")
    print(f"GOOGLE_API_KEY loaded:      {bool(google_key)} (Placeholder check: {'YES' if 'gemini' in google_key.lower() or 'placeholder' in google_key.lower() else 'NO'})")
    print(f"MCP_SEARCH_API_KEY loaded:  {bool(search_key)} (Placeholder check: {'YES' if 'search_key' in search_key.lower() or 'placeholder' in search_key.lower() or 'dummy' in search_key.lower() else 'NO'})")
    
    if not search_key or "your_search_api_key" in search_key or "dummy" in search_key:
        print("\n[WARNING] MCP_SEARCH_API_KEY is not set or is using placeholder/dummy. The tool will fall back to local simulation.")
    
    # 2. Test initialization of MCP tool
    print("\n[Step 2] Initializing MCPSessionManager...")
    try:
        session_manager = get_session_manager()
        print("MCPSessionManager initialized successfully.")
    except Exception as e:
        print(f"Error: Failed to initialize MCPSessionManager: {e}", file=sys.stderr)
        return

    # 3. Execute search query
    query = "gen z burnout statistics 2025"
    print(f"\n[Step 3] Executing direct search for: '{query}'...")
    
    try:
        # We temporarily unset the simulated check to force a real MCP connection attempt
        # so we can inspect the raw connection error if any
        if not search_key or "your_search_api_key" in search_key or "dummy" in search_key:
             print("[Info] Forcing real MCP search connection test anyway...")
             
        manager = get_session_manager()
        session = await manager.create_session()
        print("MCP Connection session created successfully. Calling 'brave_web_search' tool...")
        
        response = await session.call_tool(
            "brave_web_search",
            arguments={"query": query, "count": 5}
        )
        print("\n[Raw Response received]:")
        print(response)
        
        # Format results using the config parser
        results = []
        if response and hasattr(response, "content") and response.content:
            for idx, content_item in enumerate(response.content, 1):
                text = getattr(content_item, "text", "")
                print(f"\nContent Block #{idx}:\n{text[:500]}...")
                
        print("\n[Parsed output results]:")
        formatted = await web_search(query)
        print(formatted)
        
    except Exception as e:
        print(f"\n[Connection/Execution Error]:\n{e}", file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(test_search())
