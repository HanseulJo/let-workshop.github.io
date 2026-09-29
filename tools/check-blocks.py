# Every .event clips at overflow:hidden, so any extra spacing has to be paid
# for out of slack that is actually there. This reports the ones that spill.
import json, subprocess, sys, tempfile, time, urllib.request, random, websocket
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
JS = """(() => {
  const out = [];
  for (const e of document.querySelectorAll('.event')) {
    const over = e.scrollHeight - e.clientHeight;
    if (over > 0) out.push({t: (e.querySelector('.title')||e).textContent.trim().slice(0,34),
                            over, h: e.clientHeight, cls: e.className});
  }
  return JSON.stringify(out);
})()"""
def run(w, lang="ko-KR"):
    port = random.randint(9400, 9800); prof = tempfile.mkdtemp()
    p = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu",
        f"--remote-debugging-port={port}", "--remote-allow-origins=*",
        f"--user-data-dir={prof}", "--hide-scrollbars", f"--window-size={w},1000",
        "--no-first-run", f"--lang={lang}",
        "file:///Users/edong6768/Downloads/kolt/_site/2026/index.html"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    for _ in range(40):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
            pages = [t for t in tabs if t["type"] == "page" and t.get("webSocketDebuggerUrl")]
            if pages:
                ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], suppress_origin=True); break
        except Exception: pass
        time.sleep(0.4)
    if ws is None: p.terminate(); sys.exit("chrome never came up")
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable"})); ws.recv()
    time.sleep(2.0)
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": JS}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == 2: break
    ws.close(); p.terminate()
    return json.loads(r["result"]["result"]["value"])
if __name__ == "__main__":
    bad = 0
    for w in (1440, 1300, 1024, 900, 781):
        rows = run(w)
        print(f"  {w:>5}px  {'all fit' if not rows else str(len(rows)) + ' clipped'}")
        for r in rows:
            print(f"          +{r['over']}px  h={r['h']}  {r['cls']}  {r['t']}")
        bad += len(rows)
    sys.exit(1 if bad else 0)
