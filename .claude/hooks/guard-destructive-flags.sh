#!/usr/bin/env bash
# guard-destructive-flags.sh -- PreToolUse(Bash) hook.
#
# Catches two flags that a prefix-based permission rule CANNOT catch, because
# they can appear at any position in the command line and the permissions
# matcher only matches a prefix:
#
#   --unsafe-fixes   ruff will happily rewrite code in ways that change meaning.
#                    CI does catch the dead-expression fallout (B015/B018 are
#                    selected in ruff.toml and the lint job blocks) -- this just
#                    moves the catch from "after a CI round trip" to "now".
#   -i / --in-place  sed/perl editing a file in place. Regex over prose is how
#                    four PR descriptions were destroyed. Edit is reviewable;
#                    sed -i is not.
#
# Returns "deny". The documented permissionDecision values for PreToolUse are
# "allow", "deny", or omitted -- there is no "ask" for a hook, so a speed bump
# is not on the menu. Both of these have a clean alternative named in the
# reason, and a human can always run the command in their own terminal.
set -uo pipefail
command -v jq >/dev/null 2>&1 || exit 0
CMD=$(cat | jq -r '.tool_input.command // empty')
[ -n "$CMD" ] || exit 0

deny() {
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",
    permissionDecision:"deny", permissionDecisionReason:$r}}'
  exit 0
}

case " $CMD " in
  *" --unsafe-fixes"*|*"--unsafe-fixes "*)
    deny "ruff --unsafe-fixes rewrites code in ways that can change meaning, and has left dead expressions in this tree before. Confirm you want it, or drop the flag and fix the findings by hand." ;;
esac

# sed/perl in-place, only when sed/perl is the command being run.
first=$(printf '%s' "$CMD" | sed -E 's/\|\||&&|;|\|/\n/g' | grep -oE '(^|[[:space:]])(sed|perl)[[:space:]][^\n]*' | head -1)
if [ -n "$first" ]; then
  case "$first" in
    *" -i"*|*" --in-place"*|*" -pi"*|*" -pie"*)
      deny "In-place regex editing (${first%% *}) over a file. Prose is not a regex target -- this destroyed four PR descriptions before. Prefer the Edit tool, which shows an exact diff." ;;
  esac
fi
exit 0
