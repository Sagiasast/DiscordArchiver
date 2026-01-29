#!/usr/bin/env python3
"""
Discord Archive CLI - Cross-platform helper script
Works on Windows, Linux, and macOS


Flags supported:
  --include-bots          Include bot-authored messages in the archive (default: off)
  --download-attachments  Download images/files locally (default: off)
  --limit N               Limit messages per channel (default: unlimited)
  --channel NAME/ID       Only archive specific channel (can repeat)
  --delay N               Delay N seconds between API batches (default: 0)
"""

import subprocess
import sys
import os
import signal
from pathlib import Path
import webbrowser
import time
from typing import Optional, List, Tuple

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, ProgressColumn
from rich.panel import Panel
from rich.align import Align
from rich.text import Text
from rich.spinner import Spinner

# Configuration
SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_ARCHIVE_PATH = SCRIPT_DIR / "discord_archive"
DEFAULT_HTML_PATH = SCRIPT_DIR / "discord_html"
DEFAULT_PORT = 8000
PID_FILE = SCRIPT_DIR / ".archiver.pid"
LOG_FILE = SCRIPT_DIR / "archiver.log"
ENV_FILE = SCRIPT_DIR / ".env"
SETTINGS_FILE = SCRIPT_DIR / ".archiver.settings.json"

# Initialize rich console
console = Console()

# -----------------------------
# Rich printing helpers
# -----------------------------
def print_header():
    console.print(
        Panel.fit(
            "[bold blue]Discord Server Archiver[/bold blue]\n",
            border_style="bright_blue",
            padding=(0, 4)
        )
    )
    console.print()


def print_success(msg: str):
    console.print(f"[green]✓[/green] {msg}")


def print_error(msg: str):
    console.print(f"[red]✗[/red] {msg}")


def print_warning(msg: str):
    console.print(f"[yellow]![/yellow] {msg}")


def print_info(msg: str):
    console.print(f"[blue]→[/blue] {msg}")


def print_step(step: str, msg: str):
    console.print(f"[cyan][{step}][/cyan] {msg}")


class LiveOnlySpinnerColumn(ProgressColumn):
    def __init__(self, live_task_id_getter):
        super().__init__()
        self._get_live_task_id = live_task_id_getter
        self._spinner = Spinner("dots")

    def render(self, task):
        live_id = self._get_live_task_id()
        if live_id is not None and task.id == live_id and not task.finished:
            return self._spinner.render(task.get_time())
        # archived/static tasks: show a check
        return Text("✓", style="green")

# -----------------------------
# Env helpers
# -----------------------------
def load_env():
    """Load environment variables from .env file"""
    env = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()
    return env


def get_env(key, default=None):
    """Get environment variable from .env or use default"""
    env = load_env()
    return env.get(key, default)


def get_python_cmd():
    """Get the Python command for this system"""
    return sys.executable


# -----------------------------
# Interactive wizard (questionary)
# -----------------------------
def _require_questionary():
    try:
        import questionary  
    except ImportError:
        print_error("Missing dependency: questionary")
        print_info("Run: pip install questionary")
        sys.exit(1)


