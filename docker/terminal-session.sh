#!/bin/sh
set -u
printf '\nEasyRead · CLI workspace\n\n'
case "${1:-shell}" in
  claude-login) easyread-cli login claude ;;
  codex-login) easyread-cli login codex ;;
  claude-status) easyread-cli auth-status claude ;;
  codex-status) easyread-cli auth-status codex ;;
  claude-update) easyread-cli update claude ;;
  codex-update) easyread-cli update codex ;;
  shell) ;;
  *) echo 'Unknown action' >&2; exit 1 ;;
esac
printf '\n  easyread-cli status        · installed CLI versions\n'
printf '  easyread-cli login claude  · sign in to Claude\n'
printf '  easyread-cli login codex   · sign in to Codex\n'
printf '  easyread-cli update all    · update when jobs are idle\n\n'
printf 'Open login links in your browser and paste the code here if requested.\n'
printf 'Closing settings disconnects this shell; HOME and credentials persist.\n\n'
exec python /usr/local/bin/easyread-runtime bash --noprofile --norc -i
