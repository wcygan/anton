#!/usr/bin/env bash
# Install a pre-push shim in this clone's hooks directory. The shim runs the
# .githooks/pre-push committed in whichever worktree is pushing, so every
# worktree uses its own branch's version and shares one installation.
set -Eeuo pipefail
source "$(dirname "${0}")/lib/common.sh"

check_cli git

top="$(git rev-parse --show-toplevel)"
hooks="$(git rev-parse --path-format=absolute --git-path hooks)"
if [[ "${hooks}" == "${top}/.githooks" ]]; then
    log info "core.hooksPath already points at .githooks; nothing to install" "path=${hooks}"
    exit 0
fi

marker="anton-pre-push-shim"
target="${hooks}/pre-push"
if [[ -e "${target}" ]] && ! grep -q "${marker}" "${target}"; then
    log error "Another pre-push hook is installed; merge it with .githooks/pre-push by hand" "path=${target}"
fi

mkdir -p "${hooks}"
cat >"${target}.tmp" <<EOF
#!/bin/sh
# ${marker}: installed by \`task hooks:install\`. Runs the hook committed in
# the pushing worktree; worktrees whose branch predates it push unchecked.
hook="\$(git rev-parse --show-toplevel)/.githooks/pre-push"
if [ -x "\${hook}" ]; then
    exec "\${hook}" "\$@"
fi
EOF
chmod 0755 "${target}.tmp"
mv "${target}.tmp" "${target}"
log info "Installed pre-push hook" "path=${target}"
