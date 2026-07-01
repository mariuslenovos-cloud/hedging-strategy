#!/usr/bin/env python3
"""
Port MaxConcurrentBaskets + UseEntrySL into the Pepperstone MT4 'Marius GridStat OIL v1.0.mq4'
(faithful MQL4 translation of the MT5 S11 concurrency design). DEFAULT MaxConcurrentBaskets=1 =>
single-pool logic byte-identical to the current EA (gold/silver untouched). Oil sets it to 3.
Each basket tagged with '.B<id>' in its comment; ManageGrid becomes a per-basket dispatcher + a
portfolio catastrophe floor. UseEntrySL=false drops the per-entry stop (oil wants SL-off).
"""
import io, sys
PATH=r"C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\3294B546D50FEEDA6BF3CFC7CF858DB7\MQL4\Experts\Marius GridStat OIL v1.0.mq4"
raw=open(PATH,"rb").read()
# detect encoding
if raw[:2] in (b"\xff\xfe", b"\xfe\xff"): enc="utf-16"
elif raw[:3]==b"\xef\xbb\xbf": enc="utf-8-sig"
else: enc="utf-8"
s=raw.decode(enc, errors="strict")
if "MaxConcurrentBaskets" in s: print("ALREADY PATCHED"); sys.exit(1)
crlf="\r\n" in s; s=s.replace("\r\n","\n")

def rep(a,b,n=1):
    c=s.count(a); assert c==n, f"count {c}!={n}: {a[:70]!r}"
    return s.replace(a,b)

# 0. build tag + print label
s=rep('#define EA_BUILD_VERSION "2026-06-05-P"','#define EA_BUILD_VERSION "2026-07-01-P-MT4CONC"')
s=rep('Print("MARIUS GRIDSTAT GOLD ", EA_BUILD_VERSION, " | Magic=", MagicNumber);',
      'Print("MARIUS GRIDSTAT OIL ", EA_BUILD_VERSION, " | Magic=", MagicNumber, " | maxBaskets=", MaxConcurrentBaskets, " UseEntrySL=", UseEntrySL);')

# 1. INPUTS (after BasketMaxLossPct)
s=rep('input double BasketMaxLossPct      = 20.0;     // % of account balance — hard per-basket loss cap',
      'input double BasketMaxLossPct      = 20.0;     // % of account balance — hard per-basket loss cap\n'
      'input int    MaxConcurrentBaskets  = 1;        // [MT4-CONC] 1 = single basket (unchanged). >1 = N concurrent baskets, each grid-managed + a portfolio floor (oil/trenders need 3).\n'
      'input bool   UseEntrySL            = true;     // [MT4-CONC] true = per-entry hard SL (unchanged). false = no per-entry stop, rely on the basket floor (oil pulls back -> SL-off lets the grid recover).')

# 2. GLOBAL (after MagicNumber decl)
s=rep('int      MagicNumber = 0;','int      MagicNumber = 0;\nint      g_curBasketId = -1;   // [MT4-CONC]')

# 3. HELPER FUNCTIONS (before BasketLotCount)
helpers = '''//+------------------------------------------------------------------+
//| [MT4-CONC] multi-basket helpers (default maxBaskets<=1 => no-op)   |
//+------------------------------------------------------------------+
string BTag(int id) { return (MaxConcurrentBaskets > 1) ? (".B" + IntegerToString(id)) : ""; }
int BIdOf(string cmt) {
    int p = StringFind(cmt, ".B");
    if (p < 0) return -1;
    return (int)StringToInteger(StringSubstr(cmt, p + 2));
}
int CollectBaskets(int &ids[]) {
    ArrayResize(ids, 0);
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        int bid = BIdOf(OrderComment()); bool have = false;
        for (int k = 0; k < ArraySize(ids); k++) if (ids[k] == bid) { have = true; break; }
        if (!have) { int n = ArraySize(ids); ArrayResize(ids, n+1); ids[n] = bid; }
    }
    return ArraySize(ids);
}
int CountOpenBaskets() { int ids[]; return CollectBaskets(ids); }
int NextBasketId() {
    if (MaxConcurrentBaskets <= 1) return -1;
    int maxId = -1;
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        int bid = BIdOf(OrderComment()); if (bid > maxId) maxId = bid;
    }
    return maxId + 1;
}
double PortfolioFloat() {
    double f = 0;
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        f += OrderProfit() + OrderSwap() + OrderCommission();
    }
    return f;
}
void CloseBasket(int bid, string reason) {
    if (bid == -1) { CloseAllBasket(reason); return; }   // single-pool: close everything
    Print("CloseBasket ", bid, ": ", reason);
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        if (BIdOf(OrderComment()) != bid) continue;
        double cp = (OrderType() == OP_BUY) ? MarketInfo(Symbol(), MODE_BID) : MarketInfo(Symbol(), MODE_ASK);
        OrderClose(OrderTicket(), OrderLots(), cp, 3, clrYellow);
    }
}

int BasketLotCount() {'''
s=rep('int BasketLotCount() {', helpers)

# 4. ENTRY GATE
s=rep('    if (BasketLotCount() > 0) return;',
      '    if (CountOpenBaskets() >= MaxConcurrentBaskets) return;   // [MT4-CONC] basket-concurrency cap')

