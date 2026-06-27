path = r'C:\Users\mariu\AppData\Roaming\MetaQuotes\Terminal\98A82F92176B73A2100FCD1F8ABD7255\MQL4\Experts\Marius Hedger v1.0.mq4'
with open(path, 'rb') as f:
    raw = f.read()
text = raw[2:].decode('utf-16-le')

# ── 1. Version block ──────────────────────────────────────────────────
old_ver = '// | v1.8  2026-05-15  Error 130: skip (not clamp) when pending price too close to market; hedge guard in ManageTrailingPendingOrders |'
new_ver = ('// | v1.9  2026-05-15  Remove bothOpen guard -- skip-only logic is sufficient; BUY STOP now placed for triggered SELL leg |\r\n'
           '// | v1.8  2026-05-15  Error 130: skip (not clamp) when pending price too close to market; hedge guard in ManageTrailingPendingOrders |')
assert text.count(old_ver) == 1, f'ver: {text.count(old_ver)}'
text = text.replace(old_ver, new_ver)

# ── 2. Remove the bothOpen guard block from ManageTrailingPendingOrders ──
OLD_TRAIL_GUARD = (
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
    '    for (int i = 0; i < OrdersTotal(); i++) {'
)
NEW_TRAIL_GUARD = '    for (int i = 0; i < OrdersTotal(); i++) {'

c = text.count(OLD_TRAIL_GUARD)
print(f'bothOpen guard occurrences: {c}')
assert c == 1
text = text.replace(OLD_TRAIL_GUARD, NEW_TRAIL_GUARD)

# ── 3. Verify ──────────────────────────────────────────────────────────
print('\nVerification:')
print('  v1.9:', text.count('v1.9'))
print('  skip this tick:', text.count('skipping this tick'))
print('  Skipping OrderModify:', text.count('Skipping OrderModify'))
print('  bothOpen (should be 0):', text.count('bothOpen'))
print('  TrailGuard (should be 0):', text.count('[TrailGuard]'))
print('  clamp (should be 0):', text.count('Clamp to broker'))
print('  File chars:', len(text))

new_raw = b'\xff\xfe' + text.encode('utf-16-le')
with open(path, 'wb') as f:
    f.write(new_raw)
print('Written:', len(new_raw), 'bytes')
