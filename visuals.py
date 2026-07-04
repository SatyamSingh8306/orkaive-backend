
from app.orchestrator.graph import create_orchestrator
orchestor = create_orchestrator()
compiled_graph = orchestor._build_graph().compile()
png_bytes = compiled_graph.get_graph().draw_mermaid_png()
with open("langgraph.png", "wb") as f:
    f.write(png_bytes)

