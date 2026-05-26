#!/usr/bin/env bash
# No-agent fallback: pulls today's prediction + verifies yesterday + emits Chinese summary.
# Usage: check_daily.sh
# Output: stdout, suitable for direct delivery via Hermes no-agent cron.

set -uo pipefail

API="http://127.0.0.1"
TZ_BJ='Asia/Shanghai'

today() { TZ="$TZ_BJ" date +%F; }
yesterday() { TZ="$TZ_BJ" date -d 'yesterday' +%F 2>/dev/null || python3 -c "from datetime import date,timedelta; print((date.today()-timedelta(days=1)).isoformat())"; }

curl_json() {
    curl -fsS --max-time 8 "$@" || echo '{}'
}

if ! command -v jq >/dev/null 2>&1; then
    echo "[check_daily] jq missing; install with: apt-get install -y jq"
    exit 0
fi

T=$(today)
Y=$(yesterday)

curl_json -X POST "$API/api/predictions/daily/verify?date=$Y" >/dev/null
RUN=$(curl_json -X POST "$API/api/predictions/daily/run?date=$T")
TODAY=$(curl_json "$API/api/predictions/today")
ACC=$(curl_json "$API/api/predictions/accuracy?window=30d")

PRED=$(echo "$TODAY" | jq -r '.data // empty')
if [ -z "$PRED" ] || [ "$PRED" = "null" ]; then
    PRED=$(echo "$RUN" | jq -r '.data // empty')
fi
if [ -z "$PRED" ] || [ "$PRED" = "null" ]; then
    echo "【Aurumers · $T】今日预测尚未生成，后端可能不可达。"
    exit 0
fi

SGE=$(echo "$PRED" | jq -r '.today_close_sge // "—"')
COMEX=$(echo "$PRED" | jq -r '.today_close_comex // "—"')
TODAY_DIR=$(echo "$PRED" | jq -r '.today_direction // "—"')
TOMORROW_DIR=$(echo "$PRED" | jq -r '.tomorrow_direction // "—"')
CONF=$(echo "$PRED" | jq -r '.tomorrow_confidence // 0')
ADVICE=$(echo "$PRED" | jq -r '.tomorrow_advice // "—"')
REASONING=$(echo "$PRED" | jq -r '.reasoning_summary // "—"')
RISK=$(echo "$PRED" | jq -r '.risk_factors | join("; ")' 2>/dev/null || echo "—")
CALIB=$(echo "$PRED" | jq -r '.calibration_note // "—"')
ACC_VAL=$(echo "$ACC" | jq -r '.data.overall_accuracy // 0')
STREAK=$(echo "$ACC" | jq -r '.data.current_streak // 0')

# Pass values through argv to Python — never source-interpolate user-controlled strings.
to_pct() {
    python3 -c 'import sys; v=float(sys.argv[1]) if sys.argv[1] not in ("", "null") else 0.0; print(f"{v*100:.0f}%")' "$1" 2>/dev/null || echo "—"
}
ACC_PCT=$(to_pct "$ACC_VAL")
CONF_PCT=$(to_pct "$CONF")

cat <<EOF
【Aurumers · $T 每日金价预测】

今日 SGE 收盘：$SGE
今日 COMEX 收盘：$COMEX
今日定性：$TODAY_DIR

明日预测：$TOMORROW_DIR（置信 $CONF_PCT）
关键理由：$REASONING
操作建议：$ADVICE

风险因素：$RISK
近 30 天准确率：$ACC_PCT（连续命中 $STREAK）
校准说明：$CALIB
EOF
