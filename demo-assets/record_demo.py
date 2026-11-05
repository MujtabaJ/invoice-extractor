"""Record a two-minute CLI demo: process, queue, then approve.

The scanned sample needs Tesseract. If those tools are missing it is set aside
for this recording and restored afterwards, so `process samples/` still runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
RAW = OUT / "video-raw"
PY = os.environ.get("IE_PYTHON", sys.executable)
SCAN = ROOT / "samples" / "harbour-print-HP-5602-scan.pdf"
HELD = ROOT / "samples_holdout" / "harbour-print-HP-5602-scan.pdf"


def run(cmd: list[str]) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["IE_DB"] = str(ROOT / "invoices.db")
    proc = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True)
    text = proc.stdout
    if proc.returncode != 0:
        text += proc.stderr
    return text.rstrip("\n")


HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>invoice-extractor — zsh</title>
<style>
  html, body { margin: 0; height: 100%; background: #1c1c1c; color: #e6edf3;
    font: 16px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; }
  header { height: 38px; background: #2b2b2b; display: flex; align-items: center; gap: 8px;
    padding: 0 14px; color: #c8c8c8; font-family: system-ui, sans-serif; font-size: 13px; }
  i { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
  .r { background: #ff5f57; } .y { background: #febc2e; } .g { background: #28c840; }
  header b { flex: 1; text-align: center; font-weight: 600; margin-right: 52px; }
  pre { margin: 0; padding: 18px 22px 40px; white-space: pre-wrap; }
  .dim { color: #8b9cb3; } .cmd { color: #fff; } .bad { color: #ffb4a8; } .good { color: #8ee7b5; }
</style>
</head>
<body>
<header><i class="r"></i><i class="y"></i><i class="g"></i><b>invoice-extractor — zsh</b></header>
<pre id="term"></pre>
<script>
const term = document.getElementById('term');
function add(html) { term.insertAdjacentHTML('beforeend', html); window.scrollTo(0, document.body.scrollHeight); }
</script>
</body>
</html>
"""


def colorize(line: str) -> str:
    safe = (line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    if "needs_review" in line or line.strip().startswith("error:"):
        return f'<span class="bad">{safe}</span>'
    if "auto_approved" in line or line.strip() == "updated":
        return f'<span class="good">{safe}</span>'
    return safe


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    db = ROOT / "invoices.db"
    if db.exists():
        db.unlink()
    moved = False
    if SCAN.exists() and not (shutil.which("tesseract") and shutil.which("pdftoppm")):
        HELD.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(SCAN), str(HELD))
        moved = True
    try:
        process_out = run([PY, "-m", "ie.cli", "process", "samples/"])
        queue_out = run([PY, "-m", "ie.cli", "queue"])
        approve_out = run([PY, "-m", "ie.cli", "approve", "4"])
        export_out = run([PY, "-m", "ie.cli", "export"])
    finally:
        if moved and HELD.exists() and not SCAN.exists():
            shutil.move(str(HELD), str(SCAN))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=str(RAW),
            record_video_size={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.set_content(HTML)
        page.wait_for_timeout(1500)

        def prompt() -> None:
            page.evaluate("""() => add('<span class="good">invoice-extractor</span> <span class="dim">%</span> ')""")

        def type_cmd(text: str) -> None:
            for ch in text:
                page.evaluate("(ch) => add('<span class=cmd>' + ch.replace('&','&amp;').replace('<','&lt;') + '</span>')", ch)
                page.wait_for_timeout(38)
            page.evaluate("() => add('\\n')")

        def show(text: str, delay: int = 280) -> None:
            for line in text.splitlines():
                page.evaluate("(html) => add(html + '\\n')", colorize(line))
                page.wait_for_timeout(delay)

        prompt()
        type_cmd("python -m ie.cli process samples/")
        page.wait_for_timeout(600)
        show(process_out, 700)
        page.wait_for_timeout(22000)

        prompt()
        type_cmd("python -m ie.cli queue")
        page.wait_for_timeout(500)
        show(queue_out, 900)
        page.wait_for_timeout(26000)

        prompt()
        type_cmd("python -m ie.cli approve 4")
        page.wait_for_timeout(400)
        show(approve_out or "updated", 400)
        page.evaluate("() => add('<span class=dim># Reviewer checked INV-10612 and approved it. The queue had flagged that subtotal + tax does not match the printed total.</span>\\n')")
        page.wait_for_timeout(14000)

        prompt()
        type_cmd("python -m ie.cli export")
        page.wait_for_timeout(400)
        show("\n".join(export_out.splitlines()[:8]), 450)
        page.wait_for_timeout(18000)

        context.close()
        browser.close()

    webms = sorted(RAW.glob("*.webm"), key=lambda item: item.stat().st_mtime)
    if not webms:
        raise SystemExit("no video was recorded")
    target = OUT / "invoice-extractor-demo.webm"
    webms[-1].replace(target)
    print(target)


if __name__ == "__main__":
    main()
