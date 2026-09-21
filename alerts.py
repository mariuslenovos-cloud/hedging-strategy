#!/usr/bin/env python3
"""
ALERTS (gap #2, 2026-08-08) — one dispatch point for every red event.

Channels, in order:
  1. analysis_data/alerts.log                    (always — the audit trail)
  2. Windows toast notification                  (always — visible on this PC)
  3. Telegram push to your phone                 (optional — fill analysis_data/alert_config.json:
                                                  {"telegram_bot_token": "...", "telegram_chat_id": "..."})
  4. (MT5 phone push comes from the Book Guard EA's SendNotification — set your MetaQuotes ID in
     the terminal: Tools -> Options -> Notifications.)

Use:  from alerts import alert;  alert("GOLD outside envelope", level="RED")
Test: python alerts.py "test message"
"""
import os, io, json, subprocess, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ADIR = os.path.join(HERE, "analysis_data")
CFG = os.path.join(ADIR, "alert_config.json")
LOG = os.path.join(ADIR, "alerts.log")


def _toast(title, msg):
    ps = r'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $x.GetElementsByTagName("text")
$t.Item(0).AppendChild($x.CreateTextNode($env:TT_TITLE)) | Out-Null
$t.Item(1).AppendChild($x.CreateTextNode($env:TT_MSG)) | Out-Null
$n = [Windows.UI.Notifications.ToastNotification]::new($x)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("GridStat").Show($n)
'''
    env = dict(os.environ, TT_TITLE=title, TT_MSG=msg[:180])
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env,
                       timeout=20, capture_output=True)
    except Exception:
        pass


def _telegram(msg):
    try:
        cfg = json.load(open(CFG))
        tok, chat = cfg.get("telegram_bot_token"), cfg.get("telegram_chat_id")
        if not tok or not chat: return
        import urllib.request, urllib.parse
        url = f"https://api.telegram.org/bot{tok}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass


def alert(msg, level="RED", title=None, telegram=None):
    """Dispatch an alert everywhere. level: RED (act now) / AMBER (heads-up) / INFO.
    telegram: None = auto (RED only) · True = force phone push (e.g. the daily brief)."""
    os.makedirs(ADIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp} [{level}] {msg}"
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    _toast(title or f"GridStat {level}", msg)
    if telegram is True or (telegram is None and level == "RED"):
        _telegram(f"[{level}] {msg}")
    print("ALERT:", line, flush=True)


if __name__ == "__main__":
    alert(" ".join(sys.argv[1:]) or "alerts.py test — channels working", level="RED")
