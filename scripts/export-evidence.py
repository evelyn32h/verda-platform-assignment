"""Export a sanitized hand-in record from a successful verification run."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    source = parser.parse_args().run_directory.resolve()
    source.relative_to(ROOT / ".local" / "evidence")
    run = json.loads((source / "run.json").read_text())
    assert run["status"] == "PASS" and run["action"] == "verify"
    config = json.loads((ROOT / "platform.json").read_text())
    text = (source / f"{config['server']}-verify.txt").read_text(encoding="utf-8")
    markers = ["APP_REPLICAS=2", "APP_SPREAD_ACROSS_TWO_NODES=PASS",
               "METRICS_API=AVAILABLE", "MONITORING_SERVICES_PRIVATE=PASS",
               "ALL_REQUIRED_REMOTE_CHECKS_PASS"]
    assert all(marker in text for marker in markers)

    def record(prefix):
        return json.loads(next(line[len(prefix):] for line in text.splitlines() if line.startswith(prefix)))

    external = json.loads((source / "external-checks.json").read_text())
    assert all(item.get("status") == "PASS" or item.get("externally_reachable") is False for item in external)
    panels = record("GRAFANA_PANEL_RESULTS=")
    assert len(panels) == 6 and all(panels.values())
    targets = record("PROMETHEUS_TARGETS=")
    assert targets["total"] > 0 and not targets["down"]
    paths = [ROOT / "platform.json", ROOT / "scripts/platform.py"]
    paths += sorted((ROOT / "scripts/remote").glob("*.sh"))
    paths += sorted((ROOT / "manifests").glob("*.yaml"))
    summary = {
        "status": "PASS", "verified_at": run["finished_at"],
        "raw_evidence_directory": source.relative_to(ROOT).as_posix(),
        "hosts": run["hosts"], "k3s_version": config["k3s_version"],
        "monitoring_chart_version": config["monitoring_chart_version"],
        "checks": markers, "prometheus_queries": record("PROMETHEUS_QUERIES="),
        "prometheus_targets": targets, "grafana": record("GRAFANA="),
        "dashboard_panel_values": panels, "external_checks": external,
        "tls": {"type": "self-signed IP certificate",
                "not_after": re.search(r"^notAfter=(.+)$", text, re.MULTILINE).group(1),
                "sha256_fingerprint": re.search(r"sha256 Fingerprint=(.+)$", text, re.MULTILINE).group(1)},
        "raw_file_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(source.iterdir()) if p.is_file()},
        "deployment_source_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    }
    output = ROOT / "docs/evidence/required-checks.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {output.relative_to(ROOT)}; verified at {run['finished_at']}")


if __name__ == "__main__":
    main()
