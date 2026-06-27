path = r'C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Marius Hedger v1.0.mq4'
with open(path, 'rb') as f:
    raw = f.read()
text = raw[2:].decode('utf-16-le')

# ── 1. Version block ──────────────────────────────────────────────────
old_ver = '// | v1.6  2026-05-15  Per-bar entry guard'
new_ver = ('// | v1.7  2026-05-15  lastEntryBar to global scope; guard locks bar before basket check; error 130 stop-level fix |\r\n'
           '// | v1.6  2026-05-15  Per-bar entry guard')
assert text.count(old_ver) == 1, f'ver: {text.count(old_ver)}'
text = text.replace(old_ver, new_ver)

# ── 2. Add lastEntryBar as global variable (next to lastCandleTime) ────
OLD_GLOBAL = 'datetime lastCandleTime = 0; // Tracks the time of the last'
NEW_GLOBAL = ('datetime lastCandleTime = 0; // Tracks the time of the last\r\n'
              'datetime lastEntryBar   = 0; // Tracks the bar on which the last entry was opened (per-bar guard)')
assert text.count(OLD_GLOBAL) == 1
text = text.replace(OLD_GLOBAL, NEW_GLOBAL)

# ── 3. Remove static declaration inside the guard, lock bar FIRST ────
OLD_GUARD = (
    '        // One entry per bar only -- prevents tick-level position stacking\r\n'
    '        static datetime lastEntryBar = 0;\r\n'
    '        if (iTime(Symbol(), PERIOD_CURRENT, 0) != lastEntryBar)\r\n'
    '        {\r\n'
    '            int basketSize = CountBasketPositions();\r\n'
    '            if (MaxBasketPositions > 0 && basketSize >= MaxBasketPositions)\r\n'
    '                Print("[Guard] Basket full (", basketSize, "/", MaxBasketPositions, ") -- skipping entry");\r\n'
    '            else\r\n'
    '            {\r\n'
    '                lastEntryBar = iTime(Symbol(), PERIOD_CURRENT, 0);\r\n'
    '                if (buySignal && !IsPositionOpen(OP_BUY)) {\r\n'
    '                    OpenBuyTrade();\r\n'
    '                }\r\n'
    '                if (sellSignal && !IsPositionOpen(OP_SELL)) {\r\n'
    '                    OpenSellTrade();\r\n'
    '                }\r\n'
    '            }\r\n'
    '        }'
)
NEW_GUARD = (
    '        // One entry per bar only -- global lastEntryBar prevents tick-level stacking\r\n'
    '        datetime thisBar = iTime(Symbol(), PERIOD_CURRENT, 0);\r\n'
    '        if (thisBar != lastEntryBar)\r\n'
    '        {\r\n'
    '            lastEntryBar = thisBar; // lock this bar immediately, before any trade\r\n'
    '            int basketSize = CountBasketPositions();\r\n'
    '            if (MaxBasketPositions > 0 && basketSize >= MaxBasketPositions)\r\n'
    '                Print("[Guard] Basket full (", basketSize, "/", MaxBasketPositions, ") -- skipping entry");\r\n'
    '            else\r\n'
    '            {\r\n'
    '                if (buySignal && !IsPositionOpen(OP_BUY)) {\r\n'
    '                    OpenBuyTrade();\r\n'
    '                }\r\n'
    '                if (sellSignal && !IsPositionOpen(OP_SELL)) {\r\n'
    '                    OpenSellTrade();\r\n'
    '                }\r\n'
    '            }\r\n'
    '        }'
)
c = text.count(OLD_GUARD)
print(f'Guard block occurrences: {c}')
assert c == 1
text = text.replace(OLD_GUARD, NEW_GUARD)

