from fastmcp import FastMCP
from .auth import DjangoTokenVerifier

mcp = FastMCP(name="SIMO_MCP", auth=DjangoTokenVerifier())