"""Fetch only the FABDEM tiles an area needs from the University of Bristol's 10 x 10 degree zip, without downloading
the whole zip (556 MB for Malaysia's): the zip's index is read from its end with HTTP range requests, then only the
wanted tiles' bytes. Writes each tile's zip entry into a small zip of its own, which tools/build_pooling.py reads.

    .venv/bin/python tools/fetch_fabdem.py --tiles N02E101 N03E101 \\
        --out ../05_Raw_Data_Sources/fabdem/shah-alam_FABDEM_V1-2.zip

Standard library only. The licence (CC BY-NC-SA 4.0) and readme are saved beside the output.
"""
from __future__ import annotations

import argparse
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/"
ZIP = "N00E100-N10E110_FABDEM_V1-2.zip"
AGENT = {"User-Agent": "Mozilla/5.0 (MyFlood data fetch)"}


class RangeFile:
    """A read-only, seekable file over HTTP range requests, enough for zipfile."""

    def __init__(self, url: str) -> None:
        self.url, self.at = url, 0
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=AGENT), timeout=60) as answer:
            self.size = int(answer.headers["Content-Length"])

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.at

    def seek(self, offset: int, whence: int = 0) -> int:
        self.at = {0: offset, 1: self.at + offset, 2: self.size + offset}[whence]
        return self.at

    def read(self, count: int = -1) -> bytes:
        if count < 0:
            count = self.size - self.at
        if count == 0 or self.at >= self.size:
            return b""
        end = min(self.size, self.at + count) - 1
        request = urllib.request.Request(self.url, headers={**AGENT, "Range": f"bytes={self.at}-{end}"})
        with urllib.request.urlopen(request, timeout=600) as answer:
            if answer.status != 206:
                raise OSError(f"the server ignored the range request (HTTP {answer.status})")
            data = answer.read()
        self.at += len(data)
        return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tiles", nargs="+", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RangeFile(BASE + ZIP)) as remote, zipfile.ZipFile(args.out, "w", zipfile.ZIP_STORED) as local:
        names = remote.namelist()
        for tile in args.tiles:
            name = next((n for n in names if tile in n and n.endswith(".tif")), None)
            if name is None:
                raise SystemExit(f"{tile} is not in {ZIP}")
            info = remote.getinfo(name)
            print(f"{name}: {info.compress_size / 1e6:.1f} MB")
            local.writestr(Path(name).name, remote.read(name))
    for extra in ("license.txt", "readme.txt"):
        with urllib.request.urlopen(urllib.request.Request(BASE + extra, headers=AGENT), timeout=60) as answer:
            (args.out.parent / extra).write_bytes(answer.read())
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
