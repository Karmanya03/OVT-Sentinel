import json
from typing import Any, Dict, List


HIGH_VALUE_GROUPS = {
    "DOMAIN_ADMINS": "S-1-5-21-*-512",
    "ENTERPRISE_ADMINS": "S-1-5-21-*-519",
    "SCHEMA_ADMINS": "S-1-5-21-*-518",
    "ADMINISTRATORS": "S-1-5-32-544",
    "DOMAIN_CONTROLLERS": "S-1-5-21-*-516",
    "ACCOUNT_OPERATORS": "S-1-5-32-548",
    "BACKUP_OPERATORS": "S-1-5-32-551",
    "SERVER_OPERATORS": "S-1-5-32-549",
    "PRINT_OPERATORS": "S-1-5-32-550",
    "EXCHANGE_WINDOWS_PERMISSIONS": "S-1-5-21-*-*-717",
    "HYPER_V_ADMINS": "S-1-5-32-578",
    "DCSYNC": "DS-Replication-Get-Changes",
}

INTERESTING_ACE_GUIDS = {
    "00299570-246d-11d0-a768-00aa006e0529": "User-Force-Change-Password",
    "ab721a53-1e2f-11d0-9819-00aa0040529b": "DS-Replication-Get-Changes",
    "89e95b76-444d-4c62-991a-0facbeda640c": "DS-Replication-Get-Changes-All",
    "1131f6aa-9c07-11d1-f79f-00c04fc2dcd2": "DS-Replication-Get-Changes-In-Filtered-Set",
    "5805bc62-bdc9-4428-a5e2-856a0f4c185e": "Write-Property",
    "bf967a7f-0de6-11d0-a285-00aa003049e2": "Write-Dacl",
    "00000000-0000-0000-0000-000000000000": "GenericAll",
}


def _get_node_props(obj: Dict[str, Any]) -> Dict[str, Any]:
    props = obj.get("Properties", obj)
    return props


def _get_node_type(props: Dict[str, Any]) -> str:
    if props.get("domain"):
        return "domain"
    st = props.get("samaccounttype")
    if st in (805306369, 805306370):
        return "computer"
    if st == 805306368:
        return "user"
    if st == 268435456 or "group" in (props.get("objectclass") or []):
        return "group"
    return "computer" if st else "unknown"


def analyze_bloodhound_json(data: str) -> Dict[str, Any]:
    obj = json.loads(data)
    nodes: List[Dict] = obj.get("nodes", [])
    edges: List[Dict] = obj.get("edges", [])

    result: Dict[str, Any] = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "users": [],
        "computers": [],
        "domains": [],
        "high_value_groups": [],
        "kerberoastable": [],
        "asrep_roastable": [],
        "sessions": [],
        "edges_by_type": {},
        "interesting_acls": [],
        "ca_servers": [],
        "cert_templates": [],
    }

    node_map: Dict[str, Dict] = {}
    for n in nodes:
        props = _get_node_props(n)
        sid = str(props.get("objectsid", props.get("sid", n.get("id", ""))))
        node_map[sid] = n

        ntype = _get_node_type(props)
        name = str(props.get("name", sid))

        entry = {"name": name, "sid": sid}
        if ntype == "user":
            if props.get("serviceprincipalname"):
                entry["spns"] = list(props.get("serviceprincipalname", []))
                result["kerberoastable"].append(entry)
            if props.get("sidhistory"):
                entry["sid_history"] = list(props.get("sidhistory", []))
            if props.get("useraccountcontrol", 0) & 0x400000:
                entry["dont_require_preauth"] = True
                result["asrep_roastable"].append(entry)
            result["users"].append(entry)
        elif ntype == "computer":
            result["computers"].append(entry)
            operating_system = props.get("operatingsystem", "")
            if "CA" in operating_system or "cert" in operating_system.lower():
                result["ca_servers"].append(entry)
        elif ntype == "domain":
            result["domains"].append(entry)
        elif ntype == "group":
            name_normalized = name.upper().replace(" ", "_").replace("-", "_")
            for hvg_label in HIGH_VALUE_GROUPS:
                if hvg_label in name_normalized:
                    result["high_value_groups"].append({**entry, "label": hvg_label})
                    break

    for e in edges:
        edge_type = str(e.get("label", e.get("type", "unknown")))
        result["edges_by_type"][edge_type] = result["edges_by_type"].get(edge_type, 0) + 1

        if edge_type == "HasSession":
            src = node_map.get(str(e.get("source", "")))
            dst = node_map.get(str(e.get("target", "")))
            if src and dst:
                src_props = _get_node_props(src)
                dst_props = _get_node_props(dst)
                result["sessions"].append({
                    "user": str(dst_props.get("name", "")),
                    "computer": str(src_props.get("name", "")),
                })

        if edge_type in INTERESTING_ACE_GUIDS:
            src = node_map.get(str(e.get("source", "")))
            dst = node_map.get(str(e.get("target", "")))
            acl_name = INTERESTING_ACE_GUIDS[edge_type]
            result["interesting_acls"].append({
                "type": acl_name,
                "grantee": str(_get_node_props(src).get("name", "?")) if src else "?",
                "target": str(_get_node_props(dst).get("name", "?")) if dst else "?",
            })
        elif edge_type == "MemberOf":
            src = node_map.get(str(e.get("source", "")))
            dst = node_map.get(str(e.get("target", "")))

    return result
