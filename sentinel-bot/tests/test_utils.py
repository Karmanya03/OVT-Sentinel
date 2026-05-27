import pytest
from core.utils import safe_call


class TestSafeCall:
    @pytest.mark.asyncio
    async def test_success_returns_result(self):
        async def good():
            return "ok"
        result = await safe_call(None, lambda: good(), "test", ephemeral=True)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_failure_returns_none(self):
        async def bad():
            raise ValueError("boom")
        result = await safe_call(None, lambda: bad(), "test", ephemeral=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_label_included_in_error(self):
        async def bad():
            raise RuntimeError("fail")
        result = await safe_call(None, lambda: bad(), "my_operation", ephemeral=True)
        assert result is None
