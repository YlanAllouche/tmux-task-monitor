#!/usr/bin/env bash

# tmux-resource-monitor overview mode launch script
# This script is executed by TPM when the T keybinding is triggered

script_dir=$(dirname "$0")
script_dir=$(
	cd "$script_dir"
	pwd
)

. "$script_dir/helpers.sh"

PLUGIN_DIR="$(dirname "$script_dir")"

REFRESH_RATE=$(get_option "@tmux_resource_monitor_refresh_rate" "2.0")
WIDTH=$(get_option "@tmux_resource_monitor_width" "80%")
HEIGHT=$(get_option "@tmux_resource_monitor_height" "80%")
PYTHON=$(get_option "@tmux_resource_monitor_python" "python3")

CWD=$(tmux display-message -p '#{pane_current_path}')

tmux display-popup -E -w "$WIDTH" -h "$HEIGHT" -d "$CWD" "$PYTHON" "$PLUGIN_DIR/tmux_overview.py" -r $REFRESH_RATE
