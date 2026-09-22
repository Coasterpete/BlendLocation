"""Locate Blender 5.2, build the extension ZIP, and run isolated smoke tests."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def find_blender(override=None):
    candidates = []
    if override or os.environ.get("BLENDER_EXECUTABLE"):
        candidates.append(Path(override or os.environ["BLENDER_EXECUTABLE"]))
    else:
        located = shutil.which("blender")
        if located:
            candidates.append(Path(located))
        if sys.platform == "win32":
            for base in (Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Blender Foundation",
                         Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam" / "steamapps" / "common" / "Blender"):
                candidates.extend(base.glob("Blender 5.2*/blender.exe"))
                candidates.append(base / "blender.exe")
        elif sys.platform == "darwin":
            candidates.append(Path("/Applications/Blender.app/Contents/MacOS/Blender"))
    for candidate in candidates:
        if candidate.is_file():
            result = subprocess.run([str(candidate), "--version"], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.startswith("Blender 5.2."):
                return candidate.resolve()
    raise SystemExit("Blender 5.2.x not found. Set BLENDER_EXECUTABLE or pass --blender PATH.")


def run(args, env=None):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=ROOT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "test"))
    parser.add_argument("--blender", help="Path to Blender 5.2 executable")
    args = parser.parse_args()
    blender = find_blender(args.blender)
    output = ROOT / "dist" / "blendlocation-0.1.0.zip"
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="blendlocation-test-") as tmp:
        env = os.environ.copy()
        # Blender ignores user path overrides if their directories do not exist.
        for variable, folder in (("BLENDER_USER_RESOURCES", "resources"),
                                 ("BLENDER_USER_CONFIG", "config"),
                                 ("BLENDER_USER_SCRIPTS", "scripts"),
                                 ("BLENDER_USER_EXTENSIONS", "extensions")):
            path = Path(tmp) / folder
            path.mkdir()
            env[variable] = str(path)
        run([blender, "--command", "extension", "validate"], env)
        run([blender, "--command", "extension", "build", "--source-dir", ROOT,
             "--output-filepath", output], env)
        run([blender, "--command", "extension", "validate", output], env)
        print(f"Built {output}")
        if args.action == "test":
            repository = Path(tmp) / "repo"
            run([blender, "--command", "extension", "repo-add", "blendlocation_test",
                 "--name", "BlendLocation Test", "--directory", repository], env)
            run([blender, "--command", "extension", "install-file", "-r", "blendlocation_test", "-e", output], env)
            run([blender, "--background", "--python-exit-code", "1", "--python", ROOT / "tests" / "blender_smoke.py"], env)


if __name__ == "__main__":
    main()
