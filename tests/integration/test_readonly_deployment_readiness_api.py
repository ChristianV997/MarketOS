from api.routes.deployment_readiness import readiness
def test_deployment_readiness_api_is_read_only():
 value=readiness(); assert value["read_only"] is True and value["mutated"] is False and value["network_calls"] is False
