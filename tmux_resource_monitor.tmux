#!/usr/bin/env bash

# tmux-resource-monitor main plugin file
# This file is executed by TPM when plugin is loaded

# Get plugin directory
PLUGIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Set up keybinding when plugin loads
tmux bind-key t run-shell "$PLUGIN_DIR/scripts/launch_monitor.sh"

# Set variables for popup
PLUGIN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
tmux display-popup -E -w "$WIDTH" -h "$HEIGHT" -d "$CWD" "$PLUGIN_DIR/tmux_monitor.py $ARGS"
