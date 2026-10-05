from senzu.stuck import Call, call_from_hook, calls_from_json, read


def test_a_desk_already_called_is_known():
    calls = [Call("terminal")] * 10 + [Call("mcp__senzu__senzu_signaler")]
    assert read(calls).already_asked


def test_no_history_is_a_quiet_session():
    assert not read([]).already_asked


def test_arguments_are_never_kept():
    call = call_from_hook("terminal", "error", args={"command": "export TOKEN=secret"})
    assert call == Call("terminal", failed=True)


def test_stored_calls_from_older_versions_still_load():
    rows = [{"tool": "terminal", "failed": True, "sig": "abc", "ro": False}, "garbage"]
    assert calls_from_json(rows) == [Call("terminal", failed=True)]
