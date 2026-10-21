import pytest
from backend.core.quality_gate.engine import QualityGateEngine, GateResult
from backend.core.quality_gate.checks import BaseCheck, CheckResult, CheckStatus, CheckSeverity


class AlwaysPassCheck(BaseCheck):
    name = "always_pass"
    severity = CheckSeverity.ERROR
    blocking = False

    async def run(self, state, config):
        return self.passed("All good")


class AlwaysFailCheck(BaseCheck):
    name = "always_fail"
    severity = CheckSeverity.ERROR
    blocking = True

    async def run(self, state, config):
        return self.failed("Always fails", {"reason": "test"})


class AlwaysWarnCheck(BaseCheck):
    name = "always_warn"
    severity = CheckSeverity.WARNING
    blocking = False

    async def run(self, state, config):
        return self.warning("Just a warning")


@pytest.mark.asyncio
async def test_engine_no_checks():
    engine = QualityGateEngine()
    result = await engine.run({}, {})
    assert result.status == "skipped"
    assert result.checks_run == 0


@pytest.mark.asyncio
async def test_engine_all_pass():
    engine = QualityGateEngine()
    engine.register(AlwaysPassCheck())
    result = await engine.run({}, {})
    assert result.status == "passed"
    assert result.checks_passed == 1
    assert result.checks_failed == 0
    assert not result.blocking


@pytest.mark.asyncio
async def test_engine_with_failure():
    engine = QualityGateEngine()
    engine.register(AlwaysFailCheck())
    result = await engine.run({}, {})
    assert result.status == "failed"
    assert result.checks_failed == 1
    assert result.blocking


@pytest.mark.asyncio
async def test_engine_enabled_checks_filter():
    engine = QualityGateEngine()
    engine.register(AlwaysPassCheck())
    engine.register(AlwaysFailCheck())
    result = await engine.run({}, {}, enabled_checks=["always_pass"])
    assert result.status == "passed"
    assert result.checks_run == 1


@pytest.mark.asyncio
async def test_engine_check_exception_handled():
    class BrokenCheck(BaseCheck):
        name = "broken"
        severity = CheckSeverity.ERROR
        blocking = False
        async def run(self, state, config):
            raise RuntimeError("boom")

    engine = QualityGateEngine()
    engine.register(BrokenCheck())
    result = await engine.run({}, {})
    assert result.status == "failed"
    assert result.checks_failed == 1


@pytest.mark.asyncio
async def test_check_result_to_dict():
    check = AlwaysPassCheck()
    result = await check.run({}, {})
    d = result.to_dict()
    assert d["check_name"] == "always_pass"
    assert d["status"] == "passed"
    assert d["blocking"] is False


@pytest.mark.asyncio
async def test_gate_result_to_details():
    engine = QualityGateEngine()
    engine.register(AlwaysPassCheck())
    engine.register(AlwaysWarnCheck())
    gate = await engine.run({}, {})
    details = gate.to_details()
    assert len(details) == 2
    names = {d["check_name"] for d in details}
    assert "always_pass" in names
    assert "always_warn" in names
