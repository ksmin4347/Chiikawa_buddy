import importlib.util
import os
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "build_runtime", Path(__file__).resolve().parents[1] / "tools" / "build_runtime.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_build_search_path_keeps_required_paths_and_excludes_unrelated_tools(tmp_path, monkeypatch):
    python = tmp_path / "python"
    scripts = tmp_path / "scripts"
    binding = tmp_path / "PySide6"
    windows = tmp_path / "Windows"
    unrelated = tmp_path / "poppler"
    for path in (python / "DLLs", scripts, binding, windows / "System32", unrelated):
        path.mkdir(parents=True)
    monkeypatch.setenv("PATH", str(unrelated))
    runtime.configure_build_path(python, scripts, [binding], windows)
    result = os.environ["PATH"].split(os.pathsep)
    assert str(unrelated) not in result
    assert {str(binding), str(scripts), str(python / "DLLs"), str(windows / "System32")} <= set(
        result
    )


def test_windows_icu_is_not_copied_into_the_application(tmp_path):
    system32 = tmp_path / "System32"
    entries = [
        ("icuuc.dll", str(system32 / "icuuc.dll"), "BINARY"),
        ("Qt6Core.dll", "qt/Qt6Core.dll", "BINARY"),
    ]
    assert runtime.system_icu_filter(entries, system32) == entries[1:]


def test_other_tools_icu_is_rejected_instead_of_silently_shipped(tmp_path):
    entries = [("icuuc.dll", str(tmp_path / "poppler/icuuc.dll"), "BINARY")]
    with pytest.raises(ValueError, match="ICU"):
        runtime.system_icu_filter(entries, tmp_path / "System32")