# 5. OpenSimpleSLTP: UseEntrySL + new basket id + tag
s=rep('    if (UseTrailingExit) tp = 0;   // trailing basket exit manages the profit side (let winners run)\n'
      '    int t = OrderSend(Symbol(), dir, lot, price, 3, sl, tp, CommentText + "_SLTP", MagicNumber, 0,',
      '    if (UseTrailingExit) tp = 0;   // trailing basket exit manages the profit side (let winners run)\n'
      '    if (!UseEntrySL) sl = 0;                                   // [MT4-CONC] no per-entry stop\n'
      '    int bid = NextBasketId();                                  // [MT4-CONC] fresh basket id (-1 in single mode)\n'
      '    int t = OrderSend(Symbol(), dir, lot, price, 3, sl, tp, CommentText + "_SLTP" + BTag(bid), MagicNumber, 0,')

# 6. OpenGridLevel + OpenHedge: add bid param + tag
s=rep('bool OpenGridLevel(int dir, double lot, int gridLvl) {\n'
      '    double price = (dir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);\n'
      '    string cmt = CommentText + "_L" + IntegerToString(gridLvl);',
      'bool OpenGridLevel(int dir, double lot, int gridLvl, int bid) {\n'
      '    double price = (dir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);\n'
      '    string cmt = CommentText + "_L" + IntegerToString(gridLvl) + BTag(bid);')
s=rep('bool OpenHedge(int hedgeDir, double lot) {\n'
      '    double price = (hedgeDir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);\n'
      '    int t = OrderSend(Symbol(), hedgeDir, lot, price, 3, 0, 0, CommentText + "_HEDGE", MagicNumber, 0, clrMagenta);',
      'bool OpenHedge(int hedgeDir, double lot, int bid) {\n'
      '    double price = (hedgeDir == OP_BUY) ? MarketInfo(Symbol(), MODE_ASK) : MarketInfo(Symbol(), MODE_BID);\n'
      '    int t = OrderSend(Symbol(), hedgeDir, lot, price, 3, 0, 0, CommentText + "_HEDGE" + BTag(bid), MagicNumber, 0, clrMagenta);')

# 7. ManageGrid -> ManageOneBasket(int bid), add per-basket filters, per-basket closes, thread bid
s=rep('void ManageGrid() {\n    int nLevels = 0;', 'void ManageOneBasket(int bid) {\n    int nLevels = 0;')
s=rep('        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;\n        string cmt = OrderComment();',
      '        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;\n'
      '        if (bid != -1 && BIdOf(OrderComment()) != bid) continue;   // [MT4-CONC] this basket only\n'
      '        string cmt = OrderComment();')
s=rep('                if (StringFind(OrderComment(), "_HEDGE") >= 0) continue;\n'
      '                if (initialDir == OP_BUY  && OrderOpenPrice() < extremeEntry) extremeEntry = OrderOpenPrice();',
      '                if (StringFind(OrderComment(), "_HEDGE") >= 0) continue;\n'
      '                if (bid != -1 && BIdOf(OrderComment()) != bid) continue;   // [MT4-CONC]\n'
      '                if (initialDir == OP_BUY  && OrderOpenPrice() < extremeEntry) extremeEntry = OrderOpenPrice();')
# per-basket closes (5) + open calls (2)
s=rep('CloseAllBasket("BASKET STOP " + DoubleToString(combinedFloat,2) + " <= " + DoubleToString(maxLoss,2));',
      'CloseBasket(bid, "BASKET STOP " + DoubleToString(combinedFloat,2) + " <= " + DoubleToString(maxLoss,2));')
s=rep('CloseAllBasket("grid recovery escape +" + DoubleToString(combinedFloat,2));',
      'CloseBasket(bid, "grid recovery escape +" + DoubleToString(combinedFloat,2));')
s=rep('CloseAllBasket("trail exit @R=" + DoubleToString(combinedFloat / oneR, 2));',
      'CloseBasket(bid, "trail exit @R=" + DoubleToString(combinedFloat / oneR, 2));')
s=rep('CloseAllBasket("profit target " + DoubleToString(combinedFloat,2)); return; }',
      'CloseBasket(bid, "profit target " + DoubleToString(combinedFloat,2)); return; }')
s=rep('CloseAllBasket("max days"); return; }','CloseBasket(bid, "max days"); return; }')
s=rep('OpenGridLevel(initialDir, newLot, nLevels + 1);','OpenGridLevel(initialDir, newLot, nLevels + 1, bid);')
s=rep('OpenHedge(hedgeSide, hedgeSize);','OpenHedge(hedgeSide, hedgeSize, bid);')

# 8. NEW ManageGrid dispatcher (insert right before 'double GetGridSpacingPoints() {')
dispatch = '''void ManageGrid() {
    if (MaxConcurrentBaskets <= 1) { ManageOneBasket(-1); return; }   // single-pool = unchanged
    // [MT4-CONC] portfolio catastrophe floor: cap TOTAL float across all concurrent baskets
    if (UseBasketStop) {
        double pf = PortfolioFloat();
        if (pf <= -BasketMaxLossPct / 100.0 * AccountBalance()) { CloseAllBasket("PORTFOLIO STOP " + DoubleToString(pf,2)); return; }
    }
    int ids[]; int nb = CollectBaskets(ids);
    for (int k = 0; k < nb; k++) ManageOneBasket(ids[k]);
}

double GetGridSpacingPoints() {'''
s=rep('double GetGridSpacingPoints() {', dispatch)

if crlf: s=s.replace("\n","\r\n")
open(PATH,"wb").write(s.encode(enc if enc!="utf-8-sig" else "utf-8-sig"))
print(f"MT4 OIL CONCURRENCY PORT APPLIED ({enc}, {'CRLF' if crlf else 'LF'}).")
for t in ["MaxConcurrentBaskets","UseEntrySL","ManageOneBasket","BTag","CloseBasket","CountOpenBaskets","MT4CONC"]:
    print(f"  present: {t in s}   {t}")
