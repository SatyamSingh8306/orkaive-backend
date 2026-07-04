from mcp_arena.presents.postgres import PostgresMCPServer

mcp_server = PostgresMCPServer(
    connection_string="postgresql://user:password@localhost:5432/mydb",
    host="127.0.0.1",
    port=8000,
    auto_register_tools=True
)

if __name__ == "__main__":
    mcp_server.run(transport="streamable-http")