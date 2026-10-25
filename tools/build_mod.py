"""Build and install the Bloodstained AP client.

Before building, Mod/ClientVersion.h and Mod/StaticPakPin.h are regenerated from
version.toml and release/static_pak_manifest.json (see release_info.py). Machine-specific
defaults such as --game-dir belong in build_config.toml.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

from build_config import apply_config
from release_info import REPOSITORY, sha256, sync_generated_headers


PROJECT = REPOSITORY / "BloodstainedModdingSDK.vcxproj"
ARTIFACT = REPOSITORY / "x64/Release/BloodstainedAP.asi"
GAME_PROCESS = "BloodstainedRotN-Win64-Shipping.exe"
# Fallbacks for a machine without build_config.toml.
GAME_DIRECTORY = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Bloodstained Ritual of the Night"
    r"\BloodstainedRotN\Binaries\Win64"
)
DEFAULT_JOBS = 16
PLUGIN_RELATIVE_PATH = Path("plugins/BloodstainedAP.asi")


def positive_integer(value: str) -> int:
    jobs = int(value)
    if jobs < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return jobs


def sanitized_environment(jobs: int) -> dict[str, str]:
    environment: dict[str, str] = {}
    seen: set[str] = set()
    for key, value in os.environ.items():
        folded = key.casefold()
        if folded in seen or folded in {
            "codex_sandbox",
            "codex_sandbox_network_disabled",
        }:
            continue
        seen.add(folded)
        environment[key] = value
    environment["CL_MP"] = "true"
    environment["CL_MPCount"] = str(jobs)
    return environment


def find_msbuild() -> Path | None:
    """Locate MSBuild.exe via MSBUILD env var, vswhere, then PATH."""
    override = os.environ.get("MSBUILD")
    if override and Path(override).is_file():
        return Path(override)

    program_files = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
    if program_files:
        vswhere = Path(program_files) / "Microsoft Visual Studio/Installer/vswhere.exe"
        if vswhere.is_file():
            result = subprocess.run(
                [
                    str(vswhere),
                    "-latest",
                    "-products",
                    "*",
                    "-requires",
                    "Microsoft.Component.MSBuild",
                    "-find",
                    r"MSBuild\**\Bin\MSBuild.exe",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in result.stdout.splitlines():
                if line.strip() and Path(line.strip()).is_file():
                    return Path(line.strip())

    on_path = shutil.which("MSBuild")
    return Path(on_path) if on_path else None


def game_is_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"tasklist failed: {result.stderr.strip()}")
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) >= 2 and row[1].replace(",", "").isdigit():
            return True
    return False


def install(installed_plugin: Path) -> str:
    if not ARTIFACT.is_file():
        raise FileNotFoundError(f"build succeeded without producing {ARTIFACT}")
    installed_plugin.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ARTIFACT, installed_plugin)
    artifact_hash = sha256(ARTIFACT)
    installed_hash = sha256(installed_plugin)
    if artifact_hash != installed_hash:
        raise RuntimeError(
            f"installed plugin hash mismatch: {installed_hash} != {artifact_hash}"
        )
    return artifact_hash


def run_msbuild(
    msbuild: Path, target: str, jobs: int, toolset: str | None
) -> subprocess.CompletedProcess[str]:
    command = [
        str(msbuild),
        str(PROJECT),
        f"/t:{target}",
        "/p:Configuration=Release",
        "/p:Platform=x64",
        f"/m:{jobs}",
    ]
    if toolset:
        command.append(f"/p:PlatformToolset={toolset}")
    print(f"Running {target} with {jobs} compiler workers", flush=True)
    return subprocess.run(
        command,
        cwd=REPOSITORY,
        env=sanitized_environment(jobs),
        capture_output=True,
        text=True,
        check=False,
    )


def log_build_result(target: str, result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if result.returncode != 0:
        print(f"{target} failed with exit code {result.returncode}.", file=sys.stderr, flush=True)


def build(msbuild: Path, clean: bool, jobs: int, toolset: str | None) -> int:
    target = "Rebuild" if clean else "Build"
    result = run_msbuild(msbuild, target, jobs, toolset)
    log_build_result(target, result)
    if result.returncode == 0 or clean:
        return result.returncode

    print("Incremental build failed; retrying with a clean rebuild.", file=sys.stderr, flush=True)
    result = run_msbuild(msbuild, "Rebuild", jobs, toolset)
    log_build_result("Rebuild", result)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="perform a full rebuild instead of the default incremental build",
    )
    parser.add_argument(
        "--jobs",
        type=positive_integer,
        default=DEFAULT_JOBS,
        metavar="N",
        help="maximum MSBuild and compiler workers (default: %(default)s)",
    )
    parser.add_argument(
        "--toolset",
        metavar="NAME",
        help="override the project's PlatformToolset, e.g. v145 (default: use the .vcxproj)",
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=GAME_DIRECTORY,
        metavar="PATH",
        help="game Win64 binaries directory to install into (default: %(default)s)",
    )
    apply_config(parser, "mod")
    args = parser.parse_args()
    game_directory: Path = args.game_dir

    if game_is_running():
        parser.error(f"{GAME_PROCESS} is running; exit the game before building")
    msbuild = find_msbuild()
    if msbuild is None:
        parser.error(
            "MSBuild was not found (checked MSBUILD env var, vswhere, and PATH)"
        )
    if not game_directory.is_dir():
        parser.error(f"game directory was not found at {game_directory}")

    for header in sync_generated_headers():
        print(f"Regenerated {header.relative_to(REPOSITORY)}")
    build_result = build(msbuild, args.clean, args.jobs, args.toolset)
    if build_result != 0:
        return build_result

    installed_plugin = game_directory / PLUGIN_RELATIVE_PATH
    installed_hash = install(installed_plugin)
    print(f"Installed: {installed_plugin}")
    print(f"SHA-256: {installed_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
