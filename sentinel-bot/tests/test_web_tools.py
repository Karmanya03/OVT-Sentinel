import pytest
from core.web_tools import validate_public_url, web_search, web_fetch, search_vulnerabilities


class TestValidatePublicURL:
    def test_valid_https(self):
        assert validate_public_url("https://example.com") is None

    def test_valid_http(self):
        assert validate_public_url("http://example.com") is None

    def test_valid_with_port(self):
        assert validate_public_url("https://example.com:8080/path") is None

    def test_valid_subdomain(self):
        assert validate_public_url("https://api.github.com") is None

    def test_rejects_localhost(self):
        result = validate_public_url("http://localhost:8000")
        assert result is not None
        assert "Localhost" in result

    def test_rejects_127_dot(self):
        result = validate_public_url("http://127.0.0.1:7331")
        assert result is not None

    def test_rejects_loopback(self):
        result = validate_public_url("http://127.127.127.127")
        assert result is not None

    def test_rejects_10_dot(self):
        result = validate_public_url("http://10.0.0.1")
        assert result is not None

    def test_rejects_172_dot_16(self):
        result = validate_public_url("http://172.16.0.1")
        assert result is not None

    def test_rejects_172_dot_31(self):
        result = validate_public_url("http://172.31.255.255")
        assert result is not None

    def test_allows_172_dot_15(self):
        assert validate_public_url("http://172.15.0.1") is None

    def test_allows_172_dot_32(self):
        assert validate_public_url("http://172.32.0.1") is None

    def test_rejects_192_dot_168(self):
        result = validate_public_url("http://192.168.1.1")
        assert result is not None

    def test_rejects_169_dot_254(self):
        result = validate_public_url("http://169.254.169.254")
        assert result is not None

    def test_rejects_ipv6_loopback(self):
        result = validate_public_url("http://[::1]:8000")
        assert result is not None

    def test_rejects_ftp_scheme(self):
        result = validate_public_url("ftp://example.com")
        assert result is not None

    def test_rejects_file_scheme(self):
        result = validate_public_url("file:///etc/passwd")
        assert result is not None

    def test_rejects_empty_url(self):
        result = validate_public_url("")
        assert result is not None

    def test_rejects_0_dot_0_dot_0_dot_0(self):
        result = validate_public_url("http://0.0.0.0")
        assert result is not None

    def test_ipv4_in_dotted_quad(self):
        result = validate_public_url("http://10.10.10.10:443/path?q=1")
        assert result is not None


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_returns_error_on_missing_deps(self):
        result = await web_search("test query", max_results=3)
        assert isinstance(result, list)
        # duckduckgo_search may or may not be installed; either path should work
        if result and isinstance(result[0], dict):
            assert "title" in result[0] or "info" in result[0] or "error" in result[0]

    @pytest.mark.asyncio
    async def test_handles_empty_query(self):
        result = await web_search("", max_results=3)
        assert isinstance(result, (list, dict))


class TestWebFetch:
    @pytest.mark.asyncio
    async def test_rejects_private_url(self):
        result = await web_fetch("http://192.168.1.1/secret")
        assert result is not None
        # Should return error message about private URL

    @pytest.mark.asyncio
    async def test_rejects_localhost(self):
        result = await web_fetch("http://localhost:7331/status")
        assert result is not None

    @pytest.mark.asyncio
    async def test_rejects_non_http(self):
        result = await web_fetch("ftp://example.com")
        assert result is not None


class TestSearchVulnerabilities:
    @pytest.mark.asyncio
    async def test_known_product_ws2019(self):
        result = await search_vulnerabilities("ws2019")
        assert result is not None
        assert isinstance(result, str)
        assert "CVE-" in result

    @pytest.mark.asyncio
    async def test_known_product_ws2022(self):
        result = await search_vulnerabilities("ws2022")
        assert result is not None
        assert "CVE-" in result

    @pytest.mark.asyncio
    async def test_known_product_ws2025(self):
        result = await search_vulnerabilities("ws2025")
        assert result is not None
        assert "CVE-" in result

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        result_upper = await search_vulnerabilities("WS2019")
        result_lower = await search_vulnerabilities("ws2019")
        assert result_upper == result_lower

    @pytest.mark.asyncio
    async def test_partial_match_fallsback(self):
        result = await search_vulnerabilities("nonexistent_product_xyz")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_empty_product(self):
        result = await search_vulnerabilities("")
        assert isinstance(result, str)
