#!/usr/bin/env bash
# guard-upstream.sh -- PreToolUse(Bash) hook.
#
# One job: refuse to push, or open a PR/issue/comment, against the UPSTREAM
# remote via a git/gh command line this parser recognises. Pushing to a
# personal fork stays allowed, which is why a flat permissions deny rule
# ("Bash(git push:*)") cannot do this job -- the permission matcher cannot
# condition on an argument, only on a prefix.
#
# THIS IS A TRIP-WIRE AGAINST AN HONEST MISTAKE, NOT A SECURITY BOUNDARY.
# An earlier version of this comment claimed "fails closed" -- that claim did
# not survive two rounds of adversarial testing (2026-09-11) and is retracted
# here rather than left standing. It parses shell TEXT; it cannot see what git
# will actually do, and several of its checks can be made to look at the wrong
# thing entirely (a remote's fetch URL when only its PUSH url was swapped; a
# remote that does not exist yet at the instant the whole command line is
# evaluated; a `--repo` flag whose value is silently discarded). Confirmed,
# by execution, still open at every layer this class of control can reach:
#   - a git ALIAS, a shell FUNCTION shadowing `git`, `eval`, `xargs`, a
#     Makefile/script target -- none of these present a literal `git`/`gh`
#     token this parser can see.
#   - a push assembled inside an interpreted language's own syntax
#     (`python3 -c "...subprocess.run(['git','push',...])"`) -- unparseable
#     without parsing that language.
#   - a bare `curl`/`wget` straight to the GitHub API with the live token.
#   - this script itself is plain text, editable via Edit/Write (the
#     PreToolUse matcher below only fires on the Bash tool), and is simply
#     absent in a fresh clone or worktree until someone copies .claude/ in.
# None of the above is a defect IN this script; they are the ceiling on what
# a shell-text scanner can ever be. The actual boundary, when one exists, is
# the credential's own scope (see .claude/COLLAB.md) -- a hook cannot bound
# what a valid, sufficiently-privileged credential is permitted to do.
#
# What it IS good for, and does adequately: catching a cooperative agent's
# unintended `git push origin`, copy-pasted command, or momentary lapse,
# before it becomes an API round-trip. Treat a DENY here as a caught mistake,
# and an ALLOW as "no obvious mistake found" -- never as "this is safe."
#
# Deps: jq (present in this devcontainer), git. No network.

set -uo pipefail

# Remote names, and URL fragments, that are forbidden targets.
FORBIDDEN_REMOTES_DEFAULT="origin"
FORBIDDEN_URL_MATCH_DEFAULT="Immersive-commons/living-portraits"
FORBIDDEN_REMOTES="${LP_FORBIDDEN_REMOTES:-$FORBIDDEN_REMOTES_DEFAULT}"
FORBIDDEN_URL_MATCH="${LP_FORBIDDEN_URL:-$FORBIDDEN_URL_MATCH_DEFAULT}"

command -v jq >/dev/null 2>&1 || exit 0   # no jq: stay out of the way

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')
[ -n "$CMD" ] || exit 0
[ -n "$CWD" ] && cd "$CWD" 2>/dev/null

deny() {
  jq -n --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
}

# Is remote name (or raw URL) $1 a forbidden target?
remote_is_forbidden() {
  local name="$1" url pushurl name_lc match_lc="${FORBIDDEN_URL_MATCH,,}"
  name_lc="${name,,}"
  for f in $FORBIDDEN_REMOTES; do
    [ "$name" = "$f" ] && return 0
  done
  # A raw URL can be a push target too -- check the token itself, not just
  # the configured remotes, or `git push https://.../upstream.git` walks past.
  # Case-insensitive: confirmed by a live `gh api` call (2026-09-11) that
  # GitHub itself resolves "immersive-commons/..." to the real
  # "Immersive-commons/..." repo, so a literal-case check here stops a typo,
  # not a determined mismatch.
  case "$name_lc" in *"$match_lc"*) return 0 ;; esac
  url=$(git remote get-url "$name" 2>/dev/null) || return 1
  case "${url,,}" in *"$match_lc"*) return 0 ;; esac
  # The FETCH url can point anywhere while the PUSH url points upstream --
  # `git remote set-url --push NAME <upstream-url>` once, and every future
  # `git push NAME ...` (the fork included) reaches upstream even though
  # plain `git remote get-url NAME` above still reports the harmless fetch
  # url. Confirmed by execution, 2026-09-11.
  pushurl=$(git remote get-url --push "$name" 2>/dev/null) || return 1
  case "${pushurl,,}" in *"$match_lc"*) return 0 ;; esac
  return 1
}

