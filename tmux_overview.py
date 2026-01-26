#!/usr/bin/env python3
"""
tmux-resource-monitor-overview.py - System-wide tmux resource overview using ncurses
"""

import argparse
import curses
import subprocess
import time
from dataclasses import dataclass
from typing import List
import psutil


@dataclass
class SessionStats:
    name: str
    cpu_total: float
    ram_total: int
    process_count: int
    window_count: int


class TmuxOverviewMonitor:
    def __init__(self, refresh_rate=2.0):
        self.refresh_rate = refresh_rate
        self.total_ram_mb = psutil.virtual_memory().total // (1024 * 1024)
        self.running = True
        self.stdscr = None
        self.colors_initialized = False
        self.browse_sessions = False
        self.selected_session_index = 0
        self.sessions_data: List[SessionStats] = []
        self.system_cpu_percent = 0.0
        self.system_memory_percent = 0.0
        self.system_memory_mb = 0
        self.tmux_cpu_percent = 0.0
        self.tmux_memory_mb = 0
        self.tmux_memory_percent = 0.0
        self.cpu_warmup_done = False
        self.last_cpu_measurements = {}

    def warmup_cpu_async(self):
        """Start async CPU warmup in background to establish baseline."""
        import threading
        def do_warmup():
            time.sleep(0.1)
            sessions = self.get_tmux_sessions()
            for session_name in sessions:
                pane_pids = self.get_session_pane_pids(session_name)
                for pid in pane_pids:
                    try:
                        proc = psutil.Process(pid)
                        times = proc.cpu_times()
                        self.last_cpu_measurements[pid] = (time.time(), times)
                        for child in proc.children(recursive=True):
                            try:
                                child_times = child.cpu_times()
                                self.last_cpu_measurements[child.pid] = (time.time(), child_times)
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        if pid in self.last_cpu_measurements:
                            del self.last_cpu_measurements[pid]
            self.cpu_warmup_done = True
        thread = threading.Thread(target=do_warmup, daemon=True)
        thread.start()

    def get_cpu_percent(self, pid, update_baseline=False):
        """Get CPU percent using cpu_times() for accurate measurements."""
        try:
            proc = psutil.Process(pid)
            current_times = proc.cpu_times()
            current_time = time.time()

            if pid in self.last_cpu_measurements:
                last_time, last_times = self.last_cpu_measurements[pid]
                elapsed = current_time - last_time

                if elapsed > 0.1:
                    last_cpu = last_times.user + last_times.system
                    current_cpu = current_times.user + current_times.system
                    cpu_diff = current_cpu - last_cpu
                    percent = (cpu_diff / elapsed) * 100
                    if update_baseline:
                        self.last_cpu_measurements[pid] = (current_time, current_times)
                    return percent
                else:
                    return 0.0

            if update_baseline:
                self.last_cpu_measurements[pid] = (current_time, current_times)
            return 0.0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0

    def init_colors(self):
        """Initialize color pairs for curses."""
        if not self.colors_initialized and curses.has_colors():
            curses.start_color()
            curses.use_default_colors()

            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_CYAN, -1)
            curses.init_pair(4, curses.COLOR_RED, -1)
            curses.init_pair(5, curses.COLOR_BLUE, -1)
            curses.init_pair(6, curses.COLOR_MAGENTA, -1)
            curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLACK)
            curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_RED)

            self.colors_initialized = True

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

    def get_session_window_count(self, session_name):
        """Get the number of windows in a session."""
        try:
            result = subprocess.run(
                ["tmux", "list-windows", "-t", session_name, "-F", "#{window_index}"],
                capture_output=True,
                text=True,
                check=True,
            )
            windows = result.stdout.strip().split("\n") if result.stdout.strip() else []
            return len([w for w in windows if w])
        except subprocess.CalledProcessError:
            return 0

    def get_session_pane_pids(self, session_name):
        """Get all pane PIDs for a session."""
        pids = []
        try:
            windows_result = subprocess.run(
                ["tmux", "list-windows", "-t", session_name, "-F", "#{window_index}"],
                capture_output=True,
                text=True,
                check=True,
            )
            for window_idx in windows_result.stdout.strip().split("\n"):
                if not window_idx:
                    continue
                try:
                    panes_result = subprocess.run(
                        ["tmux", "list-panes", "-t", f"{session_name}:{window_idx}", "-F", "#{pane_pid}"],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    for pid_str in panes_result.stdout.strip().split("\n"):
                        if pid_str.strip():
                            try:
                                pids.append(int(pid_str.strip()))
                            except ValueError:
                                continue
                except subprocess.CalledProcessError:
                    continue
        except subprocess.CalledProcessError:
            pass
        return pids

    def collect_all_sessions_stats(self):
        """Collect stats for all tmux sessions."""
        sessions = self.get_tmux_sessions()
        self.sessions_data = []

        for session_name in sessions:
            try:
                pane_pids = self.get_session_pane_pids(session_name)
                window_count = self.get_session_window_count(session_name)

                session_cpu = 0.0
                session_ram = 0
                session_process_count = 0

                for pid in pane_pids:
                    try:
                        proc = psutil.Process(pid)
                        session_cpu += self.get_cpu_percent(pid)
                        session_ram += proc.memory_info().rss // 1024
                        session_process_count += 1
                        for child in proc.children(recursive=True):
                            try:
                                session_cpu += self.get_cpu_percent(child.pid)
                                session_ram += child.memory_info().rss // 1024
                                session_process_count += 1
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                self.sessions_data.append(SessionStats(
                    name=session_name,
                    cpu_total=session_cpu,
                    ram_total=session_ram,
                    process_count=session_process_count,
                    window_count=window_count
                ))
            except Exception:
                continue

        self.sessions_data.sort(key=lambda x: x.cpu_total, reverse=True)

    def collect_system_stats(self):
        """Collect system-wide resource usage."""
        try:
            self.system_cpu_percent = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            self.system_memory_percent = mem.percent
            self.system_memory_mb = mem.used // (1024 * 1024)
        except Exception:
            self.system_cpu_percent = 0.0
            self.system_memory_percent = 0.0
            self.system_memory_mb = 0

        self.collect_all_sessions_stats()

        total_tmux_cpu = 0.0
        total_tmux_ram = 0
        for session in self.sessions_data:
            total_tmux_cpu += session.cpu_total
            total_tmux_ram += session.ram_total

        self.tmux_cpu_percent = total_tmux_cpu
        self.tmux_memory_mb = total_tmux_ram // 1024
        self.tmux_memory_percent = (
            (total_tmux_ram * 100) / (self.total_ram_mb * 1024)
            if self.total_ram_mb > 0 else 0
        )

    def draw(self, stdscr, height, width):
        """Draw the overview screen."""
        y_pos = 0

        title = "System Resource Overview"
        x_pos = max(0, (width - len(title)) // 2)
        stdscr.addstr(y_pos, x_pos, title, curses.color_pair(3) | curses.A_BOLD)
        y_pos += 2

        stdscr.addstr(y_pos, 7, "CPU", curses.color_pair(7))
        stdscr.addstr(y_pos, 20, "MEM", curses.color_pair(7))
        y_pos += 1

        stdscr.addstr(y_pos, 0, "Tmux  ", curses.color_pair(2) | curses.A_BOLD)
        stdscr.addstr(y_pos, 7, f"{self.tmux_cpu_percent:>5.1f}%", curses.color_pair(4) | curses.A_BOLD)
        stdscr.addstr(y_pos, 20, f"{self.tmux_memory_mb:>6d} MB ({self.tmux_memory_percent:>4.1f}%)", curses.color_pair(4) | curses.A_BOLD)
        y_pos += 1

        stdscr.addstr(y_pos, 0, "System", curses.color_pair(2) | curses.A_BOLD)
        stdscr.addstr(y_pos, 7, f"{self.system_cpu_percent:>5.1f}%", curses.color_pair(1))
        stdscr.addstr(y_pos, 20, f"{self.system_memory_mb:>6d} MB ({self.system_memory_percent:>4.1f}%)", curses.color_pair(1))
        y_pos += 2

        separator = "-" * (width - 1)
        stdscr.addstr(y_pos, 0, separator, curses.color_pair(5))
        y_pos += 1

        header = f"{'Session':<20} {'CPU%':>8} {'MEM':>12} {'Procs':>7} {'Wins':>6}"
        stdscr.addstr(y_pos, 0, header, curses.color_pair(3) | curses.A_BOLD)
        y_pos += 1

        stdscr.addstr(y_pos, 0, separator, curses.color_pair(5))
        y_pos += 1

        if not self.sessions_data:
            no_sessions = "No tmux sessions found"
            x_pos = max(0, (width - len(no_sessions)) // 2)
            stdscr.addstr(y_pos + 1, x_pos, no_sessions, curses.color_pair(2))
            return

        if self.selected_session_index >= len(self.sessions_data):
            self.selected_session_index = 0
        if self.selected_session_index < 0:
            self.selected_session_index = len(self.sessions_data) - 1

        available_lines = height - y_pos - 2
        first_displayed = 0
        if self.browse_sessions and self.sessions_data:
            if self.selected_session_index >= available_lines:
                first_displayed = self.selected_session_index - available_lines + 1

        for idx, session in enumerate(self.sessions_data):
            line_idx = idx - first_displayed
            if line_idx < 0:
                continue
            if line_idx >= available_lines:
                break

            current_y = y_pos + line_idx

            ram_mb = session.ram_total // 1024
            ram_percent = (session.ram_total * 100) / (self.total_ram_mb * 1024) if self.total_ram_mb > 0 else 0

            is_selected = self.browse_sessions and idx == self.selected_session_index

            row = f"{session.name[:19]:<20} {session.cpu_total:>7.1f}% {ram_mb:>6d}MB({ram_percent:>4.1f}%) {session.process_count:>7} {session.window_count:>6}"

            if is_selected:
                color = curses.color_pair(1) | curses.A_REVERSE
            elif session.cpu_total > 10:
                color = curses.color_pair(4)
            else:
                color = curses.color_pair(0)

            try:
                stdscr.addstr(current_y, 0, row[:width-1], color)
            except curses.error:
                pass

    def handle_input(self, stdscr):
        """Handle keyboard input."""
        stdscr.nodelay(True)

        try:
            key = stdscr.getch()
            if key == -1:
                return

            if key == ord("q") or key == ord("Q"):
                self.running = False
            elif key == 3:
                self.running = False
            elif key == ord("j") or key == curses.KEY_DOWN:
                self.browse_sessions = True
                if self.selected_session_index < len(self.sessions_data) - 1:
                    self.selected_session_index += 1
                else:
                    self.selected_session_index = 0
            elif key == ord("k") or key == curses.KEY_UP:
                self.browse_sessions = True
                if self.selected_session_index > 0:
                    self.selected_session_index -= 1
                elif self.sessions_data:
                    self.selected_session_index = len(self.sessions_data) - 1
            elif key == 10 or key == 13:
                if self.sessions_data and self.selected_session_index < len(self.sessions_data):
                    selected = self.sessions_data[self.selected_session_index]
                    self.running = False
                    import os
                    os.execv("/usr/bin/python3", ["python3", f"{os.path.dirname(os.path.abspath(__file__))}/tmux_monitor.py", selected.name])
            elif key == 27:
                self.running = False

        except curses.error:
            pass

    def run_curses(self, stdscr):
        """Main curses loop."""
        self.stdscr = stdscr
        curses.curs_set(0)
        self.init_colors()

        stdscr.clear()
        height, width = stdscr.getmaxyx()
        loading_msg = "Loading system and tmux session data..."
        stdscr.addstr(
            height // 2,
            (width - len(loading_msg)) // 2,
            loading_msg,
            curses.color_pair(3) | curses.A_BOLD,
        )
        stdscr.refresh()

        self.collect_system_stats()
        self.warmup_cpu_async()
        time.sleep(0.15)

        last_refresh = 0

        last_draw = 0

        while self.running:
            try:
                current_time = time.time()

                self.handle_input(stdscr)

                if current_time - last_refresh >= self.refresh_rate:
                    self.collect_system_stats()
                    last_refresh = current_time

                redraw_interval = 0.05 if current_time - last_refresh < 2 else 0.1
                if current_time - last_draw >= redraw_interval:
                    try:
                        height, width = stdscr.getmaxyx()
                        stdscr.erase()
                        self.draw(stdscr, height, width)

                        curses.curs_set(0)
                        footer = "q=quit | j/k or up/down=browse | Enter=view session"
                        if width > len(footer):
                            stdscr.addstr(height - 1, 0, footer, curses.color_pair(5))
                        else:
                            stdscr.addstr(height - 1, 0, "q=quit j/k=browse Enter=view", curses.color_pair(5))

                        stdscr.refresh()
                        last_draw = current_time

                    except curses.error:
                        time.sleep(0.1)
                        continue

                time.sleep(0.05)

            except KeyboardInterrupt:
                break

    def run(self):
        """Run the monitor."""
        try:
            curses.wrapper(self.run_curses)
        except KeyboardInterrupt:
            pass
        finally:
            print("Overview stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="System-wide tmux resource overview using curses",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Run overview with default settings
  %(prog)s -r 1.0             # Refresh every 1 second

Press '?' in the monitor for keyboard controls.
        """
    )

    parser.add_argument(
        "-r",
        "--refresh-rate",
        type=float,
        default=2.0,
        help="Refresh rate in seconds (default: 2.0)",
    )

    args = parser.parse_args()

    if args.refresh_rate <= 0:
        print("Error: Refresh rate must be positive")
        return

    monitor = TmuxOverviewMonitor(refresh_rate=args.refresh_rate)
    monitor.run()


if __name__ == "__main__":
    main()
