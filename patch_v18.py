path = r'C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Marius Hedger v1.0.mq4'
with open(path, 'rb') as f:
    raw = f.read()
text = raw[2:].decode('utf-16-le')

# ── 1. Version block ──────────────────────────────────────────────────
old_ver = '// | v1.7  2026-05-15  lastEntryBar to global scope; guard locks bar before basket check; error 130 stop-level fix |'
new_ver = ('// | v1.8  2026-05-15  Error 130: skip (not clamp) when pending price too close to market; hedge guard in ManageTrailingPendingOrders |\r\n'
           '// | v1.7  2026-05-15  lastEntryBar to global scope; guard locks bar before basket check; error 130 stop-level fix |')
assert text.count(old_ver) == 1, f'ver: {text.count(old_ver)}'
text = text.replace(old_ver, new_ver)

# ── 2. Fix ManageSinglePendingOrder: SKIP on stop-level violation (both OrderSend and OrderModify paths)
# OrderSend path: replace clamp-and-create with skip
OLD_SEND = (
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
NEW_SEND = (
    '    // Skip if pending price violates broker stop level -- price will be valid on a future tick\r\n'
    '    double stopsLevel = MarketInfo(Symbol(), MODE_STOPLEVEL) * MarketInfo(Symbol(), MODE_POINT);\r\n'
    '    if (orderType == OP_SELLSTOP && pendingPrice >= NormalizeDouble(Bid - stopsLevel, Digits))\r\n'
    '    {\r\n'
    '        Print("[StopLevel] SELL STOP price ", DoubleToString(pendingPrice, Digits),\r\n'
    '              " too close to Bid ", DoubleToString(Bid, Digits), " -- skipping this tick");\r\n'
    '        return;\r\n'
    '    }\r\n'
    '    if (orderType == OP_BUYSTOP && pendingPrice <= NormalizeDouble(Ask + stopsLevel, Digits))\r\n'
    '    {\r\n'
    '        Print("[StopLevel] BUY STOP price ", DoubleToString(pendingPrice, Digits),\r\n'
    '              " too close to Ask ", DoubleToString(Ask, Digits), " -- skipping this tick");\r\n'
    '        return;\r\n'
    '    }\r\n'
    '\r\n'
    '    int ticket = OrderSend(Symbol(), orderType, lotSize, pendingPrice, 3, 0, 0, CommentText, MagicNumber, 0, clrYellow);'
)
c2 = text.count(OLD_SEND)
print(f'OrderSend block occurrences: {c2}')
assert c2 == 1
text = text.replace(OLD_SEND, NEW_SEND)

# OrderModify path: replace clamp-and-modify with skip-modify
OLD_MODIFY = (
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
NEW_MODIFY = (
    '            if (fabs(OrderOpenPrice() - pendingPrice) > Point)\r\n'
    '            {\r\n'
    '                // Skip modify if new price would violate broker stop level\r\n'
    '                double sl2 = MarketInfo(Symbol(), MODE_STOPLEVEL) * MarketInfo(Symbol(), MODE_POINT);\r\n'
    '                if (orderType == OP_SELLSTOP && pendingPrice >= NormalizeDouble(Bid - sl2, Digits))\r\n'
    '                {\r\n'
    '                    Print("[StopLevel] Skipping OrderModify -- SELL STOP price too close to Bid");\r\n'
    '                    return;\r\n'
    '                }\r\n'
    '                if (orderType == OP_BUYSTOP && pendingPrice <= NormalizeDouble(Ask + sl2, Digits))\r\n'
    '                {\r\n'
    '                    Print("[StopLevel] Skipping OrderModify -- BUY STOP price too close to Ask");\r\n'
    '                    return;\r\n'
    '                }\r\n'
    '                if (!OrderModify(OrderTicket(), pendingPrice, 0, 0, 0, clrYellow))\r\n'
    '                {\r\n'
    '                    Print("Failed to update trailing pending order. Ticket: ", OrderTicket(), " Error: ", GetLastError());\r\n'
    '                }'
)
c3 = text.count(OLD_MODIFY)
print(f'OrderModify block occurrences: {c3}')
assert c3 == 1
text = text.replace(OLD_MODIFY, NEW_MODIFY)

# ── 3. Guard ManageTrailingPendingOrders: skip when both BUY and SELL market positions are already open
# (hedge has already triggered — no new pending needed until one side closes)
OLD_TRAIL = (
    '    for (int i = 0; i < OrdersTotal(); i++) {\r\n'
    '        if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && OrderMagicNumber() == MagicNumber) {\r\n'
    '            if (OrderType() == OP_BUY || OrderType() == OP_SELL) {\r\n'
    '                double entryPrice = OrderOpenPrice();\r\n'
    '                double pendingPrice, breakevenPrice;\r\n'
    '\r\n'
    '                if (OrderType() == OP_BUY) {\r\n'
    '                    pendingPrice = NormalizeDouble(stepMAValue - PendingTrail * Point, Digits);\r\n'
    '                    breakevenPrice = entryPrice + PipsInProfit * Point;\r\n'
    '                    ManageSinglePendingOrder(OP_SELLSTOP, pendingPrice, breakevenPrice);\r\n'
    '                } else if (OrderType() == OP_SELL) {\r\n'
    '                    pendingPrice = NormalizeDouble(stepMAValue + PendingTrail * Point, Digits);\r\n'
    '                    breakevenPrice = entryPrice - PipsInProfit * Point;\r\n'
    '                    ManageSinglePendingOrder(OP_BUYSTOP, pendingPrice, breakevenPrice);\r\n'
    '                }\r\n'
    '            }\r\n'
    '        }\r\n'
    '    }\r\n'
    '}'
)
NEW_TRAIL = (
    '    // Do not place new hedging pending orders when both sides are already open as market positions\r\n'
    '    // (the pending hedge has already triggered -- wait for one side to close first)\r\n'
    '    bool bothOpen = false;\r\n'
    '    {\r\n'
    '        bool hasBuy = false, hasSell = false;\r\n'
    '        for (int j = 0; j < OrdersTotal(); j++)\r\n'
    '        {\r\n'
    '            if (!OrderSelect(j, SELECT_BY_POS, MODE_TRADES)) continue;\r\n'
    '            if (OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;\r\n'
    '            if (OrderType() == OP_BUY)  hasBuy  = true;\r\n'
    '            if (OrderType() == OP_SELL) hasSell = true;\r\n'
    '        }\r\n'
    '        bothOpen = (hasBuy && hasSell);\r\n'
    '    }\r\n'
    '    if (bothOpen)\r\n'
    '    {\r\n'
    '        Print("[TrailGuard] Both BUY and SELL market positions open -- skipping pending order management");\r\n'
    '        return;\r\n'
    '    }\r\n'
    '\r\n'
    '    for (int i = 0; i < OrdersTotal(); i++) {\r\n'
    '        if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && OrderMagicNumber() == MagicNumber) {\r\n'
    '            if (OrderType() == OP_BUY || OrderType() == OP_SELL) {\r\n'
    '                double entryPrice = OrderOpenPrice();\r\n'
    '                double pendingPrice, breakevenPrice;\r\n'
    '\r\n'
    '                if (OrderType() == OP_BUY) {\r\n'
    '                    pendingPrice = NormalizeDouble(stepMAValue - PendingTrail * Point, Digits);\r\n'
    '                    breakevenPrice = entryPrice + PipsInProfit * Point;\r\n'
    '                    ManageSinglePendingOrder(OP_SELLSTOP, pendingPrice, breakevenPrice);\r\n'
    '                } else if (OrderType() == OP_SELL) {\r\n'
    '                    pendingPrice = NormalizeDouble(stepMAValue + PendingTrail * Point, Digits);\r\n'
    '                    breakevenPrice = entryPrice - PipsInProfit * Point;\r\n'
    '                    ManageSinglePendingOrder(OP_BUYSTOP, pendingPrice, breakevenPrice);\r\n'
    '                }\r\n'
    '            }\r\n'
    '        }\r\n'
    '    }\r\n'
    '}'
)
c4 = text.count(OLD_TRAIL)
print(f'TrailingPendingOrders loop occurrences: {c4}')
assert c4 == 1
text = text.replace(OLD_TRAIL, NEW_TRAIL)

# ── 4. Verify ──────────────────────────────────────────────────────────
print('\nVerification:')
print('  v1.8:', text.count('v1.8'))
print('  skip this tick (SELL STOP):', text.count('skipping this tick'))
print('  Skipping OrderModify:', text.count('Skipping OrderModify'))
print('  TrailGuard:', text.count('[TrailGuard]'))
print('  bothOpen:', text.count('bothOpen'))
print('  clamp (should be 0):', text.count('Clamp to broker'))
print('  adjusted to (should be 0):', text.count('adjusted to'))
print('  File chars:', len(text))

new_raw = b'\xff\xfe' + text.encode('utf-16-le')
with open(path, 'wb') as f:
    f.write(new_raw)
print('Written:', len(new_raw), 'bytes')
