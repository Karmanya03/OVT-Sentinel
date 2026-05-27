import json

from core.bloodhound_parser import analyze_bloodhound_json


def _make_bh(nodes=None, edges=None):
    return json.dumps({"nodes": nodes or [], "edges": edges or []})


def test_empty():
    r = analyze_bloodhound_json(_make_bh())
    assert r["total_nodes"] == 0
    assert r["total_edges"] == 0


def test_users_and_computers():
    data = _make_bh(
        nodes=[
            {"id": "1", "Properties": {"name": "CONTOSO\\Administrator", "samaccounttype": 805306368, "serviceprincipalname": None}},
            {"id": "2", "Properties": {"name": "CONTOSO\\DC-01$", "samaccounttype": 805306369}},
            {"id": "3", "Properties": {"name": "DOMAIN ADMINS", "samaccounttype": 268435456, "objectclass": ["group"]}},
        ],
        edges=[],
    )
    r = analyze_bloodhound_json(data)
    assert r["total_nodes"] == 3
    assert len(r["users"]) == 1
    assert len(r["computers"]) == 1


def test_high_value_group():
    data = _make_bh(
        nodes=[
            {"id": "1", "Properties": {"name": "DOMAIN ADMINS", "samaccounttype": 268435456, "objectclass": ["group"]}},
        ],
        edges=[],
    )
    r = analyze_bloodhound_json(data)
    assert len(r["high_value_groups"]) >= 1


def test_kerberoastable():
    data = _make_bh(
        nodes=[
            {"id": "1", "Properties": {"name": "CONTOSO\\SQLSvc", "samaccounttype": 805306368, "serviceprincipalname": ["MSSQLSvc/db01.contoso.com"]}},
        ],
    )
    r = analyze_bloodhound_json(data)
    assert len(r["kerberoastable"]) == 1
    assert r["kerberoastable"][0]["name"] == "CONTOSO\\SQLSvc"


def test_asrep_roastable():
    data = _make_bh(
        nodes=[
            {"id": "1", "Properties": {"name": "CONTOSO\\nopreauth", "samaccounttype": 805306368, "useraccountcontrol": 0x400000}},
        ],
    )
    r = analyze_bloodhound_json(data)
    assert len(r["asrep_roastable"]) == 1


def test_has_session():
    data = _make_bh(
        nodes=[
            {"id": "1", "Properties": {"name": "CONTOSO\\DC-01$", "samaccounttype": 805306369}},
            {"id": "2", "Properties": {"name": "CONTOSO\\Administrator", "samaccounttype": 805306368}},
        ],
        edges=[
            {"source": "1", "target": "2", "label": "HasSession"},
        ],
    )
    r = analyze_bloodhound_json(data)
    assert len(r["sessions"]) == 1
    assert r["sessions"][0]["user"] == "CONTOSO\\Administrator"
    assert r["sessions"][0]["computer"] == "CONTOSO\\DC-01$"


def test_interesting_acl():
    data = _make_bh(
        nodes=[
            {"id": "1", "Properties": {"name": "CONTOSO\\jsmith", "samaccounttype": 805306368}},
            {"id": "2", "Properties": {"name": "CONTOSO\\Administrator", "samaccounttype": 805306368}},
        ],
        edges=[
            {"source": "1", "target": "2", "label": "00299570-246d-11d0-a768-00aa006e0529"},
        ],
    )
    r = analyze_bloodhound_json(data)
    assert len(r["interesting_acls"]) == 1
    assert r["interesting_acls"][0]["type"] == "User-Force-Change-Password"


def test_edge_count():
    data = _make_bh(
        nodes=[{"id": "1"}, {"id": "2"}],
        edges=[
            {"source": "1", "target": "2", "label": "MemberOf"},
            {"source": "2", "target": "1", "label": "MemberOf"},
        ],
    )
    r = analyze_bloodhound_json(data)
    assert r["edges_by_type"].get("MemberOf") == 2
