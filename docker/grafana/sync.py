"""Load the dashboard file into the local Grafana, or save the local Grafana's version back into the file."""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

GRAFANA = "http://localhost:3000"
API = f"{GRAFANA}/apis/dashboard.grafana.app/v1beta1/namespaces/default/dashboards"


def call(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def load(path: Path) -> None:
    doc = json.loads(path.read_text())
    name = doc["metadata"]["name"]
    try:
        live = call("GET", f"{API}/{name}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        call("POST", API, doc)
    else:
        doc["metadata"]["resourceVersion"] = live["metadata"]["resourceVersion"]
        call("PUT", f"{API}/{name}", doc)
    print(f"loaded {path} -> {GRAFANA}/d/{doc['spec'].get('uid', name)}")
    warm(doc["spec"])


def warm(spec: dict) -> None:
    """Run every panel and annotation query once with the default filters, so the proxy's cache serves the page."""
    values = {v["name"]: v.get("current", {}).get("value", "") for v in spec.get("templating", {}).get("list", [])}
    targets = [(p["title"], t) for p in spec["panels"] for t in p.get("targets", [])]
    targets += [(a["name"], a["target"]) for a in spec.get("annotations", {}).get("list", []) if "target" in a]
    time_range = spec.get("time", {"from": "now-7d", "to": "now"})
    failed = 0
    for title, t in targets:
        sql = t.get("rawSql", "")
        for name, value in values.items():
            sql = sql.replace(f"${{{name}}}", str(value))
        query = dict(t, rawSql=sql, datasource={"uid": values.get("datasource", t["datasource"]["uid"])})
        res = call("POST", f"{GRAFANA}/api/ds/query", {"queries": [query], **time_range})["results"][t["refId"]]
        if "error" in res:
            failed += 1
            print(f"error in {title}: {res['error'][:200]}")
    print(f"warmed {len(targets) - failed} of {len(targets)} queries")


def save(path: Path) -> None:
    name = json.loads(path.read_text())["metadata"]["name"]
    live = call("GET", f"{API}/{name}")
    spec = live["spec"]
    spec.pop("id", None)
    spec.pop("version", None)
    doc = {"apiVersion": live["apiVersion"], "kind": live["kind"], "metadata": {"name": name}, "spec": spec}
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"saved {GRAFANA}/d/{spec.get('uid', name)} -> {path}")


if __name__ == "__main__":
    {"load": load, "save": save}[sys.argv[1]](Path(sys.argv[2]))