def prompt_start_options_interactive() -> Tuple[bool, bool, Optional[str], List[str], Optional[str]]:
    """
    Firebase-init style flow:
      - checkbox toggles
      - prompts for values
      - summary + confirm
    Returns:
      include_bots, download_attachments, message_limit, channel_filter, api_delay
    """
    _require_questionary()
    import questionary  # type: ignore

    console.print(
        Panel.fit(
            "[bold]Interactive setup[/bold]\n"
            "Use ↑/↓ to move, Space to toggle, Enter to confirm.\n"
            "Ctrl+C to cancel.",
            border_style="cyan",
        )
    )
    console.print()

    selections = questionary.checkbox(
        "Select options:",
        choices=[
            questionary.Choice(
                "Include bot-authored messages (--include-bots)",
                checked=False,
                value="include_bots",
            ),
            questionary.Choice(
                "Download attachments (--download-attachments)",
                checked=False,
                value="download_attachments",
            ),
        ],
    ).ask()

    if selections is None:
        raise KeyboardInterrupt

    include_bots = "include_bots" in selections
    download_attachments = "download_attachments" in selections

    message_limit = questionary.text(
        "Message limit per channel? (leave blank for unlimited)",
        validate=lambda t: True if (t.strip() == "" or t.strip().isdigit()) else "Enter a whole number or leave blank",
    ).ask()
    if message_limit is None:
        raise KeyboardInterrupt
    message_limit = message_limit.strip() or None

    channel_input = questionary.text(
        "Channels to archive (comma-separated names/IDs). Leave blank for all channels.",
    ).ask()
    if channel_input is None:
        raise KeyboardInterrupt

    channel_filter: List[str] = []
    channel_input = channel_input.strip()
    if channel_input:
        channel_filter = [c.strip() for c in channel_input.split(",") if c.strip()]

    api_delay = questionary.text(
        "API delay seconds between API batches? (leave blank for 0)",
        default="0",
        validate=lambda t: True if (t.strip().isdigit()) else "Enter a whole number (0, 1, 2...)",
    ).ask()
    if api_delay is None:
        raise KeyboardInterrupt
    api_delay = api_delay.strip() or "0"
    if api_delay == "0":
        api_delay = None  # keep existing logic: only add --delay if set

    summary = (
        f"Include bots: {include_bots}\n"
        f"Download attachments: {download_attachments}\n"
        f"Limit: {message_limit or 'unlimited'}\n"
        f"Channels: {', '.join(channel_filter) if channel_filter else 'all'}\n"
        f"Delay: {api_delay or '0'}"
    )
    ok = questionary.confirm(f"Run with these settings?\n\n{summary}", default=True).ask()
    if ok is None:
        raise KeyboardInterrupt
    if not ok:
        raise KeyboardInterrupt

    return include_bots, download_attachments, message_limit, channel_filter, api_delay


# -----------------------------
# Setup command
# -----------------------------
def cmd_setup():
    """Install dependencies and create .env file"""
    print_header()

    # Check Python version
    version = sys.version_info
    print_success(f"Python {version.major}.{version.minor}.{version.micro} found")

    # Install dependencies with progress
    req_file = SCRIPT_DIR / "requirements.txt"

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        if req_file.exists():
            task = progress.add_task("[cyan]Installing dependencies...", total=100)
            progress.update(task, advance=20)
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"])
            progress.update(task, advance=80)
            print_success("Dependencies installed")
        else:
            task = progress.add_task("[cyan]Installing discord.py...", total=100)
            progress.update(task, advance=20)
            subprocess.run([sys.executable, "-m", "pip", "install", "discord.py", "rich", "questionary", "-q"])
            progress.update(task, advance=80)
            print_success("discord.py, rich, and questionary installed")

    # Create .env file
    print_info("Setting up environment...")

    if not ENV_FILE.exists():
        env_content = """# Discord Archive Configuration

# Your Discord bot token (required for archiving)
DISCORD_BOT_TOKEN=your_bot_token_here

# Archive update interval in hours (0 to disable auto-update)
UPDATE_INTERVAL_HOURS=24

# Path to store archived data
ARCHIVE_PATH=./discord_archive

# Path for generated HTML output
HTML_OUTPUT_PATH=./discord_html

# Web server port for viewing archive
SERVER_PORT=8000
"""
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write(env_content)
        print_warning("Created .env file")
        print_warning("Please edit .env and add your Discord bot token")
    else:
        print_success("Environment file exists")

    console.print()
    print_success("Setup complete!")
    print_info("Next steps:")
    console.print("  1. Edit .env and add your Discord bot token")
    console.print("  2. Run 'python run.py start' to start archiving (interactive wizard)")
    console.print("  3. Run 'python run.py view' to generate and view the archive")


# -----------------------------
# Process management
# -----------------------------
def is_archiver_running():
    """Check if archiver process is running"""
    if not PID_FILE.exists():
        return False

    try:
        pid = int(PID_FILE.read_text().strip())

        # Check if process exists
        if sys.platform == "win32":
            result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
            if str(pid) in result.stdout:
                return True
        else:
            os.kill(pid, 0)
            return True
    except (ValueError, OSError, ProcessLookupError):
        pass

    PID_FILE.unlink(missing_ok=True)
    return False


# -----------------------------
# Flag parsing helpers
# -----------------------------
def _has_flag(flag: str) -> bool:
    """True if CLI flag is present anywhere after the command."""
    return flag in sys.argv[2:]


