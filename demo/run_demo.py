"""Run every demo input against a running backend and print what came back.

    python demo/run_demo.py            # server on http://localhost:8000
    python demo/run_demo.py 8010       # another port
"""

import base64
import json
import pathlib
import sys
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8000"
HERE = pathlib.Path(__file__).parent

LINKS = [
    ("Real Guardian article", "https://www.theguardian.com/world/2024/mar/07/sweden-joins-nato-after-ratification-hungary-drops-opposition"),
    ("Page that does not exist", "https://www.theguardian.com/world/2016/jun/24/this-page-does-not-exist"),
    ("Guardrail: localhost", "http://127.0.0.1:8000/health"),
    ("Guardrail: cloud metadata address", "http://169.254.169.254/latest/meta-data/"),
    ("Guardrail: not http", "ftp://example.com/file"),
]


def check(payload: dict) -> str:
    req = urllib.request.Request(f"http://localhost:{PORT}/api/check", json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    verdict = error = None
    with urllib.request.urlopen(req, timeout=180) as resp:
        for line in resp:
            if line.startswith(b"data: "):
                event = json.loads(line[6:])
                if event["type"] == "verdict":
                    verdict = event["report"]
                elif event["type"] == "error":
                    error = event
    if error:
        return f"ERROR ({error['code']}): {error['message']}"
    labels = ", ".join(f"{c['label']} \"{c['claim']['text'][:60]}\"" for c in verdict["claims"]) or "no claims checked"
    return f"{verdict['overall_label']}: {labels}\n      {verdict['answer'][:150]}"


for name, url in LINKS:
    print(f"LINK  {name}\n      {check({'kind': 'url', 'url': url})}\n")
for path in sorted((HERE / "images").glob("*.png")):
    b64 = base64.b64encode(path.read_bytes()).decode()
    print(f"IMAGE {path.name}\n      {check({'kind': 'image', 'image_b64': b64, 'mime': 'image/png'})}\n")
