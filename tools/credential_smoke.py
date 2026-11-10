"""Test an isolated canary credential; never touch a real API key or make a request."""

# ruff: noqa: E402 -- Run from the source checkout.
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from desktop_buddy.security.credentials import WindowsCredentialVault


def main() -> int:
    run_id = uuid4().hex
    vault = WindowsCredentialVault(f"DesktopBuddy/QA/{run_id}/OpenAI/APIKey")
    result = {"target": vault.target, "network_requests": 0}
    owned = False
    try:
        if vault.exists():
            raise RuntimeError("QA target already exists; left untouched")
        owned = True
        canary = "not-a-real-key-" + uuid4().hex
        vault.write(canary)
        result["exists_after_write"] = vault.exists()
        result["read_matches"] = vault.read() == canary
        vault.write(canary + "-replacement")
        result["replacement_matches"] = vault.read() == canary + "-replacement"
    except Exception as error:
        result["error_type"] = type(error).__name__
        result["error_code"] = getattr(error, "winerror", None)
    finally:
        if owned:
            try:
                vault.delete()
                vault.delete()
                result["removed"] = not vault.exists() and vault.read() is None
            except Exception as error:
                result["cleanup_error_type"] = type(error).__name__
        else:
            result["removed"] = False
    passed = (
        not result.get("error_type")
        and not result.get("cleanup_error_type")
        and all(
            result.get(name) is True
            for name in ("exists_after_write", "read_matches", "replacement_matches", "removed")
        )
    )
    result["passed"] = passed
    output = ROOT / ".qa" / f"credential-native-{run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