def _get_flag_value(flag: str) -> Optional[str]:
    """Get the value following a flag (e.g., --limit 100 returns '100')"""
    args = sys.argv[2:]
    if flag in args:
        try:
            idx = args.index(flag)
            return args[idx + 1]
        except IndexError:
            return None
    return None


def _get_flag_values(flag: str) -> List[str]:
    """Get all values for a repeatable flag (e.g., --channel general --channel random)"""
    args = sys.argv[2:]
    values: List[str] = []
    i = 0
    while i < len(args):
        if args[i] == flag:
            try:
                values.append(args[i + 1])
                i += 2
            except IndexError:
                i += 1
        else:
            i += 1
    return values


def save_archiver_settings(settings: dict):
    import json
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print_warning(f"Could not save settings: {e}")


def load_archiver_settings() -> Optional[dict]:
    import json
    if not SETTINGS_FILE.exists():
        return None
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# -----------------------------
# Start archiver (background)
# -----------------------------
def cmd_start():
    """Start archiver in background with progress display"""
    print_header()

    token = get_env("DISCORD_BOT_TOKEN", "your_bot_token_here")
    if token == "your_bot_token_here":
        print_error("DISCORD_BOT_TOKEN not set in .env")
        print_info("Edit .env and add your bot token, then run this command again")
        sys.exit(1)

    if is_archiver_running():
        pid = PID_FILE.read_text().strip()
        print_warning(f"Archiver is already running (PID: {pid})")
        return

    archive_path = get_env("ARCHIVE_PATH", str(DEFAULT_ARCHIVE_PATH))
    interval = get_env("UPDATE_INTERVAL_HOURS", "24")

    # If user ran: python run.py start  (no extra args) => interactive wizard
    if len(sys.argv) <= 2:
        include_bots, download_attachments, message_limit, channel_filter, api_delay = prompt_start_options_interactive()
    else:
        include_bots = _has_flag("--include-bots")
        message_limit = _get_flag_value("--limit")
        channel_filter = _get_flag_values("--channel")
        download_attachments = _has_flag("--download-attachments")
        api_delay = _get_flag_value("--delay")

    print_info("Starting Discord archiver...")
    print_success(f"Include bots: {include_bots}")
    if message_limit:
        print_success(f"Message limit: {message_limit} per channel")
    if channel_filter:
        print_success(f"Channel filter: {', '.join(channel_filter)}")
    if download_attachments:
        print_success("Download attachments: enabled")
    if api_delay:
        print_success(f"API delay: {api_delay}s between batches")

    archiver_script = SCRIPT_DIR / "discord_archiver.py"

    cmd = [sys.executable, "-u", str(archiver_script), token, interval, archive_path]
    if include_bots:
        cmd.append("--include-bots")
    if message_limit:
        cmd.extend(["--limit", message_limit])
    for channel in channel_filter:
        cmd.extend(["--channel", channel])
    if download_attachments:
        cmd.append("--download-attachments")
    if api_delay:
        cmd.extend(["--delay", api_delay])

    # Clear log file and start process
    with open(LOG_FILE, "w", encoding="utf-8") as log:
        log.write("")

    if sys.platform == "win32":
        with open(LOG_FILE, "a", encoding="utf-8") as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            )
    else:
        with open(LOG_FILE, "a", encoding="utf-8") as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    PID_FILE.write_text(str(process.pid))

    time.sleep(1)

    if not is_archiver_running():
        print_error("Archiver failed to start. Check archiver.log for details")
        sys.exit(1)

    print_success(f"Archiver started (PID: {process.pid})")
    console.print()

    current_server = None
    current_channel = None
    archived_messages = 0
    channels_done = 0
    archive_complete = False

    live_task_id = None
    def get_live_task_id():
        return live_task_id

    with Progress(
        LiveOnlySpinnerColumn(get_live_task_id),
        TextColumn("{task.description}"),
        console=console,
        transient=False,
    ) as progress:
        
        live_task_id = progress.add_task("[cyan]Waiting for bot to connect...", total=None)

        try:
            with open(LOG_FILE, "r", encoding="utf-8") as log:
                while is_archiver_running() and not archive_complete:
                    line = log.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    line = line.strip()
                    if not line:
                        continue

                    parsed = parse_archiver_line(line)
                    if not parsed:
                        continue

                    t = parsed["type"]

                    if t == "logged_in":
                        progress.update(live_task_id, description="[cyan]Bot connected, waiting for archive...")

                    elif t == "server_start":
                        current_server = parsed["name"]
                        progress.update(live_task_id, description=f"[cyan]Archiving: {current_server}")

                    elif t == "channel_start":
                        current_channel = parsed["name"]
                        progress.update(live_task_id, description=f"[cyan]Archiving: {current_server} #{current_channel}")

                    elif t == "progress":
                        progress.update(
                            live_task_id,
                            description=f"[cyan]Archiving: {current_server} #{parsed['channel']} [{parsed['count']:,} msgs]"
                        )

                    elif t == "channel_done":
                        channels_done += 1
                        archived_messages += parsed["count"]

                        # Add archived line (will appear ABOVE the live line)
                        progress.add_task(
                            f"[green]Archived:[/green] {current_server} #{parsed['name']} [{parsed['count']:,} msgs]",
                            total=1,
                            completed=1,
                        )

                        # Keep live line ready for next channel
                        progress.update(live_task_id, description=f"[cyan]Archiving: {current_server}")

                    elif t in ("server_done", "archive_done"):
                        archive_complete = True

                # Remove live line and add final line LAST
                progress.remove_task(live_task_id)
                live_task_id = None  # so spinner column won't try to spin anything

                progress.add_task(
                    f"[green]Archive complete![/green] {archived_messages:,} messages archived",
                    total=1,
                    completed=1,
                )

        except KeyboardInterrupt:
            console.print()
            print_info("Progress display stopped (archiver continues in background)")


    console.print()
    if archive_complete:
        print_success(f"Initial archive complete: {archived_messages:,} messages from {channels_done} channels")
        settings_snapshot = {
            "archive_path": archive_path,
            "update_interval_hours": interval,
            "include_bots": include_bots,
            "download_attachments": download_attachments,
            "limit": message_limit,              
            "channels": channel_filter,          
            "delay": api_delay,                  
        }
        save_archiver_settings(settings_snapshot)

    print_info(f"Archiver running in background (PID: {process.pid})")
    print_info(f"Next auto-update in {interval} hours")
    print_info("Use 'python run.py stop' to stop the archiver")
    print_info("Use 'python run.py status' to see archieve status and settings")