# Strip heredoc BODIES before splitting -- but ONLY when the heredoc's consumer is
# a known DATA SINK (cat, tee). `cat > doc.md <<EOF ... EOF` whose text describes
# pushing to the upstream remote is documentation, and refusing it makes this a
# guard that forbids describing the thing it guards -- which is how guards get
# switched off. That is the ONLY case this strips.
#
# `bash <<EOF ... EOF`, `sh <<EOF`, `python3 - <<EOF` and the like are NOT data --
# the interpreter EXECUTES the body. An earlier version of this stripped every
# heredoc body unconditionally and `bash <<'EOF'\ngit push origin main\nEOF` sailed
# through as allowed: the exact class of bypass this hook exists to close. So a
# heredoc opened by anything other than cat/tee is left in the stream, and its body
# is scanned by the normal per-line git/gh checks below like any other command --
# which is correct, because for those consumers it is literally about to run as one.
#
# This still cannot see a `git push` assembled at runtime inside an interpreted
# string (a python subprocess.run([...]) call, a perl system(), an eval'd
# variable) -- no static scan of a command line can, without parsing that
# language. That residual gap is accepted and documented, not silently covered.
CMD=$(printf '%s' "$CMD" | awk '
  delim != "" {
    if (sink) {
      t = $0; sub(/^[ \t]+/, "", t); sub(/[ \t]+$/, "", t)
      if (t == delim) delim = ""
      next
    }
    # Not a data sink: keep printing the body so it gets scanned as commands too.
    print
    t = $0; sub(/^[ \t]+/, "", t); sub(/[ \t]+$/, "", t)
    if (t == delim) delim = ""
    next
  }
  {
    print
    # <<EOF  <<-EOF  <<"EOF"  <<\EOF -- a bare word at end of line, not a shift op.
    if (match($0, /<<-?[ \t]*\\?["'"'"']?[A-Za-z_][A-Za-z0-9_]*["'"'"']?[ \t]*$/)) {
      d = substr($0, RSTART, RLENGTH)
      gsub(/^<<-?[ \t]*\\?["'"'"']?|["'"'"']?[ \t]*$/, "", d)
      delim = d
      # Is the line that OPENED this heredoc a data sink (cat/tee), possibly
      # behind sudo/env/command/time/nice/nohup? Anything else -- bash, sh,
      # python, perl, ruby, node, an unrecognised command -- is treated as
      # code, not data, and its body is NOT stripped.
      o = $0
      gsub(/^[ \t]*((sudo|env|command|builtin|time|nice|nohup)[ \t]+)*/, "", o)
      sink = (o ~ /^(cat|tee)([ \t]|$)/) ? 1 : 0
    }
  }')

# Split the command on shell operators so "foo && git push" is seen.
# Newlines and ; & | && || all become segment breaks.
SEGMENTS=$(printf '%s' "$CMD" | sed -E 's/\|\||&&|;|\||&/\n/g')

while IFS= read -r seg; do
  # shellcheck disable=SC2086
  set -- $seg
  [ $# -gt 0 ] || continue

  # Strip common wrappers Claude Code itself strips.
  while [ $# -gt 0 ]; do
    case "$1" in
      timeout|time|nice|nohup|command|builtin|env|sudo) shift ;;
      *) break ;;
    esac
  done
  [ $# -gt 0 ] || continue

  # ---------------------------------------------------------------- gh
  if [ "$1" = "gh" ]; then
    shift

    # `gh api` is the back door: it can open an issue or post a comment with no
    # subcommand this case statement would recognise. Only WRITES are refused --
    # a GET is how you check whether something is already fixed, and blocking
    # that would push the work back to guessing.
    if [ "${1:-}" = "api" ]; then
      shift                      # drop "api" itself, or it is read as the path
      writes=0 path="" skip=0
      for ((i=1; i<=$#; i++)); do
        a="${!i}"
        # A flag's VALUE is not the path. Without this, `-X POST repos/...`
        # reads "POST" as the path and the real target is never checked.
        if [ "$skip" = "1" ]; then skip=0; continue; fi
        case "$a" in
          -X|--method) j=$((i+1)); skip=1
                       case "${!j:-}" in POST|PATCH|PUT|DELETE) writes=1 ;; esac ;;
          --method=*)  case "${a#--method=}" in POST|PATCH|PUT|DELETE) writes=1 ;; esac ;;
          -f|-F|--field|--raw-field) writes=1; skip=1 ;;
          -H|--header|--input|-q|--jq|-t|--template) skip=1 ;;
          -*) ;;
          *) [ -z "$path" ] && path="$a" ;;
        esac
      done
      if [ "$writes" = "1" ]; then
        org_lc="${FORBIDDEN_URL_MATCH%%/*}"; org_lc="${org_lc,,}"
        case "${path,,}" in
          *"$org_lc"*)
            deny "Blocked: 'gh api' write to $path targets the upstream org. Nothing is posted upstream -- not a PR, not an issue, not a comment -- until the user says so." ;;
        esac
      fi
      continue
    fi

    case "${1:-}${2:+ $2}" in
      # Every way gh writes something someone upstream has to read. The ledger's
      # cause-B incident was a PR; twenty issues went the same way through a door
      # this case statement did not cover.
      "pr create"|"pr merge"|"pr comment"|"pr review"|"pr edit"|"pr close"|"pr reopen"|\
      "issue create"|"issue comment"|"issue edit"|"issue close"|"issue reopen"|\
      "release create")
        # --repo <owner/name> pointing somewhere else is fine.
        target=""
        for ((i=1; i<=$#; i++)); do
          a="${!i}"
          [ "$a" = "--repo" ] || [ "$a" = "-R" ] && { j=$((i+1)); target="${!j:-}"; }
          case "$a" in --repo=*) target="${a#--repo=}" ;; esac
        done
        if [ -z "$target" ]; then
          deny "Blocked: '$1 ${2:-}' with no --repo defaults to the upstream repo ($FORBIDDEN_URL_MATCH). Nothing is posted upstream -- PR, issue, or comment -- until the user says so. Pass --repo <your-fork> if you meant the fork."
        fi
        org_lc="${FORBIDDEN_URL_MATCH%%/*}"; org_lc="${org_lc,,}"
        case "${target,,}" in
          *"$org_lc"*)
            deny "Blocked: --repo $target targets the upstream org. Nothing is posted upstream -- PR, issue, or comment -- until the user says so." ;;
        esac
        ;;
    esac
    continue
  fi

  # --------------------------------------------------------------- git
  [ "$1" = "git" ] || continue
  shift
  # Skip git's own global flags: -C <dir>, -c k=v, --git-dir=..., etc.
  while [ $# -gt 0 ]; do
    case "$1" in
      -C|-c) shift 2 ;;
      -*) shift ;;
      *) break ;;
    esac
  done
  # git remote add/set-url naming the forbidden URL under a NEW local name,
  # even with no push in the same command -- closes a same-command race:
  # `git remote add X <upstream> && git push X <branch>` is evaluated as ONE
  # string before any of it runs, so `remote_is_forbidden X` fails (X does not
  # exist yet) and is read as "not forbidden." As two SEPARATE commands this
  # is already caught correctly (the second sees the real, now-existing
  # remote) -- only the single-compound-command form needed this. Confirmed
  # by execution, 2026-09-11. There is no legitimate reason to alias upstream
  # under a second local name when a name for it (origin) already exists.
  case "${1:-}${2:+ $2}" in
    "remote add"|"remote set-url")
      for a in "$@"; do
        case "${a,,}" in *"${FORBIDDEN_URL_MATCH,,}"*)
          deny "Blocked: '$1 $2' names the upstream URL under a local alias. This repo's rule is no pushes to upstream, under any name -- origin already names it." ;;
        esac
      done
      ;;
  esac

  [ "${1:-}" = "push" ] || continue
  shift

  # First non-flag positional after `push` is the remote. --repo's value is
  # captured too: real git ignores it whenever a positional target is ALSO
  # given (that positional must itself be a valid target or the whole push
  # fails -- verified by execution, 2026-09-11), so the positional above
  # already covers that case correctly. What --repo overrides is the BARE
  # case below, when it is given with nothing else.
  remote="" repo_flag=""
  while [ $# -gt 0 ]; do
    case "$1" in
      -u|--set-upstream|--force|-f|--force-with-lease|--tags|--all|--delete|-d|--dry-run|-n|--atomic|--follow-tags|-v|--verbose|-q|--quiet) shift ;;
      --repo=*) repo_flag="${1#--repo=}"; shift ;;
      --repo) repo_flag="${2:-}"; shift 2 ;;
      --*=*) shift ;;
      -o|--push-option|--receive-pack|--exec) shift 2 ;;
      -*) shift ;;
      *) remote="$1"; break ;;
    esac
  done

  if [ -z "$remote" ]; then
    # `git push --repo=X` with NOTHING else -- confirmed by execution,
    # 2026-09-11: real git uses X as the actual target and does NOT fall back
    # to the branch's tracked remote in this case (that fallback is only for
    # a true bare `git push`, no --repo at all). The earlier version of this
    # branch discarded --repo's value entirely and checked the WRONG thing.
    if [ -n "$repo_flag" ]; then
      if remote_is_forbidden "$repo_flag"; then
        deny "Blocked: 'git push --repo=$repo_flag' targets upstream. This repo's rule is no pushes to upstream. Use: git push fork <branch>"
      fi
      continue
    fi
    # True bare `git push` -- goes to the current branch's tracked remote.
    br=$(git symbolic-ref --short HEAD 2>/dev/null)
    remote=$(git config --get "branch.$br.remote" 2>/dev/null)
    remote="${remote:-$(git config --get remote.pushDefault 2>/dev/null)}"
    remote="${remote:-origin}"   # git's own default. Fail closed.
    if remote_is_forbidden "$remote"; then
      deny "Blocked: bare 'git push' on branch '$br' resolves to remote '$remote' ($(git remote get-url "$remote" 2>/dev/null)), which is upstream. This repo's rule is no pushes to upstream. Name the fork explicitly: git push fork $br"
    fi
    continue
  fi

  if remote_is_forbidden "$remote"; then
    deny "Blocked: 'git push $remote' targets upstream ($(git remote get-url "$remote" 2>/dev/null)). This repo's rule is no pushes to upstream. Use: git push fork <branch>"
  fi
done <<< "$SEGMENTS"

exit 0
