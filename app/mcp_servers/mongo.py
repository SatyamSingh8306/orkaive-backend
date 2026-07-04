from mcp_arena.presents.mongo import MongoDBMCPServer

mcp_server = MongoDBMCPServer(host="127.0.0.1",port=8000,auto_register_tools=True)

if __name__ == "__main__":
    mcp_server.run(transport="streamable-http")