# -----------------------------
# Stop archiver
# -----------------------------
def cmd_stop():
    """Stop background archiver"""
    print_header()

    if not is_archiver_running():
        print_warning("Archiver is not running")
        return

    pid = int(PID_FILE.read_text().strip())
    print_info(f"Stopping archiver (PID: {pid})...")

    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass

    PID_FILE.unlink(missing_ok=True)
    print_success("Archiver stopped")


# -----------------------------
# Metadata / log parsing
# -----------------------------
def load_metadata(archive_path=None):
    """Load metadata.json to get total message counts"""
    import json

    if archive_path is None:
        archive_path = Path(get_env("ARCHIVE_PATH", str(DEFAULT_ARCHIVE_PATH)))
    else:
        archive_path = Path(archive_path)

    metadata_file = archive_path / "metadata.json"
    if metadata_file.exists():
        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print_warning(f"Could not load metadata: {e}")
    return None


def parse_archiver_line(line: str):
    """Parse archiver log line to extract progress info"""
    import re

    # Match: "Archiving server: ServerName (ID: 123)"
    server_match = re.search(r"Archiving server: (.+?) \(ID:", line)
    if server_match:
        return {"type": "server_start", "name": server_match.group(1)}

    # Match: "Archiving channel: #channelname"
    channel_start = re.search(r"Archiving channel: #(.+)$", line)
    if channel_start:
        return {"type": "channel_start", "name": channel_start.group(1)}

    # Match: "Archived 100 new messages from #channelname"
    progress_match = re.search(r"Archived (\d+) new messages from #(.+)$", line)
    if progress_match:
        return {"type": "progress", "count": int(progress_match.group(1)), "channel": progress_match.group(2)}

    # Match: "Channel archived: #channelname (123 new messages)"
    channel_done = re.search(r"Channel archived:\s+#(?P<name>[^ ]+)\s+\((?P<count>\d+)\s+new messages",line)
    # if channel_done:
    if channel_done:
        return {"type": "channel_done","name": channel_done.group("name"),"count": int(channel_done.group("count"))}

    # Match: "Server archive completed: ServerName"
    server_done = re.search(r"Server archive completed: (.+)$", line)
    if server_done:
        return {"type": "server_done", "name": server_done.group(1)}

    # Match: "Automatic archive update completed"
    if "archive update completed" in line.lower():
        return {"type": "archive_done"}

    # Match: "Logged in as BotName"
    if "Logged in as" in line:
        return {"type": "logged_in"}

    return None


