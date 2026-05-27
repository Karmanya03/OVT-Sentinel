import re
from typing import Dict, List


IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

HASH_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")

HASH_TYPES: Dict[str, str] = {
    0: "NTLM",
    1: "MS-CACHE",
    1000: "NTLM (LM compat)",
    13100: "Kerberos (TGS-REP) AES-128",
    18200: "Kerberos (AS-REP) AES-128",
    19600: "Kerberos (TGS-REP) AES-256",
    19800: "Kerberos (AS-REP) AES-256",
    5500: "NetNTLMv1",
    5600: "NetNTLMv2",
    7500: "Kerberos 5 (DB)",
}

KERB_HASH_RE = re.compile(
    r"\$krb5[^\s]+?\$[^\s]+?\$[a-fA-F0-9]{16,}"
)

NTLM_HASH_RE = re.compile(r"\b[a-fA-F0-9]{32}:[a-fA-F0-9]{32}(?::[a-fA-F0-9]{32})?\b")

USER_RE = re.compile(r"\b[A-Za-z0-9_.-]+\\[A-Za-z0-9_.-]+\b")
SAM_RE = re.compile(r"\b[A-Za-z0-9_.-]+\b")

DELEGATION_RE = re.compile(
    r"(?:unconstrained|constrained|resource-based|rbs|rcdb|whole-domain)",
    re.IGNORECASE,
)

ADCS_FINDING_RE = re.compile(
    r"(?:ESC\s*\d+|CA\s+[\w.-]+|vulnerable.*template|"
    r"ManageCA|ManageCertificates|Owner|WritePKIEnroll)",
    re.IGNORECASE,
)

SPRAY_RESULT_RE = re.compile(
    r"(?:SUCCESS|LOGON_OK|0x0|SUCCESSFUL)\s*[:：]\s*(?:\[)?\s*(\S+)",
    re.IGNORECASE,
)
SPRAY_FAIL_RE = re.compile(
    r"(?:FAIL|LOGON_FAIL|LOCKOUT|0x[89a-fA-F]\d+)",
    re.IGNORECASE,
)


def parse_output(text: str) -> Dict[str, List[str]]:
    ips = list({m.group(0) for m in IP_RE.finditer(text)})

    hashes = list({m.group(0) for m in HASH_RE.finditer(text)})

    kerb_hashes = list({m.group(0) for m in KERB_HASH_RE.finditer(text)})

    ntlm_hashes = list({m.group(0) for m in NTLM_HASH_RE.finditer(text)})

    users = list({m.group(0) for m in USER_RE.finditer(text)})

    delegations = list({m.group(0) for m in DELEGATION_RE.finditer(text)})

    adcs_findings = list({m.group(0) for m in ADCS_FINDING_RE.finditer(text)})

    spray_successes = list({m.group(0) for m in SPRAY_RESULT_RE.finditer(text)})
    spray_failures = list({m.group(0) for m in SPRAY_FAIL_RE.finditer(text)})

    result: Dict[str, List[str]] = {
        "ips": sorted(ips),
        "hashes": sorted(hashes),
        "kerb_hashes": sorted(kerb_hashes),
        "ntlm_hashes": sorted(ntlm_hashes),
        "users": sorted(users),
        "delegation_types": sorted(delegations),
        "adcs_findings": sorted(adcs_findings),
        "spray_successes": sorted(spray_successes),
        "spray_failures": sorted(spray_failures),
    }

    return result


def parse_for_ai_context(text: str) -> str:
    parsed = parse_output(text)
    parts = []
    if parsed["users"]:
        parts.append(f"Users found: {', '.join(parsed['users'][:20])}")
    if parsed["ips"]:
        parts.append(f"IPs found: {', '.join(parsed['ips'][:10])}")
    if parsed["kerb_hashes"]:
        parts.append(f"Kerberos hashes found: {len(parsed['kerb_hashes'])}")
    if parsed["ntlm_hashes"]:
        parts.append(f"NTLM hashes found: {len(parsed['ntlm_hashes'])}")
    if parsed["adcs_findings"]:
        parts.append(f"ADCS findings: {', '.join(parsed['adcs_findings'][:5])}")
    if parsed["delegation_types"]:
        parts.append(f"Delegation: {', '.join(parsed['delegation_types'][:3])}")
    if parsed["spray_successes"]:
        parts.append(f"Spray successes: {len(parsed['spray_successes'])}")
    if parsed["spray_failures"]:
        parts.append(f"Spray failures: {len(parsed['spray_failures'])}")
    return " | ".join(parts) if parts else "Standard output parsed — no security-relevant data detected"