# ── 4. Error 130 — validate stop level before OrderSend in ManageSinglePendingOrder ──
OLD_SEND = (
    '    // Create a new pending order if none exists\r\n'
    '    double lotSize = DoublePendingLot ? 2 * LotSize : LotSize;\r\n'
    '    lotSize = GetValidLotSize(lotSize);\r\n'
    '    int ticket = OrderSend(Symbol(), orderType, lotSize, pendingPrice, 3, 0, 0, CommentText, MagicNumber, 0, clrYellow);'
)
NEW_SEND = (
    '    // Create a new pending order if none exists\r\n'
    '    double lotSize = DoublePendingLot ? 2 * LotSize : LotSize;\r\n'
    '    lotSize = GetValidLotSize(lotSize);\r\n'
    '\r\n'
    '    // Validate that pending price respects broker minimum stop level (error 130 prevention)\r\n'
    '    double stopsLevel = MarketInfo(Symbol(), MODE_STOPLEVEL) * MarketInfo(Symbol(), MODE_POINT);\r\n'
    '    if (orderType == OP_SELLSTOP)\r\n'
    '    {\r\n'
    '        double maxAllowed = NormalizeDouble(Bid - stopsLevel, Digits);\r\n'
    '        if (pendingPrice > maxAllowed)\r\n'
    '        {\r\n'
    '            pendingPrice = NormalizeDouble(maxAllowed - MarketInfo(Symbol(), MODE_POINT), Digits);\r\n'
    '            Print("[StopLevel] SELL STOP adjusted to ", DoubleToString(pendingPrice, Digits), " (was above min stop distance)");\r\n'
    '        }\r\n'
    '    }\r\n'
    '    else if (orderType == OP_BUYSTOP)\r\n'
    '    {\r\n'
    '        double minAllowed = NormalizeDouble(Ask + stopsLevel, Digits);\r\n'
    '        if (pendingPrice < minAllowed)\r\n'
    '        {\r\n'
    '            pendingPrice = NormalizeDouble(minAllowed + MarketInfo(Symbol(), MODE_POINT), Digits);\r\n'
    '            Print("[StopLevel] BUY STOP adjusted to ", DoubleToString(pendingPrice, Digits), " (was below min stop distance)");\r\n'
    '        }\r\n'
    '    }\r\n'
    '\r\n'
    '    int ticket = OrderSend(Symbol(), orderType, lotSize, pendingPrice, 3, 0, 0, CommentText, MagicNumber, 0, clrYellow);'
)
c2 = text.count(OLD_SEND)
print(f'OrderSend block occurrences: {c2}')
assert c2 == 1
text = text.replace(OLD_SEND, NEW_SEND)

# ── 5. Also validate in the OrderModify (move existing pending) path ──
# Include the outer fabs() wrapper to make the search string unique
OLD_MODIFY = (
    '            if (fabs(OrderOpenPrice() - pendingPrice) > Point)\r\n'
    '            {\r\n'
    '                if (!OrderModify(OrderTicket(), pendingPrice, 0, 0, 0, clrYellow))\r\n'
    '                {\r\n'
    '                    Print("Failed to update trailing pending order. Ticket: ", OrderTicket(), " Error: ", GetLastError());\r\n'
    '                }'
)
NEW_MODIFY = (
    '            if (fabs(OrderOpenPrice() - pendingPrice) > Point)\r\n'
    '            {\r\n'
    '                // Clamp to broker stop level before modifying\r\n'
    '                double sl2 = MarketInfo(Symbol(), MODE_STOPLEVEL) * MarketInfo(Symbol(), MODE_POINT);\r\n'
    '                if (orderType == OP_SELLSTOP && pendingPrice > NormalizeDouble(Bid - sl2, Digits))\r\n'
    '                    pendingPrice = NormalizeDouble(Bid - sl2 - MarketInfo(Symbol(), MODE_POINT), Digits);\r\n'
    '                else if (orderType == OP_BUYSTOP && pendingPrice < NormalizeDouble(Ask + sl2, Digits))\r\n'
    '                    pendingPrice = NormalizeDouble(Ask + sl2 + MarketInfo(Symbol(), MODE_POINT), Digits);\r\n'
    '                if (!OrderModify(OrderTicket(), pendingPrice, 0, 0, 0, clrYellow))\r\n'
    '                {\r\n'
    '                    Print("Failed to update trailing pending order. Ticket: ", OrderTicket(), " Error: ", GetLastError());\r\n'
    '                }'
)
c3 = text.count(OLD_MODIFY)
print(f'OrderModify block occurrences: {c3}')
assert c3 == 1
text = text.replace(OLD_MODIFY, NEW_MODIFY)

# ── 6. Verify ──────────────────────────────────────────────────────────
print('\nVerification:')
print('  v1.7:', text.count('v1.7'))
print('  lastEntryBar global:', text.count('datetime lastEntryBar   = 0;'))
print('  static datetime lastEntryBar:', text.count('static datetime lastEntryBar'))  # should be 0
print('  thisBar != lastEntryBar:', text.count('thisBar != lastEntryBar'))
print('  lastEntryBar = thisBar:', text.count('lastEntryBar = thisBar'))
print('  StopLevel adjustment (new):', text.count('[StopLevel]'))
print('  MODE_STOPLEVEL uses:', text.count('MODE_STOPLEVEL'))
print('  File chars:', len(text))

new_raw = b'\xff\xfe' + text.encode('utf-16-le')
with open(path, 'wb') as f:
    f.write(new_raw)
print('Written:', len(new_raw), 'bytes')