# -----------------------------
# Run archiver (foreground)
# -----------------------------
def cmd_archive():
    """Run archiver in foreground (blocking) with progress display"""
    print_header()

    token = get_env("DISCORD_BOT_TOKEN", "your_bot_token_here")
    if token == "your_bot_token_here":
        print_error("DISCORD_BOT_TOKEN not set in .env")
        sys.exit(1)

    archive_path = get_env("ARCHIVE_PATH", str(DEFAULT_ARCHIVE_PATH))
    interval = get_env("UPDATE_INTERVAL_HOURS", "24")

    include_bots = _has_flag("--include-bots")

    print_info("Starting Discord archiver (press Ctrl+C to stop)...")
    print_success(f"Include bots: {include_bots}")

    # Load metadata for progress calculation
    metadata = load_metadata()
    total_messages = 0
    channel_messages = {}

    if metadata and "channels" in metadata:
        for ch_data in metadata["channels"].values():
            count = ch_data.get("message_count", 0)
            name = ch_data.get("name", "")
            total_messages += count
            channel_messages[name] = count
        print_info(f"Previous archive: {total_messages:,} messages across {len(channel_messages)} channels")

    archiver_script = SCRIPT_DIR / "discord_archiver.py"
    cmd = [sys.executable, "-u", str(archiver_script), token, interval, archive_path]
    if include_bots:
        cmd.append("--include-bots")

    console.print()

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    current_channel = None
    current_channel_messages = 0
    archived_messages = 0
    channels_done = 0
    total_channels = len(channel_messages) if channel_messages else 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30),
        TaskProgressColumn(),
        TextColumn("[cyan]{task.fields[status]}"),
        console=console,
        transient=False,
    ) as progress:
        main_task = progress.add_task("[cyan]Waiting for bot to connect...", total=100, status="")

        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue

                parsed = parse_archiver_line(line)

                if parsed:
                    if parsed["type"] == "logged_in":
                        progress.update(main_task, description="[cyan]Bot connected, waiting for archive...")

                    elif parsed["type"] == "server_start":
                        progress.update(main_task, description=f"[cyan]Archiving: {parsed['name']}")

                    elif parsed["type"] == "channel_start":
                        current_channel = parsed["name"]
                        current_channel_messages = 0
                        expected = channel_messages.get(current_channel, 0)
                        status = f"#{current_channel}"
                        if expected > 0:
                            status += f" (~{expected:,} msgs)"
                        progress.update(main_task, status=status)

                    elif parsed["type"] == "progress":
                        current_channel_messages = parsed["count"]
                        expected = channel_messages.get(parsed["channel"], 0)

                        if total_messages > 0:
                            completed_msgs = archived_messages
                            if expected > 0:
                                channel_pct = min(current_channel_messages / expected, 1.0)
                                completed_msgs += int(expected * channel_pct)
                            else:
                                completed_msgs += current_channel_messages

                            pct = min((completed_msgs / total_messages) * 100, 100)
                            progress.update(main_task, completed=pct)

                        status = f"#{parsed['channel']} [{current_channel_messages:,}"
                        if expected > 0:
                            status += f"/{expected:,}"
                        status += " msgs]"
                        progress.update(main_task, status=status)

                    elif parsed["type"] == "channel_done":
                        channels_done += 1
                        archived_messages += parsed["count"]

                        if total_messages > 0:
                            pct = min((archived_messages / total_messages) * 100, 100)
                            progress.update(main_task, completed=pct)
                        elif total_channels > 0:
                            pct = (channels_done / total_channels) * 100
                            progress.update(main_task, completed=pct)

                        status = f"✓ #{parsed['name']} ({parsed['count']:,} msgs)"
                        progress.update(main_task, status=status)

                    elif parsed["type"] == "server_done":
                        progress.update(
                            main_task,
                            completed=100,
                            description="[green]Archive complete!",
                            status=f"{archived_messages:,} messages archived",
                        )

                    elif parsed["type"] == "archive_done":
                        progress.update(
                            main_task,
                            completed=100,
                            description="[green]Archive complete!",
                            status=f"{archived_messages:,} total messages",
                        )

            process.wait()

        except KeyboardInterrupt:
            process.terminate()
            process.wait()
            console.print()
            print_info("Archiver stopped by user")
            return

    console.print()
    print_success(f"Archiving complete: {archived_messages:,} messages from {channels_done} channels")


