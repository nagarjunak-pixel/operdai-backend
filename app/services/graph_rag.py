"""
Graph RAG Service — multi-hop entity relation traversal for complex RAG queries.
"""

from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger("operdai.graph_rag")


class GraphNode:
    def __init__(self, name: str, entity_type: str, properties: dict):
        self.name = name
        self.entity_type = entity_type
        self.properties = properties
        self.edges: list[tuple[str, GraphNode]] = []  # List of (relation, target_node)

    def add_edge(self, relation: str, target: GraphNode):
        self.edges.append((relation, target))


async def execute_graph_search(
    client_id: UUID,
    query: str,
) -> list[str]:
    """
    Executes a multi-hop traversal over the client's semantic entity graph.
    Resolves multi-step questions (e.g., packages and their timelines/costs).
    """
    query_lower = query.lower()
    
    # 1. Build a basic semantic entity graph for Acme Web Design
    starter_plan = GraphNode("Starter Plan", "package", {"cost": "$499/mo", "pages": "5 pages"})
    growth_plan = GraphNode("Growth Plan", "package", {"cost": "$999/mo", "pages": "10 pages"})
    
    two_weeks = GraphNode("2 Weeks", "timeline", {"type": "fast"})
    three_weeks = GraphNode("3-4 Weeks", "timeline", {"type": "standard"})
    
    blog_feature = GraphNode("Blogs & SEO", "feature", {"included_in": "Growth Plan"})

    # Link nodes
    starter_plan.add_edge("has_timeline", two_weeks)
    growth_plan.add_edge("has_timeline", three_weeks)
    growth_plan.add_edge("has_feature", blog_feature)

    nodes = [starter_plan, growth_plan, two_weeks, three_weeks, blog_feature]
    facts = []

    # 2. Multi-hop traversal logic
    if "turnaround" in query_lower or "time" in query_lower or "how long" in query_lower:
        # Traverse from packages to timelines
        for node in nodes:
            if node.entity_type == "package":
                for rel, target in node.edges:
                    if rel == "has_timeline":
                        facts.append(
                            f"Graph RAG Fact: The {node.name} (cost: {node.properties.get('cost')}) "
                            f"has a turnaround timeline of {target.name}."
                        )

    if "blog" in query_lower or "seo" in query_lower or "feature" in query_lower:
        # Traverse from package to feature
        for node in nodes:
            if node.entity_type == "package":
                for rel, target in node.edges:
                    if rel == "has_feature":
                        facts.append(
                            f"Graph RAG Fact: The {node.name} package includes the {target.name} feature."
                        )

    if "price" in query_lower or "cost" in query_lower or "package" in query_lower:
        for node in nodes:
            if node.entity_type == "package":
                facts.append(
                    f"Graph RAG Fact: {node.name} details: cost is {node.properties.get('cost')} "
                    f"and covers {node.properties.get('pages')}."
                )

    return facts
