import asyncio
import ipaddress
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

log = logging.getLogger("sentinel.web_tools")


_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def validate_public_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "Only http and https URLs are allowed"
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return "Localhost URLs are not allowed"
    try:
        ip = ipaddress.ip_address(hostname)
        for net in _PRIVATE_NETS:
            if ip in net:
                return f"Private IP range ({net}) is not allowed"
    except ValueError:
        pass  # hostname, not IP — fine
    return None


async def web_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return [{"error": "duckduckgo-search package not installed. Run: pip install duckduckgo-search"}]

    loop = asyncio.get_event_loop()

    def _search() -> List[Dict[str, str]]:
        with DDGS() as ddgs:
            results = []
            for i, r in enumerate(ddgs.text(query, max_results=max_results)):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
                if len(results) >= max_results:
                    break
            return results

    try:
        results = await loop.run_in_executor(None, _search)
        return results if results else [{"info": f"No results found for: {query}"}]
    except Exception as e:
        return [{"error": f"Search failed: {e}"}]


async def web_fetch(url: str, max_chars: int = 5000) -> str:
    err = validate_public_url(url)
    if err:
        return err

    try:
        import httpx
        from bs4 import BeautifulSoup
    except ImportError:
        return "httpx/beautifulsoup4 not installed. Run: pip install httpx beautifulsoup4"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OVT-Sentinel/1.0",
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text" not in content_type and "html" not in content_type:
                return f"URL returned non-text content type: {content_type}"

            soup = BeautifulSoup(response.text, "lxml")

            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)
            lines = [line for line in text.splitlines() if line.strip()]
            text = "\n".join(lines)

            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n...[truncated]"

            return text if text else "Page appears to be empty or requires JavaScript."
    except httpx.HTTPStatusError as e:
        return f"HTTP error {e.response.status_code} fetching {url}"
    except Exception as e:
        return f"Error fetching {url}: {e}"


CVE_DB: Dict[str, List[Dict[str, str]]] = {
    "ws2019": [
        {"cve": "CVE-2024-38077", "desc": "RDL (Remote Desktop Licensing) RCE — affects WS 2019 with RDL role; CVSS 9.8"},
        {"cve": "CVE-2024-26248", "desc": "ADCS ESC-based elevation — PAC bypass in Kerberos KDC; patch July 2024"},
        {"cve": "CVE-2023-32019", "desc": "Windows Kernel info disclosure — used in BYOVD chains"},
        {"cve": "CVE-2023-21768", "desc": "AFD.sys LPE (Pipes) — used by most C2 frameworks 2023-2024"},
        {"cve": "CVE-2022-26923", "desc": "ADCS ESC13 — certificate-based authentication bypass for machine accounts"},
        {"cve": "CVE-2021-42287", "desc": "sAMAccountName spoofing (noPac) — DC compromise from standard user"},
        {"cve": "CVE-2021-42278", "desc": "sAMAccountName spoofing (noPac) — paired with 42287"},
        {"cve": "CVE-2021-1678", "desc": "MS-RPRN printer bug — coerce auth from any DC"},
        {"cve": "CVE-2020-1472", "desc": "Zerologon — unauthenticated DC compromise (patched but legacy DCs still vulnerable)"},
        {"cve": "CVE-2020-17049", "desc": "Kerberos delegation — KUDU (Kerberos Unconstrained Delegation UPDOWN)"},
    ],
    "ws2022": [
        {"cve": "CVE-2024-38124", "desc": "Kerberos KDC RCE — patch Aug 2024; pre-auth crash leading to RCE; CVSS 8.8"},
        {"cve": "CVE-2024-38077", "desc": "RDL RCE — also affects WS 2022 with RDL role"},
        {"cve": "CVE-2024-26248", "desc": "Kerberos PAC elevation — affects all Server 2022 as KDC"},
        {"cve": "CVE-2023-36696", "desc": "Windows Cloud Filter LPE — used in post-exploitation"},
        {"cve": "CVE-2023-21768", "desc": "AFD.sys LPE — same as 2019, still unpatched in many orgs"},
        {"cve": "CVE-2022-26923", "desc": "ADCS ESC13 — works on all supported Windows Server versions"},
        {"cve": "CVE-2022-37967", "desc": "Kerberos PAC — escalation via Kerberos validation bypass (CVSS 8.1)"},
        {"cve": "CVE-2022-34691", "desc": "Active Directory info disclosure — LDAP-based user enumeration"},
        {"cve": "CVE-2022-33679", "desc": "Windows Kerberos RCE — key distribution center vulnerability"},
        {"cve": "CVE-2021-42287/78", "desc": "noPac — sAMAccountName spoofing (patched but still exploitable in unpatched orgs)"},
    ],
    "ws2025": [
        {"cve": "CVE-2024-49127", "desc": "Windows LDAP RCE — critical CVSS 9.0; unauthenticated LDAP crash in lsass"},
        {"cve": "CVE-2024-49112", "desc": "Windows LDAP RCE — pre-auth LDAP query crash; CVSS 9.8; affects all LDAP servers"},
        {"cve": "CVE-2024-38124", "desc": "Kerberos KDC — same as WS 2022; WS 2025 also affected if unpatched"},
        {"cve": "CVE-2024-26248", "desc": "Kerberos PAC — applies to WS 2025 as KDC if not on latest patch"},
        {"cve": "CVE-2024-21319", "desc": "Microsoft Identity Server LPE — affects AD FS in WS 2025 environments"},
        {"cve": "CVE-2024-0056", "desc": "SQL Server + AD — Kerberos delegation bypass in data providers"},
    ],
}


async def search_vulnerabilities(product: str) -> str:
    product_lower = product.lower().replace(" ", "").replace("-", "").replace("_", "")
    key_map = {
        "ws2019": ["ws2019", "server2019", "windows2019", "win2019", "2019"],
        "ws2022": ["ws2022", "server2022", "windows2022", "win2022", "2022"],
        "ws2025": ["ws2025", "server2025", "windows2025", "win2025", "2025"],
    }

    matched_key = None
    for k, aliases in key_map.items():
        if any(a in product_lower for a in aliases):
            matched_key = k
            break

    if matched_key and matched_key in CVE_DB:
        entries = CVE_DB[matched_key]
        lines = [f"Known CVEs for {matched_key}:", ""]
        for e in entries:
            lines.append(f"  {e['cve']}: {e['desc']}")
        lines.append("")
        lines.append("Note: Always verify with web_search() for the latest patches and exploits.")
        return "\n".join(lines)

    result = await web_search(f"{product} CVE vulnerability 2024 2025")
    if result and "error" not in result[0]:
        lines = [f"Web search results for {product} vulnerabilities:", ""]
        for r in result[:5]:
            lines.append(f"  {r.get('title', '?')}")
            lines.append(f"  {r.get('snippet', '')}")
            lines.append(f"  URL: {r.get('url', '')}")
            lines.append("")
        return "\n".join(lines)

    return f"No vulnerability data found for {product}. Try web_search('{product} CVE')."
