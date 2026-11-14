"""Download NASA PSI combustion investigation metadata + experimental tables.

Usage (from repo root):  python3 data/fetch_psi.py            # all combustion IDs
                         python3 data/fetch_psi.py PSI-25     # just one
Source: NASA Physical Sciences Informatics (https://psi.nasa.gov), open data, CC0.
Stdlib only. Raw video/data files are NOT downloaded, only experimental tables.
"""
import json, os, subprocess, sys, urllib.parse, urllib.request

BASE = "https://psi.nasa.gov/geode-py/ws"
IDS = {  # accession -> short name
    "PSI-26": "BASS", "PSI-25": "BASS-II", "PSI-98": "Saffire-I", "PSI-99": "Saffire-II",
    "PSI-100": "Saffire-III", "PSI-102": "SAME", "PSI-101": "SAME-R", "PSI-69": "FLEX",
    "PSI-68": "FLEX-2", "PSI-39": "CFI", "PSI-159": "ACME CFI-G", "PSI-10": "ACME Flame Design",
    "PSI-20": "ACME BRE", "PSI-21": "ACME CLD", "PSI-22": "ACME E-FIELD", "PSI-23": "ACME s-Flame",
    "PSI-107": "SPICE", "PSI-106": "SLICE",
    "PSI-117": "ground", "PSI-62": "ground", "PSI-60": "ground", "PSI-142": "ground", "PSI-115": "ground",
}
MAX_TABLE_MB = 50
HERE = os.path.dirname(os.path.abspath(__file__))
RAW_INV = os.path.join(HERE, "raw", "investigations")
RAW_TAB = os.path.join(HERE, "raw", "tables")
META_KEYS = ["accession", "title", "investigationAcronym", "doi", "objective", "hypothesis",
             "approach", "researchImpacts", "description", "missionName", "flightProgram",
             "investigationStartDate", "investigationEndDate", "licenseName", "publications"]


def get(url):
    """GET -> bytes. Falls back to system curl (macOS python often lacks SSL certs)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "flamescope"}), timeout=120) as r:
            return r.read()
    except Exception as e:
        if "CERTIFICATE" not in str(e) and "SSL" not in str(e):
            raise
        return subprocess.run(["curl", "-sSfL", "--max-time", "300", url], check=True, capture_output=True).stdout


def signed_url(study_id, fname, version):
    q = urllib.parse.urlencode({"file": fname, "version": version, "redirect": "false"})
    body = get(f"{BASE}/studies/{study_id}/download?{q}").decode().strip()
    try:
        j = json.loads(body)
        if isinstance(j, str):
            return j
        for k in ("url", "signed_url", "presigned_url", "location"):
            if isinstance(j, dict) and j.get(k):
                return j[k]
        raise ValueError(f"unexpected JSON: {body[:200]}")
    except json.JSONDecodeError:
        return body  # plain-text URL


def main(ids):
    os.makedirs(RAW_INV, exist_ok=True)
    os.makedirs(RAW_TAB, exist_ok=True)
    meta_path = os.path.join(HERE, "metadata.json")
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
    for acc in ids:
        print(f"\n== {acc} ({IDS.get(acc, '?')})")
        try:
            inv = json.loads(get(f"{BASE}/repo/investigations/{acc}"))
        except Exception as e:
            print(f"   !! investigation fetch failed: {e}")
            continue
        json.dump(inv, open(os.path.join(RAW_INV, f"{acc}.json"), "w"), indent=1)
        rec = {k: inv.get(k) for k in META_KEYS}
        rec["short_name"] = IDS.get(acc)
        rec["tables"] = []
        for t in inv.get("experimentalTable") or []:
            fname, ver, sid = t.get("file_name"), t.get("version"), t.get("study_id")
            size_mb = (t.get("file_size") or 0) / 1e6
            entry = {"file_name": fname, "version": ver, "study_id": sid, "size_mb": round(size_mb, 2)}
            if size_mb > MAX_TABLE_MB:
                print(f"   skip (>{MAX_TABLE_MB} MB): {fname}")
                entry["status"] = "skipped_large"
            else:
                out_dir = os.path.join(RAW_TAB, acc)
                os.makedirs(out_dir, exist_ok=True)
                out = os.path.join(out_dir, fname)
                try:
                    data = None
                    for ident in (sid, acc):  # endpoint may want study_id or accession
                        try:
                            data = get(signed_url(ident, fname, ver))
                            break
                        except Exception as e:
                            last = e
                    if data is None:
                        raise last
                    open(out, "wb").write(data)
                    entry["path"] = os.path.relpath(out, os.path.dirname(HERE))
                    entry["status"] = "ok"
                    print(f"   table: {fname} ({len(data)/1e3:.0f} kB)")
                except Exception as e:
                    entry["status"] = f"error: {e}"
                    print(f"   !! table failed: {fname}: {e}")
            rec["tables"].append(entry)
        if not rec["tables"]:
            print("   (no experimental table)")
        print(f"   title: {(rec.get('title') or '')[:90]}")
        print(f"   doi: {rec.get('doi')}  publications: {len(rec.get('publications') or [])}")
        meta[acc] = rec
        json.dump(meta, open(meta_path, "w"), indent=2)
    print(f"\nDone. Metadata -> {meta_path}")


if __name__ == "__main__":
    main(sys.argv[1:] or list(IDS))
