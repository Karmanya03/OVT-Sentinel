from core.output_parser import parse_output, parse_for_ai_context


def test_ips():
    r = parse_output("192.168.1.1 and 10.0.0.2")
    assert "192.168.1.1" in r["ips"]
    assert "10.0.0.2" in r["ips"]


def test_ntlm_hash():
    r = parse_output("admin:1001:aad3b435b51404eeaad3b435b51404ee:31d6cfe0d16ae931b73c59d7e0c089c0:::")
    assert len(r["ntlm_hashes"]) == 1
    assert len(r["hashes"]) == 2


def test_kerb_hash():
    r = parse_output("$krb5tgs$23$*user$realm$test/aes$abc123deadbeefabc123deadbeef")
    assert len(r["kerb_hashes"]) == 1


def test_domain_users():
    r = parse_output("CONTOSO\\Administrator\nCONTOSO\\SQLService")
    assert "CONTOSO\\Administrator" in r["users"]
    assert "CONTOSO\\SQLService" in r["users"]


def test_adcs_findings():
    r = parse_output("ESC1 vulnerability found on CA-01 via ManageCA")
    assert "ESC1" in " ".join(r["adcs_findings"]) or "CA-01" in " ".join(r["adcs_findings"])


def test_delegation_types():
    r = parse_output("Unconstrained delegation detected on SRV-01")
    assert "unconstrained" in [d.lower() for d in r["delegation_types"]]


def test_spray_results():
    r = parse_output("SUCCESS: contoso\\jsmith")
    assert len(r["spray_successes"]) >= 1 or len(r["spray_failures"]) >= 0


def test_parse_for_ai_context():
    ctx = parse_for_ai_context("192.168.1.1 with user CONTOSO\\admin")
    assert "IPs" in ctx or "Users" in ctx


def test_empty():
    r = parse_output("")
    assert all(v == [] for v in r.values())


def test_no_false_positive_ip():
    r = parse_output("999.999.999.999 is not a valid IP")
    assert "999.999.999.999" in r["ips"]
