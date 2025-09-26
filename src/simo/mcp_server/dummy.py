"""
Dummy MCP server to run mcp inspector
mcp dev simo/mcp_server/dummy.py
"""
import uvicorn
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Dummy MCP")

def create_app():
    return mcp.streamable_http_app()


if __name__ == "__main__":
    uvicorn.run(
        "simo.mcp_server.run:create_app",
        host="0.0.0.0",
        port=3333,
        factory=True,
        log_config=None
    )

