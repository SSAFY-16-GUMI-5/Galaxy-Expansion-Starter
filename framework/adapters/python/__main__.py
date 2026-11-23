"""Load a participant module and run it over JSONL."""

import argparse
from contextlib import redirect_stdout
from importlib import import_module
import sys

from . import _run


def main() -> int:
    output = sys.stdout.buffer
    with redirect_stdout(sys.stderr):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--module", default="solution.main", help="participant module to load")
        parser.add_argument("--reset-on-start", action="store_true", help="reset slots after init")
        options = parser.parse_args()
        try:
            module = import_module(options.module)
            create_pool = module.create_pool
            scenario = module.scenario
            snapshot = module.snapshot
            if not all(callable(hook) for hook in (create_pool, scenario, snapshot)):
                raise TypeError("create_pool, scenario and snapshot must be callable")
            pool = create_pool()
        except KeyboardInterrupt:
            print("[galaxy runner] participant setup: interrupted", file=sys.stderr)
            return 130
        except (Exception, SystemExit) as exc:
            print(
                f"[galaxy runner] participant setup ({options.module}): {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1
        return _run(output, pool, scenario, snapshot=snapshot, reset_on_start=options.reset_on_start)


if __name__ == "__main__":
    raise SystemExit(main())
