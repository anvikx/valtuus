"""MCP door for outside agents."""

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

# DNS rebinding protection guards servers on localhost. This one is public behind
# Caddy, and the agent key check is its guard.
_TRANSPORT_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)


def create_mcp_server() -> MCPServer:
    server = MCPServer(name="valtuus")

    @server.tool()
    def ping() -> str:
        """Check that the gateway answers."""
        return "pong"

    return server


def build_mcp_app(server: MCPServer) -> Starlette:
    # Stateless JSON: one worker, no session survives a deploy restart anyway.
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=_TRANSPORT_SECURITY,
    )
