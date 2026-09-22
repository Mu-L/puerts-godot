#!/usr/bin/env python3
"""Build puerts native backends for this repository."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from scons.puerts_matrix import ARCH_TO_PUERTS, PLATFORM_TO_PUERTS, SUPPORTED_BACKENDS

REPO_ROOT = Path(__file__).resolve().parents[1]
PUERTS_REPO_DIR = REPO_ROOT / "thirdparty" / "puerts"
UNITY_DIR = PUERTS_REPO_DIR / "unity"
NATIVE_DIR = UNITY_DIR / "native"
NODE_LIB_DIR = NATIVE_DIR / "papi-nodejs" / ".backends" / "papi-nodejs" / "lib"
BIN_DIR = REPO_ROOT / "bin"
PATCHES_DIR = REPO_ROOT / "patches"

BACKEND_ALIASES = {
    "core": "puerts",
    "v8": "papi-v8",
    "nodejs": "papi-nodejs",
    "quickjs": "papi-quickjs",
    "lua": "papi-lua",
}
CANONICAL_BACKENDS = set(BACKEND_ALIASES.values())

DEFAULT_ARCH = {
    "windows": "x86_64",
    "macos": "arm64",
    "linux": "x86_64",
    "android": "arm64",
    "ios": "arm64",
    "web": "wasm32",
}

# Patches applied to the puerts submodule before building.
# Each entry: (patch file name under patches/, applies?(platform, backends)).
PATCHES = [
    ("papi-lua-object-new-nullptr", lambda platform, backends: "papi-lua" in backends),
    ("papi-lua-value-ref-release", lambda platform, backends: "papi-lua" in backends),
    (
        "papi-v8-nodejs-linux-origin-rpath",
        lambda platform, backends: platform == "linux" and bool(backends & {"papi-v8", "papi-nodejs"}),
    ),
]
PATCH_APPLY_FLAGS = ["--ignore-whitespace", "--ignore-space-change"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build puerts native backends.")
    parser.add_argument(
        "--platform",
        required=True,
        choices=sorted(PLATFORM_TO_PUERTS.keys()),
        help="Godot platform name.",
    )
    parser.add_argument("--arch", default="", help="Godot arch (x86_64/x86_32/arm64/arm32/wasm32).")
    parser.add_argument(
        "--config",
        choices=["Release", "Debug"],
        default="Debug",
        help="Puerts CMake config.",
    )
    parser.add_argument(
        "--backends",
        default=",".join(BACKEND_ALIASES),
        help="Comma-separated backends: core,v8,nodejs,quickjs,lua",
    )
    return parser.parse_args()


def resolve_executable(name: str) -> str:
    path = shutil.which(name)
    if path:
        return path
    if os.name == "nt" and "." not in name:
        for ext in (".cmd", ".exe", ".bat"):
            path = shutil.which(name + ext)
            if path:
                return path
    return name


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    resolved = list(command)
    resolved[0] = resolve_executable(command[0])
    printable = " ".join(shlex.quote(str(part)) for part in resolved)
    print(f"[make_puerts] ({cwd}) $ {printable}")
    subprocess.run(resolved, cwd=str(cwd), env=env, check=True)


def ensure_patch(name: str) -> None:
    """Apply a patch to the puerts submodule; skip if already applied, fail otherwise."""
    patch_file = PATCHES_DIR / f"{name}.patch"
    if not patch_file.is_file():
        raise FileNotFoundError(f"patch file not found: {patch_file}")

    def applies_cleanly(*extra: str) -> bool:
        result = subprocess.run(
            [resolve_executable("git"), "apply", "--check", *extra, *PATCH_APPLY_FLAGS, str(patch_file.resolve())],
            cwd=PUERTS_REPO_DIR,
            capture_output=True,
        )
        return result.returncode == 0

    if applies_cleanly():
        run(["git", "apply", *PATCH_APPLY_FLAGS, str(patch_file.resolve())], PUERTS_REPO_DIR)
        print(f"[make_puerts] patch {name} applied.")
    elif applies_cleanly("--reverse"):
        print(f"[make_puerts] patch {name} already applied, skip.")
    else:
        raise RuntimeError(f"patch {name} does not apply cleanly; the puerts submodule may have drifted.")


def normalize_backends(raw: str) -> list[str]:
    result: list[str] = []
    for token in raw.split(","):
        name = token.strip().lower()
        if not name:
            continue
        canonical = BACKEND_ALIASES.get(name, name)
        if canonical not in CANONICAL_BACKENDS:
            raise ValueError(f"Unsupported backend token: {token}")
        if canonical not in result:
            result.append(canonical)
    return result


def build_backend(platform: str, puerts_arch: str, config: str, backend: str) -> None:
    backend_dir = NATIVE_DIR / backend
    if not backend_dir.is_dir():
        raise FileNotFoundError(f"Backend directory not found: {backend_dir}")

    cmd = [
        "node",
        "../../cli",
        "make",
        "--platform",
        PLATFORM_TO_PUERTS[platform],
        "--arch",
        puerts_arch,
        "--config",
        config,
    ]

    env = os.environ.copy()
    if platform == "android":
        env.setdefault("ANDROID_NDK", str(Path.home() / "android-ndk-r27d"))
    elif platform == "web":
        for key, flags in (("CFLAGS", "-pthread -fPIC"), ("CXXFLAGS", "-pthread -fPIC"), ("LDFLAGS", "-pthread")):
            env[key] = f"{env.get(key, '')} {flags}".strip()

    run(cmd, backend_dir, env)


def copy_nodejs_deps(platform: str, arch: str) -> None:
    """Stage Node.js backend runtime/static dependencies into bin/."""
    if platform == "windows":
        sources, dst_dir = [NODE_LIB_DIR / "Win64" / "libnode.dll"], BIN_DIR
    elif platform == "linux":
        sources, dst_dir = [NODE_LIB_DIR / "Linux" / "libnode.so.93"], BIN_DIR
    elif platform == "macos":
        sources, dst_dir = (
            [NODE_LIB_DIR / ("macOS_arm64" if arch == "arm64" else "macOS") / "libnode.93.dylib"],
            BIN_DIR,
        )
    elif platform == "ios":
        sources, dst_dir = sorted((NODE_LIB_DIR / "iOS").glob("*.a")), BIN_DIR / "ios-nodejs"
    else:  # web/android: nothing to copy
        return

    if not sources:
        raise FileNotFoundError(f"no nodejs dependency archives found under {NODE_LIB_DIR}")
    for src in sources:
        if not src.is_file():
            raise FileNotFoundError(f"nodejs dependency not found: {src}")
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst_dir / src.name)
        print(f"[make_puerts] copied {src} -> {dst_dir / src.name}")


def main() -> int:
    args = parse_args()

    if not UNITY_DIR.is_dir():
        print(f"[make_puerts] unity directory not found: {UNITY_DIR}", file=sys.stderr)
        return 2

    try:
        backends = normalize_backends(args.backends)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not backends:
        print("[make_puerts] no backend selected.", file=sys.stderr)
        return 2

    arch = args.arch or DEFAULT_ARCH[args.platform]
    puerts_arch = ARCH_TO_PUERTS.get(args.platform, {}).get(arch)
    if not puerts_arch:
        print(f"[make_puerts] unsupported arch mapping for platform={args.platform}, arch={arch}", file=sys.stderr)
        return 2

    for name, applies in PATCHES:
        if applies(args.platform, set(backends)):
            ensure_patch(name)

    run(["npm", "ci"], UNITY_DIR)

    supported = SUPPORTED_BACKENDS[args.platform]
    skipped = [backend for backend in backends if backend not in supported]
    for backend in skipped:
        print(f"[make_puerts] skip unsupported backend {backend} on {args.platform}")
    build_list = [backend for backend in backends if backend in supported]

    for backend in build_list:
        build_backend(args.platform, puerts_arch, args.config, backend)

    if not build_list:
        print("[make_puerts] no backend was built.", file=sys.stderr)
        return 2

    if "papi-nodejs" in build_list:
        copy_nodejs_deps(args.platform, arch)

    print("[make_puerts] summary")
    print(f"  platform: {args.platform}")
    print(f"  arch: {arch} -> {puerts_arch}")
    print(f"  config: {args.config}")
    print(f"  built: {', '.join(build_list)}")
    if skipped:
        print(f"  skipped: {', '.join(skipped)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
