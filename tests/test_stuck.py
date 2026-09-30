from senzu.stuck import Call, call_from_hook, is_read_only, read


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


SAME = Call("terminal", signature="npm-i")


def test_the_owner_saying_it_is_still_broken_does_not_clear_the_repetition():
    # Only tool calls are recorded: the owner's « ça marche toujours pas » resets nothing.
    reading = read([SAME] * 15)
    assert reading.repeats == 15
    assert reading.deserves_an_offer


def test_hammering_needs_the_tool_to_dominate():
    calls = [SAME] * 7 + [Call(f"tool{i}", signature=str(i)) for i in range(20)]
    assert not read(calls).deserves_an_offer, "7 out of 27 is honest work"


def test_six_dominant_calls_are_enough():
    assert read([SAME] * 6).deserves_an_offer


def test_a_desk_already_called_is_never_nagged():
    calls = [SAME] * 10 + [Call("mcp__senzu__senzu_signaler")]
    assert not read(calls).deserves_an_offer


def test_no_history_is_a_quiet_session():
    assert not read([]).deserves_an_offer


# --- Production, 30/09: offers made to scheduled jobs that were working --------------------------


def _calls(*pairs):
    return [call_from_hook(tool, "ok", args) for tool, args in pairs]


def test_research_is_not_a_loop():
    """Eight web searches on different questions, in three batches, then an extract."""
    searches = [("web_search", {"query": f"fiche CEE scooter {i}"}) for i in range(8)]
    calls = _calls(*searches, ("web_extract", {"urls": ["https://example.gouv.fr"]}))
    assert not read(calls).deserves_an_offer


def test_a_varied_brief_is_not_a_loop():
    """Fifteen varied calls that succeed, the morning brief."""
    tools = ["web_search", "terminal", "read_file", "web_extract", "execute_code"]
    calls = _calls(*[(tools[i % 5], {"n": i}) for i in range(15)])
    assert not read(calls).deserves_an_offer


def test_different_commands_are_not_the_same_call():
    calls = _calls(*[("terminal", {"command": f"step {i}"}) for i in range(12)])
    assert read(calls).repeats == 1
    assert not read(calls).deserves_an_offer


def test_the_same_command_again_and_again_is():
    calls = _calls(*[("terminal", {"command": "npm i  clickup"})] * 3) + _calls(
        *[("terminal", {"command": "npm i clickup"})] * 3
    )
    assert read(calls).repeats == 6, "spacing aside, the same command"
    assert read(calls).deserves_an_offer


def test_an_identical_command_failing_speaks():
    calls = [call_from_hook("terminal", "error", {"command": "npm i clickup"})] * 4
    assert read(calls).deserves_an_offer


def test_reading_tools_never_count_as_repetition():
    calls = _calls(*[("web_search", {"query": "même question"})] * 10)
    assert read(calls).repeats == 0
    assert is_read_only("mcp__odoo__search_read")
    assert is_read_only("mcp__erp__list_invoices")
    assert is_read_only("sage_query", extra=["sage_query"])
    assert not is_read_only("terminal")


def test_arguments_are_never_kept():
    call = call_from_hook("terminal", "ok", {"command": "export TOKEN=secret"})
    assert "secret" not in repr(call)
