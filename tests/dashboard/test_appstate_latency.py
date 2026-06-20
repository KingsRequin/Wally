from bot.dashboard.state import AppState


def _bare_state():
    s = AppState.__new__(AppState)  # bypass required dataclass fields
    s._init_latency()
    return s


def test_avg_none_when_empty():
    assert _bare_state().avg_response_ms is None


def test_avg_is_mean_of_samples():
    s = _bare_state()
    s.record_response_time(100.0)
    s.record_response_time(300.0)
    assert s.avg_response_ms == 200.0


def test_ring_buffer_bounded():
    s = _bare_state()
    for i in range(100):
        s.record_response_time(float(i))
    assert s.avg_response_ms == round(sum(range(50, 100)) / 50, 1)
