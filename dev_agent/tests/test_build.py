from langgraph.graph import END

from graph.build import route_from_supervisor


def test_route_from_supervisor_maps_end_string_to_end_constant():
    assert route_from_supervisor({"next": "END"}) == END


def test_route_from_supervisor_passes_through_worker_name():
    assert route_from_supervisor({"next": "review_agent"}) == "review_agent"


def test_route_from_supervisor_defaults_to_end_when_missing():
    assert route_from_supervisor({}) == END
