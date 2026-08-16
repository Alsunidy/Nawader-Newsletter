"""Wires the agents into the compiled LangGraph workflow.

START -> researcher -> writer -> editor -> (router)
                          ^                    |
                          |___ REJECTED <cap___|
                                               |APPROVED / cap reached
                                               v
                                           formatter -> promoter -> END
"""
from langgraph.graph import END, START, StateGraph

from .nodes import editor, formatter, promoter, researcher, writer
from .router import route_after_editor
from .state import NewsletterState


def build_graph():
    graph = StateGraph(NewsletterState)

    graph.add_node("researcher", researcher)
    graph.add_node("writer", writer)
    graph.add_node("editor", editor)
    graph.add_node("formatter", formatter)
    graph.add_node("promoter", promoter)

    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "editor")
    graph.add_conditional_edges(
        "editor",
        route_after_editor,
        {"writer": "writer", "formatter": "formatter"},
    )
    graph.add_edge("formatter", "promoter")
    graph.add_edge("promoter", END)

    return graph.compile()


# Compiled once at import time; the API reuses this instance for every request.
newsletter_graph = build_graph()
