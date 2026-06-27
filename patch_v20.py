path = r'C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Marius Hedger v1.0.mq4'
with open(path, 'rb') as f:
    raw = f.read()
text = raw[2:].decode('utf-16-le')

# ── 1. Version block ──────────────────────────────────────────────────
old_ver = '// | v1.9  2026-05-15  Remove bothOpen guard -- skip-only logic is sufficient; BUY STOP now placed for triggered SELL leg |'
new_ver = ('// | v2.0  2026-05-15  Strategy optimisation: single-level hedge only; ATR hard SL; MaxBasket=2; HedgeProfit=150; MA angle=55; session filter |\r\n'
           '// | v1.9  2026-05-15  Remove bothOpen guard -- skip-only logic is sufficient; BUY STOP now placed for triggered SELL leg |')
assert text.count(old_ver) == 1
text = text.replace(old_ver, new_ver)

# ── 2. Input defaults ─────────────────────────────────────────────────
# MaxBasketPositions 5 → 2
old = 'input int    MaxBasketPositions    = 5;    // Max market positions open at once (0 = no limit) -- prevents position stacking'
new = 'input int    MaxBasketPositions    = 2;    // Max market positions open at once (0 = no limit) -- prevents position stacking'
assert text.count(old) == 1
text = text.replace(old, new)

# HedgeProfitThreshold 50 → 150
old = 'input double HedgeProfitThreshold = 50; // Profit level to liquidate hedge trades'
new = 'input double HedgeProfitThreshold = 150; // Profit level to liquidate hedge trades'
assert text.count(old) == 1
text = text.replace(old, new)

# MA_Angle_Threshold 45.0 → 55.0
old = 'input double MA_Angle_Threshold = 45.0; // Minimum MA angle in degrees 30'
new = 'input double MA_Angle_Threshold = 55.0; // Minimum MA angle in degrees -- raise to filter noise'
assert text.count(old) == 1
text = text.replace(old, new)

# DoublePendingLot true → false  +  add new inputs below it
old = ('input bool DoublePendingLot = true; // Control whether pending order lot size is doubled\r\n'
       '\r\n'
       '\r\n'
       '// Input parameters for trend activation')
new = ('input bool DoublePendingLot = false; // Control whether pending order lot size is doubled -- off by default (keeps hedge lot = primary lot)\r\n'
       'input bool UseATRStopLoss   = true;  // Place ATR-based hard stop loss on every new entry\r\n'
       'input int  SessionStartHour = 7;     // Broker server hour to start trading (7 = London open UTC)\r\n'
       'input int  SessionEndHour   = 22;    // Broker server hour to stop new entries (22 = after NY close UTC)\r\n'
       '\r\n'
       '\r\n'
       '// Input parameters for trend activation')
assert text.count(old) == 1
text = text.replace(old, new)

# ── 3. Session filter around buySignal/sellSignal ─────────────────────
old = ('        bool buySignal = (ggreen > 0);\r\n'
       '        bool sellSignal = (gred > 0);')
new = ('        // Session filter -- only allow new entries during configured broker-server hours\r\n'
       '        int  currentHour = TimeHour(TimeCurrent());\r\n'
       '        bool inSession   = (currentHour >= SessionStartHour && currentHour < SessionEndHour);\r\n'
       '        bool buySignal   = inSession && (ggreen > 0);\r\n'
       '        bool sellSignal  = inSession && (gred > 0);')
assert text.count(old) == 1
text = text.replace(old, new)

# ── 4. ATR hard SL in OpenBuyTrade ───────────────────────────────────
old = ('    // Place the buy order\r\n'
       '    int ticket = OrderSend(Symbol(), OP_BUY, lotSize, ask, 3, 0, 0, CommentText, MagicNumber, 0, Blue);')
