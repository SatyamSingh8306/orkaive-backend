class BaseToolExecutor:
    async def execute(self, tool_definition, tool_config, context):
        raise NotImplementedError
