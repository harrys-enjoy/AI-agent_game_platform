from langgraph.graph import END, StateGraph

from graph.ci_trigger import ci_trigger_node
from graph.deploy_trigger import deploy_trigger_node
from graph.fetch import endpoint_agent, fetch_node
from graph.state import State
from graph.supervisor import supervisor_node
from graph.workers import branch_agent, ci_agent, general_qa_agent, review_agent

WORKER_NODES = [
    "fetch",
    "review_agent",
    "endpoint_agent",
    "branch_agent",
    "ci_agent",
    "general_qa",
    "ci_trigger",
    "deploy_trigger",
]


def route_from_supervisor(state: dict) -> str:
    """supervisor의 라우팅 결정을 그대로 읽는다. 부수효과 없는 순수 함수."""
    next_node = state.get("next", "END")
    return END if next_node == "END" else next_node


def build_graph():
    graph = StateGraph(State)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("fetch", fetch_node)
    graph.add_node("review_agent", review_agent)
    graph.add_node("endpoint_agent", endpoint_agent)
    graph.add_node("branch_agent", branch_agent)
    graph.add_node("ci_agent", ci_agent)
    graph.add_node("general_qa", general_qa_agent)
    graph.add_node("ci_trigger", ci_trigger_node)
    graph.add_node("deploy_trigger", deploy_trigger_node)

    graph.set_entry_point("supervisor")

    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {node: node for node in WORKER_NODES} | {END: END},
    )

    for worker in WORKER_NODES:
        graph.add_edge(worker, "supervisor")

    return graph.compile()
