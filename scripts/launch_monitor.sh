#!/usr/bin/env bash

# tmux-resource-monitor launch script
# This script is executed by TPM when plugin is loaded

PLUGIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Read tmux options with defaults
REFRESH_RATE=$(tmux show-option -gqv '@tmux_resource_monitor_refresh_rate' 2>/dev/null || echo "2.0")
WINDOW_FILTER=$(tmux show-option -gqv '@tmux_resource_monitor_window_filter' 2>/dev/null || echo "")
WIDTH=$(tmux show-option -gqv '@tmux_resource_monitor_width' 2>/dev/null || echo "80%")
HEIGHT=$(tmux show-option -gqv '@tmux_resource_monitor_height' 2>/dev/null || echo "40%")

# Get current session/window info from tmux
SESSION_NAME=$(tmux display-message -p '#{session_name}')
WINDOW_NAME=$(tmux display-message -p '#{window_name}')
CWD=$(tmux display-message -p '#{pane_current_path}')

# Build command arguments
ARGS="\"$SESSION_NAME\""
if [ -n "$WINDOW_FILTER" ]; then
    ARGS="$ARGS -w \"$WINDOW_NAME\""
fi
ARGS="$ARGS -r $REFRESH_RATE"

# Launch Python monitor
tmux display-popup -E -w "$WIDTH" -h "$HEIGHT" -d "$CWD" "$PLUGIN_DIR/tmux_monitor.py $ARGS"
