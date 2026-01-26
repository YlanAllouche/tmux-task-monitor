#!/usr/bin/env bash

# tmux-resource-monitor launch script
# This script is executed by TPM when the keybinding is triggered

script_dir=$(dirname "$0")
script_dir=$(
	cd "$script_dir"
	pwd
)

. "$script_dir/helpers.sh"

PLUGIN_DIR="$(dirname "$script_dir")"

REFRESH_RATE=$(get_option "@tmux_resource_monitor_refresh_rate" "2.0")
WINDOW_FILTER=$(get_option "@tmux_resource_monitor_window_filter" "")
WIDTH=$(get_option "@tmux_resource_monitor_width" "80%")
HEIGHT=$(get_option "@tmux_resource_monitor_height" "80%")

SESSION_NAME=$(tmux display-message -p '#{session_name}')
WINDOW_NAME=$(tmux display-message -p '#{window_name}')
CWD=$(tmux display-message -p '#{pane_current_path}')

ARGS="$SESSION_NAME"
if [ -n "$WINDOW_FILTER" ]; then
    ARGS="$ARGS -w $WINDOW_NAME"
fi
ARGS="$ARGS -r $REFRESH_RATE"

tmux display-popup -E -w "$WIDTH" -h "$HEIGHT" -d "$CWD" python3 "$PLUGIN_DIR/tmux_monitor.py" $ARGS
