#!/usr/bin/env python3
"""
FINGERPRINT-DB VERSIONING + safe PROMOTE/ROLLBACK.
The live gate DBs in Common\\Files are what the EAs trade off. Before any refresh
overwrites one, snapshot it so we can roll back. Snapshots are content-hashed so
daily runs don't pile up identical copies.

  snapshot                 -> archive current live DBs (only if changed since last)
  promote  <stream>        -> snapshot the live DB, then copy the *_research DB over it
  rollback <stream> [ts]   -> restore a versioned DB to live (latest, or a given timestamp)
  list     [stream]        -> show archived versions

streams: gold | oil | silver
"""
import os, io, sys, shutil, hashlib, glob
from datetime import datetime

HERE   = os.path.dirname(os.path.abspath(__file__))
COMMON = r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
VERDIR = os.path.join(HERE, "db_versions")
os.makedirs(VERDIR, exist_ok=True)

LIVE = {
    "gold":   "gridstat_setups_gold.csv",
    "oil":    "gridstat_setups_oil_mt5.csv",
    "silver": "gridstat_setups_silver_mt5.csv",
}
RESEARCH = {
    "gold": os.path.join(HERE, "analysis_data", "gridstat_setups_gold_research.csv"),
    "oil":  os.path.join(HERE, "analysis_data", "gridstat_setups_oil_research.csv"),
}

def md5(path):
    if not os.path.exists(path): return None
    return hashlib.md5(io.open(path, "rb").read()).hexdigest()

def latest_version(stream):
    vs = sorted(glob.glob(os.path.join(VERDIR, f"{LIVE[stream]}.*.csv")))
    return vs[-1] if vs else None

def snapshot(streams=None):
    for s in (streams or LIVE):
        live = os.path.join(COMMON, LIVE[s])
        if not os.path.exists(live):
            print(f"  {s}: live DB missing ({LIVE[s]}) - skip"); continue
        last = latest_version(s)
        if last and md5(last) == md5(live):
            print(f"  {s}: unchanged since {os.path.basename(last)} - skip"); continue
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(VERDIR, f"{LIVE[s]}.{ts}.csv")
        shutil.copy2(live, dst)
        print(f"  {s}: snapshot -> {os.path.basename(dst)} ({os.path.getsize(dst)} b)")

def promote(stream):
    if stream not in RESEARCH:
        print(f"no research DB defined for '{stream}'"); return
    res = RESEARCH[stream]
    if not os.path.exists(res):
        print(f"research DB not found: {res} (run gridstat_shadow_refresh.py first)"); return
    snapshot([stream])                                  # always version before overwrite
    live = os.path.join(COMMON, LIVE[stream])
    shutil.copy2(res, live)
    print(f"PROMOTED {stream}: {os.path.basename(res)} -> live {LIVE[stream]}")
    print("  (roll back with: python gridstat_db_version.py rollback " + stream + ")")

def rollback(stream, ts=None):
    if ts:
        src = os.path.join(VERDIR, f"{LIVE[stream]}.{ts}.csv")
    else:
        src = latest_version(stream)
    if not src or not os.path.exists(src):
        print(f"no version found for {stream}" + (f" @ {ts}" if ts else "")); return
    live = os.path.join(COMMON, LIVE[stream])
    # version the CURRENT (about-to-be-replaced) live first, so rollback is itself reversible
    cur_md5 = md5(live); lv = latest_version(stream)
    if not (lv and md5(lv) == cur_md5):
        snapshot([stream])
    shutil.copy2(src, live)
    print(f"ROLLED BACK {stream}: {os.path.basename(src)} -> live {LIVE[stream]}")

def listv(stream=None):
    for s in ([stream] if stream else LIVE):
        vs = sorted(glob.glob(os.path.join(VERDIR, f"{LIVE[s]}.*.csv")))
        live = os.path.join(COMMON, LIVE[s])
        cur = md5(live)
        print(f"{s} ({LIVE[s]}) - {len(vs)} version(s):")
        for v in vs:
            tag = "  <- matches LIVE now" if md5(v) == cur else ""
            print(f"   {os.path.basename(v)[len(LIVE[s])+1:-4]}  ({os.path.getsize(v)} b){tag}")
        if not vs: print("   (none yet - run snapshot)")

def main():
    a = sys.argv[1:]
    if not a or a[0] == "list":
        listv(a[1] if len(a) > 1 else None)
    elif a[0] == "snapshot":
        print("SNAPSHOT:"); snapshot()
    elif a[0] == "promote" and len(a) > 1:
        promote(a[1])
    elif a[0] == "rollback" and len(a) > 1:
        rollback(a[1], a[2] if len(a) > 2 else None)
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
