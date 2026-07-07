#!/bin/bash
# Claude Code statusline
# Rate-limit values are cached to a temp file so the section never goes blank
# between API calls — staleness is shown as "(cached Xm ago)".

input=$(cat)
CACHE_FILE="${TMPDIR:-/tmp}/.claude_rl_$(id -u 2>/dev/null || echo 0)"

# ── parse JSON ────────────────────────────────────────────────────────────────
MODEL=$(echo "$input"     | jq -r '.model.display_name // "unknown"')
DIR=$(echo "$input"       | jq -r '.workspace.current_dir // ""')
SESSION=$(echo "$input"   | jq -r '.session_name // empty')
VERSION=$(echo "$input"   | jq -r '.version // ""')
VIM_MODE=$(echo "$input"  | jq -r '.vim.mode // empty')
AGENT=$(echo "$input"     | jq -r '.agent.name // empty')
WT_BRANCH=$(echo "$input" | jq -r '.worktree.branch // empty')

CTX_SIZE=$(echo "$input"  | jq -r '.context_window.context_window_size // 0')
USED_PCT=$(echo "$input"  | jq -r '.context_window.used_percentage // empty')
REM_PCT=$(echo "$input"   | jq -r '.context_window.remaining_percentage // empty')
IN_TOK=$(echo "$input"    | jq -r '.context_window.current_usage.input_tokens // empty')
OUT_TOK=$(echo "$input"   | jq -r '.context_window.current_usage.output_tokens // empty')
CACHE_W=$(echo "$input"   | jq -r '.context_window.current_usage.cache_creation_input_tokens // empty')
CACHE_R=$(echo "$input"   | jq -r '.context_window.current_usage.cache_read_input_tokens // empty')
TOT_IN=$(echo "$input"    | jq -r '.context_window.total_input_tokens // empty')
TOT_OUT=$(echo "$input"   | jq -r '.context_window.total_output_tokens // empty')

FIVE_HR=$(echo "$input"   | jq -r '.rate_limits.five_hour.used_percentage // empty')
FIVE_RST=$(echo "$input"  | jq -r '.rate_limits.five_hour.resets_at // empty')
SEVEN_DAY=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
SEVEN_RST=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')

# ── rate-limit caching ────────────────────────────────────────────────────────
# Claude Code only includes rate_limits when it gets fresh headers from the API.
# Persist the last known values so the bars don't disappear between messages.
RATE_FRESH=0
CACHE_TS=""
if [ -n "$FIVE_HR" ] || [ -n "$SEVEN_DAY" ]; then
  RATE_FRESH=1
  printf '%s\t%s\t%s\t%s\t%d\n' \
    "${FIVE_HR:-}" "${FIVE_RST:-}" "${SEVEN_DAY:-}" "${SEVEN_RST:-}" "$(date +%s)" \
    > "$CACHE_FILE" 2>/dev/null
elif [ -f "$CACHE_FILE" ]; then
  IFS=$'\t' read -r FIVE_HR FIVE_RST SEVEN_DAY SEVEN_RST CACHE_TS < "$CACHE_FILE"
fi

# ── account / plan ────────────────────────────────────────────────────────────
_CLAUDE_CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
ACCOUNT_EMAIL="" ACCOUNT_ORG="" PLAN_NAME=""

for _cc in "$_CLAUDE_CFG/.claude.json" "$HOME/.claude.json"; do
  [ -f "$_cc" ] || continue
  _email=$(jq -r '.oauthAccount.emailAddress // empty' "$_cc" 2>/dev/null)
  [ -n "$_email" ] && [ "$_email" != "null" ] || continue
  ACCOUNT_EMAIL="$_email"
  ACCOUNT_ORG=$(jq -r '.oauthAccount.organizationName // empty' "$_cc" 2>/dev/null)
  _tier=$(jq -r '(.oauthAccount.userRateLimitTier // .oauthAccount.organizationRateLimitTier) // empty' "$_cc" 2>/dev/null)
  _extra=$(jq -r '.oauthAccount.hasExtraUsageEnabled // false' "$_cc" 2>/dev/null)
  case "$_tier" in
    *max_20x*)                   PLAN_NAME="Max 20x" ;;
    *max_5x*)                    PLAN_NAME="Max 5x" ;;
    *max_1x*)                    PLAN_NAME="Max 1x" ;;
    *claude_pro*|*default_claude_ai*)
      [ "$_extra" = "true" ] && PLAN_NAME="Max" || PLAN_NAME="Pro" ;;
    "") ;;
    *) PLAN_NAME="$_tier" ;;
  esac
  break
