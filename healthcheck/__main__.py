import argparse
from collections import Counter
from pathlib import Path
import sys

from .core import load_config, run_probes, save_results
from .site import ROOT, build_demo, build_site


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe model APIs and build a static status page")
    parser.add_argument("command", choices=("validate", "check", "build", "demo"))
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "models.json")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", action="append", help="Probe only this configured model (repeatable)")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.command == "validate":
            print(f"Configuration valid: {len(config['models'])} models; interval {config['interval_minutes']} minutes")
        elif args.command == "check":
            results = run_probes(config, args.model)
            save_results(args.data_dir, results, config["retention_days"])
            counts = Counter(result["status"] for result in results)
            print("Probe finished: " + ", ".join(f"{status}={counts[status]}" for status in sorted(counts)))
            for result in results:
                print(f"{result['model']}: {result['status']} / {result['reason']}")
        elif args.command == "build":
            manifest = build_site(config, args.data_dir, args.output or ROOT / "site")
            print(f"Site built: {len(manifest['models'])} models; {len(manifest['history'])} history days")
        else:
            build_demo(config, args.output or ROOT / ".preview")
            print("Synthetic demo built; no API calls were made")
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        # Avoid dumping exceptions that can contain API data or credentials.
        print("Command failed. Check configuration/data validity and required API-key environment variables. No raw API response was logged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