# -----------------------------
# Generate HTML
# -----------------------------
def cmd_generate():
    """Generate HTML from archive"""
    print_header()

    archive_path = Path(get_env("ARCHIVE_PATH", str(DEFAULT_ARCHIVE_PATH)))
    output_path = Path(get_env("HTML_OUTPUT_PATH", str(DEFAULT_HTML_PATH)))

    if not archive_path.exists():
        print_error(f"Archive directory not found: {archive_path}")
        print_info("Run 'start' or 'archive' command first to archive your Discord server")
        sys.exit(1)

    servers = list(archive_path.glob("server_*"))
    if not servers:
        print_error(f"No archived servers found in {archive_path}")
        print_info("Make sure the archiver has run and archived at least one server")
        sys.exit(1)

    print_info("Generating HTML from archive...")
    generator_script = SCRIPT_DIR / "html_generator.py"
    subprocess.run([sys.executable, str(generator_script), str(archive_path), str(output_path)])
    print_success(f"HTML generated: {output_path}")


# -----------------------------
# Serve / View
# -----------------------------
def cmd_serve(port=None):
    """Start local web server and open browser"""
    print_header()

    output_path = Path(get_env("HTML_OUTPUT_PATH", str(DEFAULT_HTML_PATH)))
    if port is None:
        port = int(get_env("SERVER_PORT", DEFAULT_PORT))

    if not output_path.exists():
        print_error(f"HTML directory not found: {output_path}")
        print_info("Run 'generate' command first")
        sys.exit(1)

    server_dirs = [d for d in output_path.iterdir() if d.is_dir()]
    if not server_dirs:
        print_error(f"No server directories found in {output_path}")
        sys.exit(1)

    server_dir = max(server_dirs, key=lambda d: d.stat().st_mtime)
    server_id = server_dir.name

    url = f"http://localhost:{port}/{server_id}/index.html"

    print_info(f"Starting web server on port {port}...")
    print_success(f"Opening [green]{url}[/green]")
    print_warning("Press Ctrl+C to stop")
    console.print()

    os.chdir(output_path)

    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port)])
    time.sleep(0.5)
    webbrowser.open(url)

    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()
        server.wait()


def cmd_view(port=None):
    """Generate HTML and start server with browser"""
    print_header()

    archive_path = Path(get_env("ARCHIVE_PATH", str(DEFAULT_ARCHIVE_PATH)))
    output_path = Path(get_env("HTML_OUTPUT_PATH", str(DEFAULT_HTML_PATH)))

    if not archive_path.exists():
        print_error(f"Archive directory not found: {archive_path}")
        sys.exit(1)

    print_info("Generating HTML from archive...")
    generator_script = SCRIPT_DIR / "html_generator.py"
    subprocess.run([sys.executable, str(generator_script), str(archive_path), str(output_path)])
    print_success(f"HTML generated: {output_path}")
    console.print()

    if port is None:
        port = int(get_env("SERVER_PORT", DEFAULT_PORT))

    server_dirs = [d for d in output_path.iterdir() if d.is_dir()]
    if not server_dirs:
        print_error(f"No server directories found in {output_path}")
        sys.exit(1)

    server_dir = max(server_dirs, key=lambda d: d.stat().st_mtime)
    server_id = server_dir.name

    url = f"http://localhost:{port}/{server_id}/index.html"

    print_info(f"Starting web server on port {port}...")
    print_success(f"Opening [green]{url}[/green]")
    print_warning("Press Ctrl+C to stop")
    console.print()

    os.chdir(output_path)

    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port)])
    time.sleep(0.5)
    webbrowser.open(url)

    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()
        server.wait()


