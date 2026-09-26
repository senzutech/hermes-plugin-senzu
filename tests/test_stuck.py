from senzu.stuck import Call, read


def test_a_working_session_is_left_alone():
    # The real capture had 43 tool calls over several tools; spread work is honest work.
    tools = ["terminal", "read_file", "search_files", "process_manage"]
    calls = [Call("terminal", failed=True)] + [Call(tools[i % 4]) for i in range(42)]
    reading = read(calls)
    assert reading.failures == 0, "the failure left the window"
    assert not reading.deserves_an_offer


def test_two_recent_failures_ending_on_one_speak():
    calls = [Call("terminal"), Call("terminal", True), Call("terminal"), Call("terminal", True)]
    reading = read(calls)
    assert reading.failures == 2 and reading.just_failed
    assert reading.deserves_an_offer


def test_the_owner_saying_it_is_still_broken_does_not_clear_the_repetition():
    # Only tool calls are recorded: the owner's « ça marche toujours pas » resets nothing.
    reading = read([Call("terminal")] * 15)
    assert reading.repeats == 15
    assert reading.deserves_an_offer


def test_hammering_needs_the_tool_to_dominate():
    calls = [Call("terminal")] * 7 + [Call(f"tool{i}") for i in range(20)]
    assert not read(calls).deserves_an_offer, "7 out of 27 is honest work"


def test_six_dominant_calls_are_enough():
    assert read([Call("terminal")] * 6).deserves_an_offer


def test_a_desk_already_called_is_never_nagged():
    calls = [Call("terminal")] * 10 + [Call("mcp__senzu__senzu_signaler")]
    assert not read(calls).deserves_an_offer


def test_no_history_is_a_quiet_session():
    assert not read([]).deserves_an_offer
