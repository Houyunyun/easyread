#!/bin/sh
set -eu
printf '\nEasyRead CLI terminal / CLI 管理终端\n\n'
printf '  easyread-cli status                 # Installed versions / 已安装版本\n'
printf '  easyread-cli login claude           # Claude login / 登录 Claude\n'
printf '  easyread-cli login codex            # Codex device login / 设备登录\n'
printf '  easyread-cli auth-status claude     # Login state / 登录状态\n'
printf '  easyread-cli auth-status codex\n'
printf '  easyread-cli update all             # Update when idle / 空闲时更新\n\n'
printf 'Open the CLI login URL in your own browser. Paste a code if prompted.\n'
printf '在自己的浏览器打开 CLI 输出的登录链接，需要时将验证码粘贴回终端。\n'
printf 'HOME and CLI updates persist. Disconnecting closes this shell.\n\n'
exec python /usr/local/bin/easyread-runtime bash --noprofile --norc -i
