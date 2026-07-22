from __future__ import annotations

import argparse

from aiflow import __version__


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="aiflow")
    result.add_argument("--version", action="version", version=__version__)
    return result


def main(argv: list[str] | None = None) -> int:
    parser().parse_args(argv)
    return 0
