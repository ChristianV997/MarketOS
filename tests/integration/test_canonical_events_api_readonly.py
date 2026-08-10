from api.routes.canonical_events import router

def test_api_router_exposes_get_only():
    methods = {method for route in router.routes for method in route.methods}
    assert methods == {"GET"}