done
# Fallback: derive label from config dir name when no auth file found
if [ -z "$ACCOUNT_EMAIL" ]; then
  _dn=$(basename "$_CLAUDE_CFG")
  if [ "$_dn" != ".claude" ] && [ "$_dn" != "claude" ]; then
    ACCOUNT_EMAIL="${_dn#.claude-}"; ACCOUNT_EMAIL="${ACCOUNT_EMAIL#claude-}"
  fi
fi

# ── colours ───────────────────────────────────────────────────────────────────
CYAN='\033[36m'; BLUE='\033[34m'; GREEN='\033[32m'
YELLOW='\033[33m'; RED='\033[31m'; MAGENTA='\033[35m'
BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

# ── helpers ───────────────────────────────────────────────────────────────────
make_bar() {
  local pct="${1:-0}" color="$2"
  local ipct; ipct=$(printf '%.0f' "$pct" 2>/dev/null) || ipct=0
  [ "$ipct" -gt 100 ] && ipct=100
  local filled=$(( (ipct * 20 + 50) / 100 ))
  [ "$filled" -gt 20 ] && filled=20
  local empty=$(( 20 - filled ))
  printf -v F "%${filled}s" ""; printf -v E "%${empty}s" ""
  printf "%b%s%b%s" "$color" "${F// /█}" "$DIM" "${E// /░}"
}

fmt_k() {
  local n="${1:-}"
  [ -z "$n" ] || [ "$n" = "null" ] && echo "—" && return
  [ "$n" -ge 1000 ] 2>/dev/null && printf '%dk' $(( n / 1000 )) || printf '%d' "$n"
}

fmt_reset() {
  local epoch="${1:-}"
  [ -z "$epoch" ] || [ "$epoch" = "null" ] && return
  local now; now=$(date +%s)
  local diff=$(( epoch - now ))
  [ "$diff" -le 0 ] && echo "now" && return
  local h=$(( diff / 3600 )) m=$(( (diff % 3600) / 60 ))
  [ "$h" -gt 0 ] && printf '%dh%dm' "$h" "$m" || printf '%dm' "$m"
}

fmt_age() {
  local ts="${1:-}"
  [ -z "$ts" ] && return
  local now; now=$(date +%s)
  local age=$(( now - ts ))
  if   [ "$age" -lt 60 ];   then printf '%ds' "$age"
  elif [ "$age" -lt 3600 ]; then printf '%dm' $(( age / 60 ))
  else                           printf '%dh' $(( age / 3600 ))
  fi
}

# ── line 1: model / session / account / plan / dir / branch ──────────────────
SESSION_PART=""
[ -n "$SESSION" ] && SESSION_PART=" ${DIM}(${SESSION})${RESET}"

BRANCH=""
GIT_DIR=$(git -C "$DIR" rev-parse --git-dir 2>/dev/null)
if [ -n "$GIT_DIR" ]; then
  BR=$(git -C "$DIR" -c core.useReplacement=false branch --show-current 2>/dev/null)
  [ -n "$WT_BRANCH" ] && BR="$WT_BRANCH"
  [ -n "$BR" ] && BRANCH=" ${DIM}on${RESET} ${MAGENTA}${BR}${RESET}"
fi

AGENT_PART=""
[ -n "$AGENT" ] && AGENT_PART=" ${YELLOW}[agent:${AGENT}]${RESET}"

VIM_PART=""
[ -n "$VIM_MODE" ] && VIM_PART=" ${BLUE}[${VIM_MODE}]${RESET}"

VER_PART=""
[ -n "$VERSION" ] && VER_PART=" ${DIM}v${VERSION}${RESET}"

ACCT_PART=""
if [ -n "$ACCOUNT_EMAIL" ]; then
  ACCT_PART=" ${DIM}as${RESET} ${MAGENTA}${ACCOUNT_EMAIL}${RESET}"
  [ -n "$ACCOUNT_ORG" ] && ACCT_PART="${ACCT_PART} ${DIM}@ ${ACCOUNT_ORG}${RESET}"
fi

PLAN_PART=""
[ -n "$PLAN_NAME" ] && PLAN_PART=" ${DIM}[${RESET}${CYAN}${PLAN_NAME}${RESET}${DIM}]${RESET}"

printf "${BOLD}${CYAN}[${MODEL}]${RESET}${VER_PART}${SESSION_PART}${AGENT_PART}${VIM_PART}${ACCT_PART}${PLAN_PART}  ${DIR##*/}${BRANCH}\n"

