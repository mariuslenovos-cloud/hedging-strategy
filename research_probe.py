"""research_probe.py -- the standing RESEARCH PROBE (2026-10-11, user: "put a process in place to probe" the shelved items).
Every research item the project shelved, killed or left open lives in analysis_data/research_registry.csv with the reason it
stopped and the CONDITION under which it is worth re-probing (capital reached, a sample size reached, a date, an event).
`python research_probe.py` prints the items whose trigger is met or whose cadence is overdue; the Monday brief runs it.
A killed item is never silently dead: it carries a cheap probe command and comes back on the board when its trigger fires.
Status vocabulary: open (not yet run) / watch (running, judged on a clock or sample) / shelved (waits on capital or venue) / killed (edge absent; re-probed on cadence only)."""
import io, os, sys, csv
from datetime import datetime, timedelta
HERE = os.path.dirname(os.path.abspath(__file__)); REG = os.path.join(HERE, "analysis_data", "research_registry.csv")


def main_balance():
    try:
        import MetaTrader5 as mt5, time
        for _ in range(4):
            mt5.shutdown()
            if mt5.initialize(path=r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe"):
                ai = mt5.account_info()
                if ai and ai.login == 51511633:
                    b = ai.balance; mt5.shutdown(); return b
            time.sleep(1)
    except Exception:
        pass
    return None


def ledger_counts():
    out = {}
    try:
        import pandas as pd
        led = pd.read_csv(os.path.join(HERE, "analysis_data", "episode_ledger.csv"))
        out["LIVE oil episodes"] = int(((led.account == "LIVE") & led.stream.str.contains("oil", case=False)).sum())
        out["DEMO 56136 ladders"] = int(((led.account == "DEMO") & led.stream.str.contains("zgrid", case=False)).sum())
        out["DEMO longvol closes"] = int(((led.account == "DEMO") & led.stream.str.contains("longvol", case=False)).sum())
    except Exception:
        pass
    return out


def oil_review(since):
    """The oil review line (2026-10-12): fires only when BOTH (a) the two most recent weekly re-tests of OIL-SOLID@PEP dated
    after `since` are net-negative AND (b) MAIN's live oil realized net over the last 56 days (episode ledger, LIVE account
    only -- DEON is not the user's account) is negative. Returns a reason string when fired, else None (status printed)."""
    import pandas as pd
    try:
        rt = pd.read_csv(os.path.join(HERE, "analysis_data", "rolling_retest.csv"))
        o = rt[(rt.job == "OIL-SOLID@PEP") & (rt.date.astype(str).str[:10] > since)].tail(2)
        led = pd.read_csv(os.path.join(HERE, "analysis_data", "episode_ledger.csv"), parse_dates=["closed"])
        lv = led[(led.account == "LIVE") & (led.stream == "oil-SOLID") & (led.closed >= pd.Timestamp.now() - pd.Timedelta(days=56))]
        live = float(lv.realized_net.sum())
    except Exception as e:
        print(f"   oil_review: cannot evaluate ({e})"); return None
    nets = [float(x) for x in o.net]
    a = len(nets) == 2 and all(x < 0 for x in nets); b = live < 0
    state = f"re-tests after {since}: {nets if nets else 'none yet'} | MAIN live oil 56d {live:+.2f} ({len(lv)} eps)"
    print(f"   oil_review: {state} -> {'FIRED' if (a and b) else 'not fired'}")
    return f"oil review line FIRED ({state})" if (a and b) else None


def due(rows, bal, counts, today):
    out = []
    for r in rows:
        kind, val, why = r["trigger_kind"], r["trigger_value"].strip(), None
        if kind == "capital":
            try:
                if bal is not None and bal >= float(val): why = f"capital trigger met (MAIN ${bal:,.0f} >= {val})"
            except ValueError:
                pass
        elif kind == "sample":
            for k, n in counts.items():
                if val.startswith(k):
                    try:
                        need = int(val.split(">=")[1])
                        if n >= need: why = f"sample trigger met ({k} {n} >= {need})"
                    except Exception:
                        pass
        elif kind == "script":            # the row's own probe command decides: exit 0 = condition met
            try:
                import subprocess, shlex
                cp = subprocess.run(r["probe"].split(), capture_output=True, text=True, timeout=300, cwd=os.path.dirname(os.path.abspath(__file__)))
                if cp.returncode == 0: why = "script trigger met: " + (cp.stdout.strip().splitlines() or [""])[-1][:160]
            except Exception as e:
                why = f"script trigger ERROR ({e})"
        elif kind == "oil_review":
            why = oil_review(val)
        elif kind == "date":
            if val.count("-") == 2:
                try:
                    if today >= datetime.strptime(val, "%Y-%m-%d").date(): why = f"date reached ({val})"
                except ValueError:
                    pass
            elif val in ("0", "") and not r["last_probed"]:
                why = "never run"
        if why is None and r["last_probed"] and r["cadence_days"] not in ("", "0"):
            try:
                if today >= datetime.strptime(r["last_probed"], "%Y-%m-%d").date() + timedelta(days=int(r["cadence_days"])):
                    why = f"cadence overdue ({r['cadence_days']}d since {r['last_probed']})"
            except ValueError:
                pass
        if why: out.append((r, why))
    return out


def main(brief=None, with_balance=True):
    rows = list(csv.DictReader(io.open(REG, encoding="utf-8")))
    bal = main_balance() if with_balance else None
    counts = ledger_counts(); today = datetime.now().date()
    head = f"RESEARCH PROBE {today}: {len(rows)} items on the board"
    head += f" (MAIN ${bal:,.0f}; " if bal else " (MAIN balance unavailable; "
    head += ", ".join(f"{k} {v}" for k, v in counts.items()) + ")"
    lines = [head]
    d = due(rows, bal, counts, today)
    if not d:
        lines.append("   nothing due -- every shelved item is waiting on its trigger")
    for r, why in d:
        lines.append(f"   DUE  {r['id']:<14}[{r['status']}] {r['item']}")
        lines.append(f"        why: {why}")
        lines.append(f"        probe: {r['probe']}")
        lines.append(f"        if it passes: {r['next_action_if_pass']}")
    by = {}
    for r in rows: by.setdefault(r["status"], []).append(r["id"])
    lines.append("   board: " + " | ".join(f"{k}: {', '.join(v)}" for k, v in sorted(by.items())))
    txt = "\n".join(lines); print(txt)
    if brief is not None: brief.extend(lines)
    return d


if __name__ == "__main__":
    main(with_balance="--no-balance" not in sys.argv)
