from api.routes.phase1_benchmark_matrix import benchmark_matrix

def test_benchmark_endpoint_is_read_only_and_offline():
    report = benchmark_matrix()
    assert report["read_only"] is True and report["mutated"] is False and report["network_calls"] is False
    assert report["candidate_count"] == 6
