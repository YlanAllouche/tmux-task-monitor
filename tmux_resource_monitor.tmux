#!/usr/bin/env bash

# tmux-resource-monitor main plugin file
# This file is sourced by TPM when plugin is loaded

script_dir=$(dirname "$0")
script_dir=$(
	cd "$script_dir"
	pwd
)

. "$script_dir/scripts/helpers.sh"

monitor_key=$(get_option "@tmux_resource_monitor_key" "t")
monitor_script="$script_dir/scripts/launch_monitor.sh"

lowercase_key=$(echo $monitor_key | tr '[:upper:]' '[:lower:]')

if [ "$lowercase_key" != "none" ]; then
	tmux bind-key "${monitor_key}" run-shell -t "#{pane_id}" "$monitor_script"
fi

overview_key=$(get_option "@tmux_resource_monitor_overview_key" "T")
overview_script="$script_dir/scripts/launch_overview.sh"

lowercase_overview_key=$(echo $overview_key | tr '[:upper:]' '[:lower:]')

if [ "$lowercase_overview_key" != "none" ]; then
	tmux bind-key "${overview_key}" run-shell -t "#{pane_id}" "$overview_script"
fi
