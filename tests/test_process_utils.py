from browser_session_hub.process_utils import command_exists, wait_for_condition


def test_wait_for_condition_succeeds_quickly():
    state = {"count": 0}

    def predicate() -> bool:
        state["count"] += 1
        return state["count"] >= 3

    assert wait_for_condition(predicate, timeout_seconds=1.0, interval_seconds=0.01)


def test_command_exists_handles_missing_path():
    assert command_exists(None) is False
    assert command_exists("/tmp/this-path-should-not-exist") is False
