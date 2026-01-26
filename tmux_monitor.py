#!/usr/bin/env python3
"""
tmux-resource-monitor-curses.py - Lightweight and simple tmux resource monitor using ncurses
"""

import argparse
import curses
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List

import psutil


@dataclass
class WindowStats:
    name: str
    index: int
    cpu_total: float
    ram_total: int  # in KB
    process_count: int
    pane_pids: List[int]
    processes: List[dict]  # Store process info for display


class TmuxResourceMonitor:
    def __init__(self, session_name, window_filter=None, refresh_rate=2.0):
        self.session_name = session_name
        self.window_filter = window_filter
        self.refresh_rate = refresh_rate
        self.total_ram_mb = psutil.virtual_memory().total // (1024 * 1024)
        self.current_tab = 0
        self.windows_data = []
        self.running = True
        self.stdscr = None
        self.colors_initialized = False
        self.show_help = False
        self.process_browsing_active = False
        self.selected_process_index = 0
        self.horizontal_scroll_offset = 0
        self.input_mode = None
        self.input_buffer = ""

    def init_colors(self):
        """Initialize color pairs for curses."""
        if not self.colors_initialized and curses.has_colors():
            curses.start_color()
            curses.use_default_colors()

            # Define color pairs
            curses.init_pair(1, curses.COLOR_GREEN, -1)  # Green text
            curses.init_pair(2, curses.COLOR_YELLOW, -1)  # Yellow text
            curses.init_pair(3, curses.COLOR_CYAN, -1)  # Cyan text
            curses.init_pair(4, curses.COLOR_RED, -1)  # Red text
            curses.init_pair(5, curses.COLOR_BLUE, -1)  # Blue text
            curses.init_pair(6, curses.COLOR_MAGENTA, -1)  # Magenta text
            curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLUE)  # White on blue
            curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_RED)  # White on red for selected process

            self.colors_initialized = True

    def format_memory(self, rss_kb):
        """Format memory usage with MB and percentage."""
        mb = rss_kb // 1024
        percent = (rss_kb * 100) / (self.total_ram_mb * 1024)
        return f"{mb:4d} MB ({percent:5.1f}%)"

    def get_tmux_sessions(self):
        """Get list of available tmux sessions."""
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip().split("\n") if result.stdout.strip() else []
        except subprocess.CalledProcessError:
            return []

    def get_tmux_windows(self):
        """Get windows for the specified session."""
        try:
            cmd = [
                "tmux",
                "list-windows",
                "-t",
                self.session_name,
                "-F",
                "#{window_index}:#{window_name}",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            windows = []
            for line in result.stdout.strip().split("\n"):
                if line and ":" in line:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        try:
                            index = int(parts[0])
                            name = parts[1]
                            windows.append((index, name))
                        except ValueError:
                            continue
            return windows
        except subprocess.CalledProcessError:
            return []

    def get_pane_pids(self, window_index):
        """Get PIDs for all panes in a window."""
        try:
            cmd = [
                "tmux",
                "list-panes",
                "-t",
                f"{self.session_name}:{window_index}",
                "-F",
                "#{pane_pid}",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            pids = []
            for pid_str in result.stdout.strip().split("\n"):
                if pid_str.strip():
                    try:
                        pids.append(int(pid_str.strip()))
                    except ValueError:
                        continue
            return pids
        except subprocess.CalledProcessError:
            return []

    def get_process_info(self, pid, depth=0):
        """Get process info recursively."""
        processes = []
        try:
            parent = psutil.Process(pid)
            try:
                cpu_percent = parent.cpu_percent()
                memory_info = parent.memory_info()
                rss_kb = memory_info.rss // 1024
                cmdline_parts = parent.cmdline()
                if cmdline_parts:
                    executable = cmdline_parts[0].split("/")[-1]  # ? Remove path
                    args = cmdline_parts[1:] if len(cmdline_parts) > 1 else []
                    cmdline = executable + (" " + " ".join(args) if args else "")
                else:
                    cmdline = parent.name()


                processes.append(
                    {
                        "pid": pid,
                        "cpu": cpu_percent,
                        "memory_kb": rss_kb,
                        "command": cmdline,
                        "depth": depth,
                    }
                )

                try:
                    for child in parent.children():
                        processes.extend(self.get_process_info(child.pid, depth + 1))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        return processes

    def get_all_process_stats(self, pid):
        """Get stats for process and all its children."""
        total_cpu = 0
        total_ram = 0
        total_count = 0

        try:
            parent = psutil.Process(pid)

            try:
                total_cpu += parent.cpu_percent()
                total_ram += parent.memory_info().rss // 1024
                total_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            try:
                for child in parent.children(recursive=True):
                    try:
                        total_cpu += child.cpu_percent()
                        total_ram += child.memory_info().rss // 1024
                        total_count += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        return total_cpu, total_ram, total_count

    def collect_window_data(self):
        """Collect data for all windows."""
        windows = self.get_tmux_windows()
        old_windows_count = len(self.windows_data)
        self.windows_data = []

        for window_index, window_name in windows:
            pane_pids = self.get_pane_pids(window_index)

            if not pane_pids:
                window_stats = WindowStats(
                    name=window_name,
                    index=window_index,
                    cpu_total=0,
                    ram_total=0,
                    process_count=0,
                    pane_pids=[],
                    processes=[],
                )
                self.windows_data.append(window_stats)
                continue

            window_cpu_total = 0
            window_ram_total = 0
            window_process_count = 0
            all_processes = []

            for pane_pid in pane_pids:
                processes = self.get_process_info(pane_pid)
                all_processes.extend(processes)

                pane_cpu, pane_ram, pane_count = self.get_all_process_stats(pane_pid)
                window_cpu_total += pane_cpu
                window_ram_total += pane_ram
                window_process_count += pane_count

            window_stats = WindowStats(
                name=window_name,
                index=window_index,
                cpu_total=window_cpu_total,
                ram_total=window_ram_total,
                process_count=window_process_count,
                pane_pids=pane_pids,
                processes=all_processes,
            )
            self.windows_data.append(window_stats)

        if self.window_filter and old_windows_count == 0 and self.windows_data:
            found = False
            for i, window in enumerate(self.windows_data):
                if window.name == self.window_filter:
                    self.current_tab = i
                    found = True
                    break
            if not found:
                self.current_tab = 0

    def draw_header(self, stdscr, height, width):
        """Draw the header with session summary."""
        if not self.windows_data or height < 3:
            return 2

        try:
            total_cpu = sum(w.cpu_total for w in self.windows_data)
            total_ram = sum(w.ram_total for w in self.windows_data)
            total_processes = sum(w.process_count for w in self.windows_data)
            total_ram_mb = total_ram // 1024
            total_ram_percent = (
                (total_ram * 100) / (self.total_ram_mb * 1024)
                if self.total_ram_mb > 0
                else 0
            )

            # Title line - session name with highlighted "Session:"
            x_pos = max(0, (width - len(f"Session: {self.session_name}")) // 2)
            stdscr.addstr(0, x_pos, "Session:", curses.color_pair(2) | curses.A_REVERSE | curses.A_BOLD)
            stdscr.addstr(0, x_pos + 8, " ", curses.color_pair(3))
            stdscr.addstr(0, x_pos + 9, self.session_name, curses.color_pair(3) | curses.A_BOLD)

            # Summary line with different colors for labels, values, and separators
            summary_parts = [
                ("Windows: ", curses.color_pair(2)),
                (str(len(self.windows_data)), curses.color_pair(1)),
                (" | ", curses.color_pair(5)),
                ("CPU: ", curses.color_pair(2)),
                (f"{total_cpu:.1f}%", curses.color_pair(1)),
                (" | ", curses.color_pair(5)),
                ("MEM: ", curses.color_pair(2)),
                (f"{total_ram_mb}MB", curses.color_pair(1)),
                (f" ({total_ram_percent:.1f}%)", curses.color_pair(1)),
                (" | ", curses.color_pair(5)),
                ("Processes: ", curses.color_pair(2)),
                (str(total_processes), curses.color_pair(1))
            ]
            
            # Build the full string and calculate positions for colored segments
            full_summary = "".join(part[0] for part in summary_parts)
            if len(full_summary) > width - 2:
                full_summary = full_summary[: width - 5] + "..."
            
            x_pos = max(0, (width - len(full_summary)) // 2)
            current_x = x_pos
            
            for text, color in summary_parts:
                if current_x + len(text) > width - 1:
                    break
                try:
                    stdscr.addstr(1, current_x, text, color)
                    current_x += len(text)
                except curses.error:
                    break

        except curses.error:
            pass  # Skip drawing if there's an error

        return 2

    def draw_tabs(self, stdscr, y_pos, height, width):
        """Draw the window tabs."""
        if not self.windows_data:
            return y_pos + 1

        x_pos = 0
        stdscr.addstr(y_pos, x_pos, "Windows", curses.color_pair(6) | curses.A_BOLD)
        x_pos += 7
        stdscr.addstr(y_pos, x_pos, ": ", curses.color_pair(3))
        x_pos += 2

        for i, window in enumerate(self.windows_data):
            if i > 0:
                stdscr.addstr(y_pos, x_pos, " | ", curses.color_pair(2))
                x_pos += 3

            display_name = window.name
            if len(display_name) > 12:
                display_name = display_name[:9] + "..."

            if i == self.current_tab:
                try:
                    stdscr.addstr(
                        y_pos,
                        x_pos,
                        f"[{display_name}]",
                        curses.color_pair(2) | curses.A_REVERSE,
                    )
                except curses.error:
                    pass
            else:
                try:
                    stdscr.addstr(y_pos, x_pos, display_name, curses.color_pair(2))
                except curses.error:
                    pass

            x_pos += len(display_name)
            if i == self.current_tab:
                x_pos += 2  # Account for brackets

        counter_text = f" ({self.current_tab + 1}/{len(self.windows_data)})"
        if x_pos + len(counter_text) < width:
            stdscr.addstr(y_pos, x_pos, counter_text, curses.color_pair(2))

        return y_pos + 1

    def draw_window_details(self, stdscr, y_pos, height, width):
        """Draw the current window's process details."""
        if not self.windows_data:
            return y_pos

        # Ensure current_tab is within bounds
        if self.current_tab >= len(self.windows_data):
            self.current_tab = 0
        if self.current_tab < 0:
            self.current_tab = len(self.windows_data) - 1

        window = self.windows_data[self.current_tab]

        # Calculate available space - reserve space for window totals at bottom
        # We need: window header, table header, separator, and totals line at minimum
        min_required_lines = 4
        available_content_lines = height - y_pos - 2  # Leave space for footer

        if available_content_lines < min_required_lines:
            # Not enough space, show minimal info
            return y_pos

        # Window header with different colors for label, values, and separators
        window_parts = [
            ("Window", curses.color_pair(6) | curses.A_BOLD),
            (": ", curses.color_pair(3)),
            (window.name, curses.color_pair(2) | curses.A_BOLD),
            (f" ({window.index})", curses.color_pair(1) | curses.A_BOLD),
            (" - ", curses.color_pair(5)),
            (f"{len(window.pane_pids)}", curses.color_pair(1) | curses.A_BOLD),
            (" panes", curses.color_pair(2))
        ]
        
        current_x = 0
        for text, color in window_parts:
            if current_x + len(text) > width - 1:
                break
            try:
                stdscr.addstr(y_pos, current_x, text, color)
                current_x += len(text)
            except curses.error:
                break
        
        y_pos += 1

        # Process table header
        header = f"{'PID':>8} {'CPU%':>6} {'MEM':>12} COMMAND"
        stdscr.addstr(y_pos, 0, header, curses.color_pair(3) | curses.A_BOLD)
        y_pos += 1

        # Separator line
        separator = "-" * min(width - 1, 60)
        stdscr.addstr(y_pos, 0, separator, curses.color_pair(5))
        y_pos += 1

        # Calculate how many lines we can use for process list
        # Reserve 1 line for totals at the bottom
        lines_for_processes = (
            available_content_lines - 3
        )  # -3 for header, separator, totals

        # Ensure selected process index is within bounds
        if window.processes:
            if self.selected_process_index >= len(window.processes):
                self.selected_process_index = len(window.processes) - 1
            if self.selected_process_index < 0:
                self.selected_process_index = 0
        else:
            self.selected_process_index = 0
            self.process_browsing_active = False

        # Process list
        displayed_processes = 0
        first_displayed_process = 0
        
        # If browsing is active, try to keep selected process visible
        if self.process_browsing_active and window.processes:
            if self.selected_process_index >= lines_for_processes:
                first_displayed_process = self.selected_process_index - lines_for_processes + 1

        for process_idx, process in enumerate(window.processes):
            if process_idx < first_displayed_process:
                continue
            if displayed_processes >= lines_for_processes:
                break

            indent = "  " * process["depth"]
            mem_str = self.format_memory(process["memory_kb"])

            # Calculate available space for command
            fixed_width = (
                8 + 6 + 12 + 3 + len(indent)
            )  # PID + CPU + MEMORY + spaces + indent
            max_cmd_len = width - fixed_width - 1  # Leave 1 char margin

            command = process["command"]
            
            # Apply horizontal scroll if browsing is active
            if self.process_browsing_active and process_idx == self.selected_process_index:
                if len(command) > max_cmd_len:
                    command = command[self.horizontal_scroll_offset:self.horizontal_scroll_offset + max_cmd_len]
                    if self.horizontal_scroll_offset > 0:
                        command = "<<" + command[2:]
                    if self.horizontal_scroll_offset + max_cmd_len < len(process["command"]):
                        command = command[:-2] + ">>"
                else:
                    command = command[:max_cmd_len]
            else:
                # Only truncate if command is actually too long for the available space
                if len(command) > max_cmd_len and max_cmd_len > 3:
                    command = command[: max_cmd_len - 3] + "..."

            line = f"{process['pid']:>8} {process['cpu']:>6.1f} {mem_str:>12} {indent}{command}"
            # Final safety check - only truncate if line exceeds terminal width
            if len(line) > width - 1:
                line = line[: width - 4] + "..."

            # Determine color and styling
            is_selected = self.process_browsing_active and process_idx == self.selected_process_index
            color = curses.color_pair(1) if process['cpu'] > 10 else curses.color_pair(0)
            
            if is_selected:
                color = color | curses.A_REVERSE
            
            try:
                stdscr.addstr(y_pos, 0, line, color)
            except curses.error:
                break  # Stop if we can't draw more
            y_pos += 1
            displayed_processes += 1

        # Window totals - always show at bottom
        # Move to the line just before footer
        totals_y = height - 2

        window_ram_mb = window.ram_total // 1024
        window_ram_percent = (window.ram_total * 100) / (self.total_ram_mb * 1024)
        total_line = f"TOTAL: CPU {window.cpu_total:.1f}% | RAM {window_ram_mb}MB ({window_ram_percent:.1f}%) | Processes {window.process_count}"

        if len(total_line) > width - 1:
            total_line = total_line[:width-4] + "..."

        try:
            stdscr.addstr(totals_y, 0, total_line, curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

            return y_pos
 
        # Move to the line just before footer
        totals_y = height - 2
        # Reserve 1 line for totals at the bottom
        lines_for_processes = (
            available_content_lines - 3
        )  # -3 for header, separator, totals

        # Process list
        displayed_processes = 0

        for process in window.processes:
            if displayed_processes >= lines_for_processes:
                break

            indent = "  " * process["depth"]
            mem_str = self.format_memory(process["memory_kb"])

            # Calculate available space for command
            fixed_width = (
                8 + 6 + 12 + 3 + len(indent)
            )  # PID + CPU + MEMORY + spaces + indent
            max_cmd_len = width - fixed_width - 1  # Leave 1 char margin

            command = process["command"]
            # Only truncate if command is actually too long for the available space
            if len(command) > max_cmd_len and max_cmd_len > 3:
                command = command[: max_cmd_len - 3] + "..."

            line = f"{process['pid']:>8} {process['cpu']:>6.1f} {mem_str:>12} {indent}{command}"
            # Final safety check - only truncate if line exceeds terminal width
            if len(line) > width - 1:
                line = line[: width - 4] + "..."

            # Color based on CPU usage
            color = (
                curses.color_pair(1) if process["cpu"] > 10 else curses.color_pair(0)
            )
            try:
                stdscr.addstr(y_pos, 0, line, color)
            except curses.error:
                break  # Stop if we can't draw more
            y_pos += 1
            displayed_processes += 1

        # ? Move to the line just before footer
        totals_y = height - 2

        window_ram_mb = window.ram_total // 1024
        window_ram_percent = (window.ram_total * 100) / (self.total_ram_mb * 1024)
        # Build TOTAL line with different colors for labels, values, and separators
        total_parts = [
            ("TOTAL:", curses.color_pair(6) | curses.A_BOLD),
            (" CPU ", curses.color_pair(3)),
            (f"{window.cpu_total:.1f}%", curses.color_pair(1) | curses.A_BOLD),
            (" | ", curses.color_pair(5)),
            ("MEM ", curses.color_pair(3)),
            (f"{window_ram_mb}MB", curses.color_pair(1) | curses.A_BOLD),
            (f" ({window_ram_percent:.1f}%)", curses.color_pair(1) | curses.A_BOLD),
            (" | ", curses.color_pair(5)),
            ("Processes ", curses.color_pair(3)),
            (str(window.process_count), curses.color_pair(1) | curses.A_BOLD)
        ]
        
        full_total = "".join(part[0] for part in total_parts)
        
        current_x = 0
        for text, color in total_parts:
            if current_x + len(text) > width - 1:
                break
            try:
                stdscr.addstr(totals_y, current_x, text, color)
                current_x += len(text)
            except curses.error:
                break

        return y_pos

    def draw_footer(self, stdscr, height, width):
        """Draw the footer with refresh info."""
        footer = "Press 'q' to quit, '?' for help"
        stdscr.addstr(height - 1, 0, footer, curses.color_pair(5))

    def draw_help(self, stdscr, height, width):
        """Draw the help screen."""
        stdscr.erase()

        help_lines = [
            "Tmux Resource Monitor - Keyboard Controls",
            "",
            "Navigation:",
            "  <- -> or h l          Navigate between windows",
            "  q or Q                Exit the monitor",
            "  ?                     Show/hide this help screen",
            "",
            "Process Browsing (press j or down to start):",
            "  j/k or up/down        Navigate up/down through processes",
            "  Alt+h/l or Alt+<- ->  Scroll long command lines horizontally",
            "  x                     Send SIGTERM (15) to selected process",
            "  s                     Enter signal number to send custom signal",
            "  y                     Copy process command to clipboard",
            "  Y                     Copy process PID to clipboard",
            "  <- -> or h l          Navigate between windows (works in all modes)",
            "",
            "Display:",
            "  Header                Shows session name and total resource usage",
            "  Tabs                  Shows available windows (current window is highlighted)",
            "  Process List          Shows processes in the current window",
            "  Footer                Shows exit instructions",
            "",
            "Features:",
            "  • Session summary with total resource usage",
            "  • Interactive window navigation",
            "  • Process tree visualization for selected window",
            "  • Process selection and signal sending",
            "  • Real-time updates",
            "  • Lightweight curses-based interface",
            "",
            "Press any key to return to the monitor..."
        ]

        start_y = max(0, (height - len(help_lines)) // 2)

        for i, line in enumerate(help_lines):
            if start_y + i < height - 1:
                try:
                    if i == 0:
                        stdscr.addstr(start_y + i, (width - len(line)) // 2, line, curses.color_pair(3) | curses.A_BOLD)
                    else:
                        stdscr.addstr(start_y + i, 0, line, curses.color_pair(0))
                except curses.error:
                    pass

        stdscr.refresh()
    
    def draw_input_prompt(self, stdscr, height, width):
        """Draw input prompt for signal number."""
        if not self.windows_data:
            return
        
        window = self.windows_data[self.current_tab]
        if not window.processes or self.selected_process_index >= len(window.processes):
            return
        
        process = window.processes[self.selected_process_index]
        prompt = f"Send signal to PID {process['pid']}: [ {self.input_buffer} ]"
        
        # Draw prompt just above the footer
        prompt_y = height - 2
        
        try:
            # Clear the line first
            stdscr.move(prompt_y, 0)
            stdscr.clrtoeol()
            # Draw prompt
            stdscr.addstr(prompt_y, 0, prompt, curses.color_pair(3) | curses.A_BOLD)
            stdscr.move(prompt_y, len(prompt) - len(self.input_buffer) - 2)
            stdscr.refresh()
        except curses.error:
            pass

    def next_tab(self):
        """Switch to next tab."""
        if self.windows_data:
            self.current_tab = (self.current_tab + 1) % len(self.windows_data)

    def prev_tab(self):
        """Switch to previous tab."""
        if self.windows_data:
            self.current_tab = (self.current_tab - 1) % len(self.windows_data)
    
    def send_signal_to_process(self, signal_number):
        """Send a signal to the currently selected process."""
        if not self.windows_data:
            return False
        
        window = self.windows_data[self.current_tab]
        if not window.processes or self.selected_process_index >= len(window.processes):
            return False
        
        process = window.processes[self.selected_process_index]
        try:
            proc = psutil.Process(process['pid'])
            proc.send_signal(signal_number)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    def copy_to_clipboard(self, text):
        """Copy text to clipboard using available clipboard tools (Wayland/X11)."""
        def try_command(cmd):
            process = None
            try:
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL
                )
                stdout, stderr = process.communicate(input=text.encode('utf-8'))
                return process.returncode == 0
            except FileNotFoundError:
                return False
            except Exception as e:
                return False
        
        # Try wl-copy first (Wayland)
        if try_command(['wl-copy']):
            return True
        
        # Fallback to xclip (X11)
        if try_command(['xclip', '-selection', 'clipboard']):
            return True
        
        # Fallback to xsel (X11)
        if try_command(['xsel', '--clipboard', '--input']):
            return True
        
        return False
    
    def copy_process_command(self):
        """Copy the selected process's command to clipboard."""
        if not self.windows_data:
            return False
        
        window = self.windows_data[self.current_tab]
        if not window.processes or self.selected_process_index >= len(window.processes):
            return False
        
        process = window.processes[self.selected_process_index]
        return self.copy_to_clipboard(process['command'])
    
    def copy_process_pid(self):
        """Copy the selected process's PID to clipboard."""
        if not self.windows_data:
            return False
        
        window = self.windows_data[self.current_tab]
        if not window.processes or self.selected_process_index >= len(window.processes):
            return False
        
        process = window.processes[self.selected_process_index]
        return self.copy_to_clipboard(str(process['pid']))

    def handle_input(self, stdscr):
        """Handle keyboard input - no separate thread to avoid curses issues."""
        stdscr.nodelay(True)  # Non-blocking input

        try:
            key = stdscr.getch()
            if key != -1:  # Key was pressed
                # Handle Alt key combinations first
                if key == 27:  # ESC - could be Alt+key or just ESC
                    # Try to detect Alt+key by checking for another key quickly
                    stdscr.timeout(50)  # Short timeout to detect Alt
                    next_key = stdscr.getch()
                    stdscr.timeout(-1)  # Reset to blocking
                    stdscr.nodelay(True)  # Set back to non-blocking
                    
                    if next_key != -1:  # Alt+key combination
                        # Alt+key detected
                        alt_key = next_key
                        if self.process_browsing_active and self.windows_data:
                            window = self.windows_data[self.current_tab]
                            if window.processes and self.selected_process_index < len(window.processes):
                                process = window.processes[self.selected_process_index]
                                command = process['command']
                                
                                # Calculate available space for command
                                indent = "  " * process["depth"]
                                fixed_width = 8 + 6 + 12 + 3 + len(indent)
                                height, width = stdscr.getmaxyx()
                                max_cmd_len = width - fixed_width - 1
                                
                                if alt_key == curses.KEY_LEFT or alt_key == ord('h') or alt_key == ord('H'):
                                    # Scroll left
                                    self.horizontal_scroll_offset = max(0, self.horizontal_scroll_offset - 10)
                                elif alt_key == curses.KEY_RIGHT or alt_key == ord('l') or alt_key == ord('L'):
                                    # Scroll right
                                    max_offset = max(0, len(command) - max_cmd_len + 4)  # +4 for << and >>
                                    self.horizontal_scroll_offset = min(max_offset, self.horizontal_scroll_offset + 10)
                        return
                    # If we get here, it was just ESC, continue processing below
                
                # Handle input mode (signal number entry)
                if self.input_mode == 'signal':
                    if key == 10 or key == 13:  # Enter
                        if self.input_buffer.strip():
                            try:
                                signal_number = int(self.input_buffer.strip())
                                self.send_signal_to_process(signal_number)
                            except ValueError:
                                pass  # Invalid number, ignore
                        self.input_mode = None
                        self.input_buffer = ""
                    elif key == 27:  # ESC
                        self.input_mode = None
                        self.input_buffer = ""
                    elif key == curses.KEY_BACKSPACE or key == 127:
                        if self.input_buffer:
                            self.input_buffer = self.input_buffer[:-1]
                    elif 48 <= key <= 57:  # 0-9
                        self.input_buffer += chr(key)
                    return
                
                # Normal mode or process browsing mode
                if key == ord("q") or key == ord("Q"):
                    self.running = False
                elif key == ord("?"):
                    self.show_help = not self.show_help
                    if self.show_help:
                        self.draw_help(
                            stdscr, stdscr.getmaxyx()[0], stdscr.getmaxyx()[1]
                        )
                        stdscr.nodelay(False)
                        stdscr.getch()
                        stdscr.nodelay(True)
                        self.show_help = False
                elif key == curses.KEY_LEFT or key == ord("h") or key == ord("H"):
                    self.prev_tab()
                elif key == curses.KEY_RIGHT or key == ord("l") or key == ord("L"):
                    self.next_tab()
                elif key == ord("j") or key == curses.KEY_DOWN:
                    # Enter or continue process browsing mode
                    if self.windows_data and self.windows_data[self.current_tab].processes:
                        self.process_browsing_active = True
                        window = self.windows_data[self.current_tab]
                        if self.selected_process_index < len(window.processes) - 1:
                            self.selected_process_index += 1
                elif key == ord("k") or key == curses.KEY_UP:
                    # Move up in process browsing mode
                    if self.process_browsing_active and self.selected_process_index > 0:
                        self.selected_process_index -= 1
                elif key == ord("x") or key == ord("X"):
                    # Send SIGTERM to selected process
                    if self.process_browsing_active:
                        self.send_signal_to_process(15)  # SIGTERM
                elif key == ord("y"):
                    # Copy process command to clipboard
                    if self.process_browsing_active:
                        self.copy_process_command()
                elif key == ord("Y"):
                    # Copy process PID to clipboard
                    if self.process_browsing_active:
                        self.copy_process_pid()
                elif key == ord("s") or key == ord("S"):
                    # Enter signal input mode
                    if self.process_browsing_active:
                        self.input_mode = 'signal'
                        self.input_buffer = ""
                elif key == 3:  # Ctrl+C
                    self.running = False
        except curses.error:
            pass

    def run_curses(self, stdscr):
        """Main curses loop."""
        self.stdscr = stdscr
        curses.curs_set(0)  # Hide cursor
        self.init_colors()

        sessions = self.get_tmux_sessions()
        if self.session_name not in sessions:
            stdscr.clear()
            error_msg = f"Error: Session '{self.session_name}' not found"
            stdscr.addstr(0, 0, error_msg, curses.color_pair(4))
            stdscr.addstr(2, 0, "Available sessions:", curses.color_pair(3))
            for i, session in enumerate(sessions):
                if i + 3 < curses.LINES:
                    stdscr.addstr(i + 3, 2, session)
            stdscr.addstr(len(sessions) + 5, 0, "Press any key to exit...")
            stdscr.refresh()
            stdscr.getch()
            return

        stdscr.clear()
        height, width = stdscr.getmaxyx()
        loading_msg = "Loading tmux session data..."
        stdscr.addstr(
            height // 2,
            (width - len(loading_msg)) // 2,
            loading_msg,
            curses.color_pair(3) | curses.A_BOLD,
        )
        stdscr.refresh()

        for proc in psutil.process_iter(["pid"]):
            try:
                proc.cpu_percent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        self.collect_window_data()

        time.sleep(0.05)

        last_refresh = time.time()
        last_draw = 0

        while self.running:
            try:
                current_time = time.time()

                self.handle_input(stdscr)

                # Only refresh data if not in input mode
                if not self.input_mode and current_time - last_refresh >= self.refresh_rate:
                    self.collect_window_data()
                    last_refresh = current_time

                redraw_interval = 0.05 if current_time - last_refresh < 2 else 0.1
                if current_time - last_draw >= redraw_interval:
                    try:
                        height, width = stdscr.getmaxyx()

                        stdscr.erase()

                        # Draw interface
                        y_pos = self.draw_header(stdscr, height, width)
                        y_pos = self.draw_tabs(stdscr, y_pos, height, width)
                        self.draw_window_details(stdscr, y_pos, height, width)
                        
                        # Draw input prompt if in signal input mode
                        if self.input_mode == 'signal':
                            curses.curs_set(1)  # Show cursor
                            self.draw_input_prompt(stdscr, height, width)
                        else:
                            curses.curs_set(0)  # Hide cursor
                            self.draw_footer(stdscr, height, width)

                        # Refresh screen?
                        stdscr.refresh()
                        last_draw = current_time

                    except curses.error:
                        # Terminal might be resizing?
                        time.sleep(0.1)
                        continue

                time.sleep(0.05)  # Responsive interface

            except KeyboardInterrupt:
                break

    def run(self):
        """Run the monitor."""
        try:
            curses.wrapper(self.run_curses)
        except KeyboardInterrupt:
            pass
        finally:
            print("Monitoring stopped.")


def read_tmux_option(option, default=""):
    """Read a tmux option value."""
    try:
        result = subprocess.run(
            ["tmux", "show-option", "-gqv", f"@{option}"],
            capture_output=True,
            text=True,
        )
        if result.stdout and result.stdout.strip():
            return result.stdout.strip()
        return default
    except (subprocess.CalledProcessError, FileNotFoundError):
        return default


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, signal_handler)

    parser = argparse.ArgumentParser(
        description="Lightweight tmux resource monitor using curses",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s blog                    # Monitor session 'blog'
  %(prog)s blog -w editor          # Monitor session 'blog', start on 'editor' window
  %(prog)s blog -r 1.0             # Refresh every 1 second
  %(prog)s blog -w editor -r 0.5   # Start on 'editor' window, refresh every 0.5s

Note: When used as a tmux plugin, options can also be set via .tmux.conf:
  set -g @tmux_resource_monitor_refresh_rate "2.0"
  set -g @tmux_resource_monitor_width "80%"
  set -g @tmux_resource_monitor_height "40%"

Press '?' in the monitor for keyboard controls.

Features:
  • Session summary with total resource usage
  • Interactive window navigation
  • Process tree visualization for selected window
  • Real-time updates
  • Lightweight curses-based interface
  • Works standalone or as tmux plugin
        """
    )

    parser.add_argument("session_name", help="Name of the tmux session to monitor", default=None)

    parser.add_argument(
        "-w",
        "--window",
        dest="window_filter",
        help="Start monitoring on specific window name",
        default=None,
    )

    parser.add_argument(
        "-r",
        "--refresh-rate",
        type=float,
        default=None,
        help="Refresh rate in seconds (default: 2.0)",
    )

    parser.add_argument(
        "--key",
        dest="key",
        help="Keybinding to open monitor (default: t)",
        default=None,
    )

    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List available tmux sessions and exit",
    )

    args = parser.parse_args()

    if args.list_sessions:
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
                check=True,
            )
            sessions = (
                result.stdout.strip().split("\n") if result.stdout.strip() else []
            )
            if sessions:
                print("Available tmux sessions:")
                for session in sessions:
                    print(f"  {session}")
            else:
                print("No tmux sessions found")
        except subprocess.CalledProcessError:
            print("Error: Could not list tmux sessions. Is tmux running?")
        return

    # Determine session name (CLI arg or tmux option)
    session_name = args.session_name
    if not session_name:
        # Try to read from tmux environment if available
        session_name = os.environ.get('TMUX_SESSION_NAME', None)

    # Determine window filter (CLI arg or tmux option)
    window_filter = args.window_filter
    if not window_filter:
        window_filter = read_tmux_option('tmux_resource_monitor_window_filter')
        if not window_filter:
            window_filter = None

    # Determine refresh rate (CLI arg or tmux option)
    refresh_rate = args.refresh_rate
    if refresh_rate is None:
        refresh_rate_str = read_tmux_option('tmux_resource_monitor_refresh_rate')
        if not refresh_rate_str:
            refresh_rate_str = "2.0"
        try:
            refresh_rate = float(refresh_rate_str)
        except ValueError:
            refresh_rate = 2.0

    if refresh_rate <= 0:
        print("Error: Refresh rate must be positive")
        sys.exit(1)

    monitor = TmuxResourceMonitor(
        session_name, window_filter, refresh_rate
    )

    monitor.run()


if __name__ == "__main__":
    main()