new = ('    // Compute ATR-based hard stop loss\r\n'
       '    double atrBuy = iATR(Symbol(), PERIOD_CURRENT, ATRPeriod, 1);\r\n'
       '    double slBuy  = 0;\r\n'
       '    if (UseATRStopLoss && atrBuy > 0)\r\n'
       '    {\r\n'
       '        slBuy = NormalizeDouble(ask - ATRMultiplier * atrBuy, Digits);\r\n'
       '        double minDist = MarketInfo(Symbol(), MODE_STOPLEVEL) * MarketInfo(Symbol(), MODE_POINT);\r\n'
       '        if ((ask - slBuy) < minDist) slBuy = NormalizeDouble(ask - minDist - MarketInfo(Symbol(), MODE_POINT), Digits);\r\n'
       '    }\r\n'
       '\r\n'
       '    // Place the buy order\r\n'
       '    int ticket = OrderSend(Symbol(), OP_BUY, lotSize, ask, 3, slBuy, 0, CommentText, MagicNumber, 0, Blue);')
assert text.count(old) == 1
text = text.replace(old, new)

# ── 5. ATR hard SL in OpenSellTrade ──────────────────────────────────
old = ('    // Place the sell order\r\n'
       '    int ticket = OrderSend(Symbol(), OP_SELL, lotSize, bid, 3, 0, 0, CommentText, MagicNumber, 0, Red);')
new = ('    // Compute ATR-based hard stop loss\r\n'
       '    double atrSell = iATR(Symbol(), PERIOD_CURRENT, ATRPeriod, 1);\r\n'
       '    double slSell  = 0;\r\n'
       '    if (UseATRStopLoss && atrSell > 0)\r\n'
       '    {\r\n'
       '        slSell = NormalizeDouble(bid + ATRMultiplier * atrSell, Digits);\r\n'
       '        double minDist = MarketInfo(Symbol(), MODE_STOPLEVEL) * MarketInfo(Symbol(), MODE_POINT);\r\n'
       '        if ((slSell - bid) < minDist) slSell = NormalizeDouble(bid + minDist + MarketInfo(Symbol(), MODE_POINT), Digits);\r\n'
       '    }\r\n'
       '\r\n'
       '    // Place the sell order\r\n'
       '    int ticket = OrderSend(Symbol(), OP_SELL, lotSize, bid, 3, slSell, 0, CommentText, MagicNumber, 0, Red);')
assert text.count(old) == 1
text = text.replace(old, new)

# ── 6. Remove recursive hedge: strip OP_SELL arm from ManageTrailingPendingOrders ──
old = ('                } else if (OrderType() == OP_SELL) {\r\n'
       '                    pendingPrice = NormalizeDouble(stepMAValue + PendingTrail * Point, Digits);\r\n'
       '                    breakevenPrice = entryPrice - PipsInProfit * Point;\r\n'
       '                    ManageSinglePendingOrder(OP_BUYSTOP, pendingPrice, breakevenPrice);\r\n'
       '                }')
new = '                }'   # close the if (OrderType() == OP_BUY) block only
assert text.count(old) == 1
text = text.replace(old, new)

# ── 7. Verify ─────────────────────────────────────────────────────────
print('Verification:')
print('  v2.0:', text.count('v2.0'))
print('  MaxBasketPositions = 2:', text.count('MaxBasketPositions    = 2'))
print('  HedgeProfitThreshold = 150:', text.count('HedgeProfitThreshold = 150'))
print('  MA_Angle_Threshold = 55.0:', text.count('MA_Angle_Threshold = 55.0'))
print('  DoublePendingLot = false:', text.count('DoublePendingLot = false'))
print('  UseATRStopLoss input:', text.count('input bool UseATRStopLoss'))
print('  SessionStartHour input:', text.count('input int  SessionStartHour'))
print('  inSession:', text.count('inSession'))
print('  slBuy:', text.count('slBuy'))
print('  slSell:', text.count('slSell'))
print('  OP_BUYSTOP call (should be 0):', text.count('ManageSinglePendingOrder(OP_BUYSTOP'))
print('  OP_SELLSTOP call (should be 1):', text.count('ManageSinglePendingOrder(OP_SELLSTOP'))
print('  File chars:', len(text))

new_raw = b'\xff\xfe' + text.encode('utf-16-le')
with open(path, 'wb') as f:
    f.write(new_raw)
print('Written:', len(new_raw), 'bytes')
