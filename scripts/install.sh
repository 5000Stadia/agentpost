#!/usr/bin/env sh
set -eu

python=${PYTHON:-python3}
install_dir=${AGENTPOST_INSTALL_DIR:-"$HOME/.local/share/agentpost/venv"}
bin_dir=${AGENTPOST_BIN_DIR:-"$HOME/.local/bin"}
source=${AGENTPOST_SOURCE:-"git+https://github.com/5000Stadia/agentpost.git"}
connection_mode=${AGENTPOST_CONNECTION_MODE:-auto}

if ! command -v "$python" >/dev/null 2>&1; then
    printf 'agentpost: Python 3.11+ is required; %s was not found\n' "$python" >&2
    exit 1
fi

if [ ! -x "$install_dir/bin/python" ]; then
    "$python" -m venv "$install_dir"
fi

"$install_dir/bin/python" -m pip install --upgrade "$source"
mkdir -p "$bin_dir"
ln -sf "$install_dir/bin/agentpost" "$bin_dir/agentpost"
"$bin_dir/agentpost" init --connection-mode "$connection_mode"
"$bin_dir/agentpost" migrate

printf 'AgentPost installed: %s\n' "$bin_dir/agentpost"
case ":${PATH:-}:" in
    *":$bin_dir:"*) ;;
    *) printf 'Add %s to PATH before opening a CLI agent.\n' "$bin_dir" ;;
esac
