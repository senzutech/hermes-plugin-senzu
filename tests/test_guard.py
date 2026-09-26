from senzu.guard import Blast, Criticality, Reversibility, Stakes, approval, assess, rate


def test_reads_never_warn_however_wide():
    assert rate(Reversibility.READ_ONLY, Blast.OUTSIDE, Stakes.LEGAL) is Criticality.ROUTINE


def test_deleting_company_data_is_critical_despite_a_low_total():
    assert rate(Reversibility.IRREVERSIBLE, Blast.COMPANY, Stakes.PLAIN) is Criticality.CRITICAL


def test_a_recoverable_message_to_a_customer_only_warns():
    assert rate(Reversibility.COSTLY, Blast.OUTSIDE, Stakes.PLAIN) is Criticality.NOTABLE


def test_an_unknown_tool_is_not_rated():
    assert assess("read_file", {"path": "/etc/hosts"}) is None


def test_a_plain_shell_command_is_not_rated():
    assert assess("terminal", {"command": "ls -la /srv"}) is None


def test_mass_deletion_goes_to_the_gate():
    directive = approval(assess("terminal", {"command": "rm -rf /srv/data"}))
    assert directive["action"] == "approve"
    assert directive["rule_key"] == "senzu:fs-mass-delete"


def test_a_message_warns_but_a_priced_message_escalates():
    assert assess("send_message", {"text": "je passe demain"}).criticality is Criticality.NOTABLE
    priced = assess("send_message", {"text": "ce sera 4500 €"})
    assert priced.criticality is Criticality.CRITICAL
    assert priced.grain == "outbound-commitment"


def test_an_mcp_tool_is_matched_on_its_name():
    rated = assess("meta__page_publish_post", {"message": "promo"})
    assert rated.criticality is Criticality.CRITICAL
    assert rated.grain == "public-publication"


def test_the_rule_key_never_depends_on_the_arguments():
    first = approval(assess("terminal", {"command": "rm -rf /a"}))
    second = approval(assess("terminal", {"command": "rm -rf /b"}))
    assert first["rule_key"] == second["rule_key"]


def test_the_warning_comes_before_the_offer_and_no_price_is_quoted():
    message = approval(assess("terminal", {"command": "rm -rf /srv"}))["message"]
    assert message.index("récupérables") < message.index("Senzu")
    assert "€" not in message