# ── line 2: context window bar + token counts ─────────────────────────────────
if [ -n "$USED_PCT" ]; then
  PCT=$(printf '%.0f' "$USED_PCT" 2>/dev/null || echo 0)
  REM=$(printf '%.0f' "${REM_PCT:-$(( 100 - PCT ))}" 2>/dev/null || echo 0)

  if   [ "$PCT" -ge 90 ]; then BAR_COLOR="$RED"
  elif [ "$PCT" -ge 70 ]; then BAR_COLOR="$YELLOW"
  else BAR_COLOR="$GREEN"; fi

  BAR=$(make_bar "$PCT" "$BAR_COLOR")

  TOK_DETAIL=""
  if [ -n "$IN_TOK" ]; then
    TOK_DETAIL=" ${DIM}in:$(fmt_k "$IN_TOK") out:$(fmt_k "$OUT_TOK")"
    [ -n "$CACHE_R" ] && [ "$CACHE_R" -gt 0 ] 2>/dev/null \
      && TOK_DETAIL="${TOK_DETAIL} cr:$(fmt_k "$CACHE_R")"
    [ -n "$CACHE_W" ] && [ "$CACHE_W" -gt 0 ] 2>/dev/null \
      && TOK_DETAIL="${TOK_DETAIL} cw:$(fmt_k "$CACHE_W")"
    TOK_DETAIL="${TOK_DETAIL}${RESET}"
  fi

  CUM_DETAIL=""
  [ -n "$TOT_IN" ] && CUM_DETAIL=" ${DIM}∑in:$(fmt_k "$TOT_IN") ∑out:$(fmt_k "$TOT_OUT")${RESET}"

  CTX_K=$(fmt_k "$CTX_SIZE")
  printf "%b %b${RESET} ${BAR_COLOR}${PCT}%%${RESET} ${DIM}rem:${REM}%%${RESET}${TOK_DETAIL}${CUM_DETAIL} ${DIM}ctx:${CTX_K}${RESET}\n" \
    "${DIM}ctx${RESET}" "$BAR"
else
  printf "${DIM}ctx: waiting for first message…${RESET}\n"
fi

# ── line 3: rate limits ───────────────────────────────────────────────────────
if [ -n "$FIVE_HR" ] || [ -n "$SEVEN_DAY" ]; then
  STALE_PART=""
  if [ "$RATE_FRESH" -eq 0 ] && [ -n "$CACHE_TS" ]; then
    AGE=$(fmt_age "$CACHE_TS")
    STALE_PART=" ${DIM}(cached ${AGE} ago)${RESET}"
  fi

  RATE_LINE=""
  if [ -n "$FIVE_HR" ] && [ "$FIVE_HR" != "null" ]; then
    P=$(printf '%.0f' "$FIVE_HR" 2>/dev/null || echo 0)
    if   [ "$P" -ge 90 ]; then RC="$RED"
    elif [ "$P" -ge 70 ]; then RC="$YELLOW"
    else RC="$GREEN"; fi
    BAR5=$(make_bar "$P" "$RC")
    RST5=$(fmt_reset "$FIVE_RST")
    RST5_PART=""; [ -n "$RST5" ] && RST5_PART=" ${DIM}resets ${RST5}${RESET}"
    RATE_LINE="${DIM}5h${RESET} ${BAR5}${RESET} ${RC}${P}%%${RESET}${RST5_PART}"
  fi

  if [ -n "$SEVEN_DAY" ] && [ "$SEVEN_DAY" != "null" ]; then
    P=$(printf '%.0f' "$SEVEN_DAY" 2>/dev/null || echo 0)
    if   [ "$P" -ge 90 ]; then RC="$RED"
    elif [ "$P" -ge 70 ]; then RC="$YELLOW"
    else RC="$GREEN"; fi
    BAR7=$(make_bar "$P" "$RC")
    RST7=$(fmt_reset "$SEVEN_RST")
    RST7_PART=""; [ -n "$RST7" ] && RST7_PART=" ${DIM}resets ${RST7}${RESET}"
    [ -n "$RATE_LINE" ] && RATE_LINE="${RATE_LINE}  "
    RATE_LINE="${RATE_LINE}${DIM}7d${RESET} ${BAR7}${RESET} ${RC}${P}%%${RESET}${RST7_PART}"
  fi

  printf "%b%b\n" "$RATE_LINE" "$STALE_PART"
fi