# -----------------------------
# Status / Logs / Help
# -----------------------------
def cmd_status():
    """Show current status"""
    print_header()

    archive_path = Path(get_env("ARCHIVE_PATH", str(DEFAULT_ARCHIVE_PATH)))
    output_path = Path(get_env("HTML_OUTPUT_PATH", str(DEFAULT_HTML_PATH)))

    console.print("Configuration:")
    console.print(f"  Archive path: {archive_path}")
    console.print(f"  HTML output:  {output_path}")
    console.print()

    if is_archiver_running():
        pid = PID_FILE.read_text().strip()
        print_success(f"Archiver is running (PID: {pid})")
    else:
        print_warning("Archiver is not running")

    if archive_path.exists():
        servers = list(archive_path.glob("server_*"))
        print_success(f"Archive exists ({len(servers)} server(s))")
    else:
        print_warning("Archive directory not found")

    if output_path.exists():
        print_success("HTML output exists")
    else:
        print_warning("HTML not generated yet")

    saved = load_archiver_settings()
    if saved:
        console.print()
        console.print("[cyan]Last archiver settings:[/cyan]")
        console.print(f"  Include bots:          {saved.get('include_bots', False)}")
        console.print(f"  Download attachments:  {saved.get('download_attachments', False)}")
        console.print(f"  Limit:                 {saved.get('limit') or 'unlimited'}")
        chs = saved.get("channels") or []
        console.print(f"  Channels:              {', '.join(chs) if chs else 'all'}")
        console.print(f"  Delay:                 {saved.get('delay') or '0'}")
        console.print(f"  Update interval hours: {saved.get('update_interval_hours')}")
        console.print(f"  Archive path:          {saved.get('archive_path')}")
    else:
        console.print()
        console.print("[yellow]![/yellow] No saved archiver settings found yet (run `start` once).")


    console.print()


def cmd_logs():
    """Show archiver logs"""
    if LOG_FILE.exists():
        print_info("Showing archiver logs (Ctrl+C to exit)...")
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                console.print(f.read())
                while True:
                    line = f.readline()
                    if line:
                        console.print(line, end="")
                    else:
                        time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    else:
        print_warning("No log file found")


def cmd_help():
    """Show help message"""
    print_header()
    console.print("Usage: python run.py <command> [options]")
    console.print()
    console.print("[cyan]Setup Commands:[/cyan]")
    console.print("  setup              Install dependencies and create .env file")
    console.print("  status             Show current status of archiver and files")
    console.print()
    console.print("[cyan]Archiver Commands:[/cyan]")
    console.print("  start [options]    Start archiver in background (interactive if no flags)")
    console.print("  stop               Stop background archiver")
    console.print("  archive [options]  Run archiver in foreground (Ctrl+C to stop)")
    console.print("  logs               Show archiver logs")
    console.print()
    console.print("[cyan]HTML Commands:[/cyan]")
    console.print("  generate           Generate HTML from archive")
    console.print("  serve [port]       Start local web server (default: 8000)")
    console.print("  view [port]        Generate new HTML and start server")
    console.print()
    console.print("[cyan]Archiver Options:[/cyan]")
    console.print("  --include-bots          Include bot-authored messages (default: off)")
    console.print("  --limit N               Limit messages per channel (default: unlimited)")
    console.print("  --channel NAME/ID       Only archive specific channel (can repeat)")
    console.print("  --download-attachments  Download images/files locally (default: off)")
    console.print("  --delay N               Delay N seconds between API batches (default: 0)")
    console.print()
    console.print("[blue]USAGE:[/blue]")
    console.print("[blue]1)[/blue] python run.py setup[green]   First time - creates .env[/green]")
    console.print("[blue]2)[/blue] python run.py start[green]   Start archiver (wizard if no flags)[/green]")
    console.print("[blue]3)[/blue] python run.py view[green]    Generate HTML and open viewer[/green]")
    console.print()


# -----------------------------
# Main
# -----------------------------
def main():
    os.chdir(SCRIPT_DIR)

    if len(sys.argv) < 2:
        cmd_help()
        return

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    commands = {
        "setup": cmd_setup,
        "start": cmd_start,
        "stop": cmd_stop,
        "archive": cmd_archive,
        "generate": cmd_generate,
        "serve": lambda: cmd_serve(int(args[0]) if args else None),
        "view": lambda: cmd_view(int(args[0]) if args else None),
        "status": cmd_status,
        "logs": cmd_logs,
        "help": cmd_help,
        "--help": cmd_help,
        "-h": cmd_help,
    }

    if command in commands:
        try:
            commands[command]()
        except KeyboardInterrupt:
            console.print("\n")
            print_info("Interrupted by user")
    else:
        print_error(f"Unknown command: {command}")
        console.print()
        cmd_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
