#!/usr/bin/env python3
"""
Generate availability.json: which DuckDB versions and platforms each community
extension has a binary for, based on a listing of the extensions bucket.

Usage:
  python3 scripts/generate_availability.py [--from-file keys.txt] [--output build/availability.json]

Without --from-file, the bucket is listed with `aws s3 ls --recursive`
(credentials and AWS_ENDPOINT_URL are taken from the environment).
--from-file accepts either plain object keys or `aws s3 ls` output lines.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BUCKET = "duckdb-community-extensions"

# Display order of platforms, grouped by family. Platforms found in the bucket
# but not listed here are appended at the end in alphabetical order.
PLATFORM_ORDER = [
    "linux_amd64",
    "linux_arm64",
    "linux_amd64_musl",
    "linux_arm64_musl",
    "osx_amd64",
    "osx_arm64",
    "windows_amd64",
    "windows_amd64_mingw",
    "windows_amd64_rtools",
    "windows_arm64",
    "wasm_mvp",
    "wasm_eh",
    "wasm_threads",
]

KEY_PATTERN = re.compile(
    r"^(v\d+\.\d+\.\d+)/([a-z0-9_]+)/([A-Za-z0-9_]+)\.duckdb_extension\.(gz|wasm)$"
)


def list_bucket_keys():
    result = subprocess.run(
        ["aws", "s3", "ls", f"s3://{BUCKET}/", "--recursive"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def parse_key(line):
    # `aws s3 ls` lines look like "2024-06-03 12:00:00   123456 v1.0.0/osx_arm64/x.duckdb_extension.gz";
    # the key is the last field (keys never contain spaces).
    fields = line.split()
    if not fields:
        return None
    return KEY_PATTERN.match(fields[-1])


def version_sort_key(version):
    return tuple(int(part) for part in version[1:].split("."))


def platform_sort_key(platform):
    if platform in PLATFORM_ORDER:
        return (0, PLATFORM_ORDER.index(platform), platform)
    return (1, 0, platform)


def build_availability(lines):
    found = {}
    for line in lines:
        match = parse_key(line)
        if match is None:
            continue
        version, platform, extension, _ = match.groups()
        found.setdefault(extension, {}).setdefault(version, set()).add(platform)

    platforms = sorted(
        {p for versions in found.values() for ps in versions.values() for p in ps},
        key=platform_sort_key,
    )
    versions = sorted(
        {v for versions in found.values() for v in versions}, key=version_sort_key
    )
    platform_index = {p: i for i, p in enumerate(platforms)}

    extensions = {}
    for extension in sorted(found):
        extensions[extension] = {
            version: sorted(platform_index[p] for p in found[extension][version])
            for version in sorted(found[extension], key=version_sort_key)
        }

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": platforms,
        "versions": versions,
        "extensions": extensions,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--from-file", help="read keys from a file instead of listing the bucket"
    )
    parser.add_argument("--output", default="build/availability.json")
    args = parser.parse_args()

    if args.from_file:
        lines = Path(args.from_file).read_text().splitlines()
    else:
        lines = list_bucket_keys()

    availability = build_availability(lines)
    if not availability["extensions"]:
        sys.exit("No extension binaries found, refusing to write an empty file")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(availability, separators=(",", ":")) + "\n")
    print(
        f"Wrote {output}: {len(availability['extensions'])} extensions, "
        f"{len(availability['versions'])} versions, {len(availability['platforms'])} platforms"
    )


if __name__ == "__main__":
    main()
