import pytest
import json
from unittest.mock import patch, MagicMock
from prometheus.services.diagnostics_service import DiagnosticsService, Diagnostic

@pytest.fixture
def diagnostics_service(tmp_path):
    return DiagnosticsService(str(tmp_path))

@pytest.mark.asyncio
async def test_get_python_diagnostics_empty(diagnostics_service, tmp_path):
    test_file = tmp_path / "test.py"
    test_file.write_text("print('hello')")
    
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = MagicMock()
        mock_process.communicate.return_value = (b"[]", b"")
        mock_exec.return_value = mock_process
        
        results = await diagnostics_service.get_diagnostics("test.py")
        assert len(results) == 0

@pytest.mark.asyncio
async def test_get_python_diagnostics_errors(diagnostics_service, tmp_path):
    test_file = tmp_path / "test.py"
    test_file.write_text("print('hello')")
    
    ruff_output = json.dumps([
        {
            "code": "E402",
            "message": "Module level import not at top of file",
            "location": {"row": 10, "column": 1}
        }
    ]).encode()
    
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = MagicMock()
        mock_process.communicate.return_value = (ruff_output, b"")
        mock_exec.return_value = mock_process
        
        results = await diagnostics_service.get_diagnostics("test.py")
        assert len(results) == 1
        assert results[0].code == "E402"
        assert results[0].line == 10
        assert results[0].severity == "error"

@pytest.mark.asyncio
async def test_get_typescript_diagnostics(diagnostics_service, tmp_path):
    test_file = tmp_path / "test.ts"
    test_file.write_text("const x: number = 'hello';")
    
    tsc_output = b"test.ts(1,7): error TS2322: Type 'string' is not assignable to type 'number'."
    
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = MagicMock()
        mock_process.communicate.return_value = (tsc_output, b"")
        mock_exec.return_value = mock_process
        
        results = await diagnostics_service.get_diagnostics("test.ts")
        assert len(results) == 1
        assert results[0].code == "TS2322"
        assert results[0].line == 1
        assert "not assignable" in results[0].message
