"""Essential checks and optional staging for the complete original publication."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent


def inspect_release(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "release_manifest.json").read_text(encoding="utf-8"))
    files = manifest["allowlist"]
    assert len(files) == len(set(files))
    denied = {".git", ".pbi", "__pycache__", ".venv", "build", "outputs", "output"}
    patterns = [r"gh[pousr]_[A-Za-z0-9]{30,}", r"AKIA[0-9A-Z]{16}",
                r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                r"(?i)[A-Z]:[\\/]Users[\\/][^\s]+"]
    hashes = {}
    for relative in files:
        path = root / relative
        assert not Path(relative).is_absolute() and ".." not in Path(relative).parts
        assert not set(Path(relative).parts) & denied, relative
        assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root), relative
        assert path.suffix.lower() not in {".pyc", ".pbix", ".abf", ".sqlite", ".zip", ".env", ".pem", ".pfx"}, relative
        assert path.stat().st_size < 100 * 1024**2, f"GitHub file limit: {relative}"
        content = path.read_bytes()
        hashes[relative] = hashlib.sha256(content).hexdigest()
        if path.suffix.lower() != ".png":
            text = content.decode("utf-8-sig")
            assert not any(re.search(pattern, text) for pattern in patterns), f"Secret/path pattern: {relative}"
        if path.suffix in {".json", ".pbip", ".pbir", ".pbism"} or path.name == ".platform":
            json.loads(content)
    for relative, expected in manifest["immutable_sha256"].items():
        assert hashes[relative] == expected, f"Original asset changed: {relative}"
    prefix = "Enterprise Retail Inventory Intelligence"
    model = root / "powerbi" / (prefix + ".SemanticModel") / "definition"
    report = root / "powerbi" / (prefix + ".Report") / "definition"
    assert (root / "powerbi" / (prefix + ".pbip")).is_file()
    assert len(list((report / "pages").glob("*/page.json"))) == 8
    assert len(list((report / "pages").glob("*/visuals/*/visual.json"))) == 112
    tables = list((model / "tables").glob("*.tmdl"))
    assert sum(len(re.findall(r"^\s+measure ", p.read_text(encoding="utf-8-sig"), re.M)) for p in tables) == 51
    assert len(re.findall(r"^relationship ", (model / "relationships.tmdl").read_text(encoding="utf-8-sig"), re.M)) == 18
    assert len(list((root / "DASHBORD_SCREEN_SHOTS").glob("*.png"))) == 8
    imports = []
    for table in tables:
        imports += re.findall(r'File\.Contents\(DataRoot & "([^"\n]+)"\)', table.read_text(encoding="utf-8-sig"))
    assert len(imports) == 9
    assert all((root / "data" / name.lstrip("/")).is_file() for name in imports)
    assert "expression DataRoot =" in (model / "expressions.tmdl").read_text(encoding="utf-8-sig")
    assert "ref expression DataRoot" in (model / "model.tmdl").read_text(encoding="utf-8-sig")
    return {"status": "COMPLETE_PUBLICATION_CHECK_PASS", "files": len(files), "sha256": hashes,
            "pages": 8, "visuals": 112, "measures": 51, "relationships": 18, "screenshots": 8,
            "historical_csv_imports": 9, "raw_license": "CC BY 4.0; publisher SHA-256 verified",
            "runtime": "POWER_BI_RUNTIME_NOT_VERIFIED"}


def stage(root, destination):
    root = Path(root).resolve()
    destination = Path(destination).resolve()
    assert destination.is_relative_to(root / "build") and destination != root / "build" and not destination.exists()
    result = inspect_release(root)
    for relative, digest in result["sha256"].items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_release(ROOT) if args.check else stage(ROOT, args.output_dir)
    except (AssertionError, OSError, ValueError) as error:
        parser.exit(1, f"Publication check failed: {error}\n")
    print(json.dumps({k: v for k, v in result.items() if k != "sha256"}, indent=2))


if __name__ == "__main__":
    main()
