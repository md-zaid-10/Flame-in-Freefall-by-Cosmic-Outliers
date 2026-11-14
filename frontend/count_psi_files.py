"""Count every file PSI holds for the 24 combustion investigations.

Source of the "NASA files" figure on the home screen. Hits PSI's public API
(the same endpoints as rag/prep/build_manifest.py) and writes
frontend/data/psi_file_count.json. Uses curl to avoid macOS SSL issues.

    python3 frontend/count_psi_files.py
"""
import datetime
import json
import os
import subprocess

B = "https://psi.nasa.gov/geode-py/ws"
ACC = ['PSI-26', 'PSI-25', 'PSI-98', 'PSI-99', 'PSI-100', 'PSI-69', 'PSI-68', 'PSI-39',
       'PSI-159', 'PSI-102', 'PSI-101', 'PSI-47', 'PSI-107', 'PSI-106', 'PSI-10', 'PSI-20',
       'PSI-21', 'PSI-22', 'PSI-23', 'PSI-117', 'PSI-142', 'PSI-62', 'PSI-60', 'PSI-115']
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "psi_file_count.json")


def curl(args):
    r = subprocess.run(["curl", "-s", "--max-time", "180", "-A", "research-client"] + args,
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def count(nodes):
    n = 0
    for x in nodes or []:
        if x.get("directory") is False and x.get("key"):
            n += 1
        if x.get("files"):
            n += count(x["files"])
    return n


def main():
    per = {}
    for a in ACC:
        v = curl([f"{B}/repo/investigations/{a}"]).get("version")
        body = json.dumps({"folder": f"psi-data/{a}/", "fileType": "study", "studyId": a,
                           "version": v, "obfuscationcode": ""})
        j = curl(["-X", "POST", "-H", "Content-Type: application/json", "-d", body,
                  f"{B}/files/v2"])
        per[a] = count(j.get("files"))
        print(f"{a:8} {per[a]:6d}", flush=True)
    out = {"total": sum(per.values()), "investigations": len(per), "per_investigation": per,
           "counted_on": datetime.date.today().isoformat(),
           "method": "All files listed by PSI's files API for the 24 combustion investigations."}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print("TOTAL", out["total"])


if __name__ == "__main__":
    main()
