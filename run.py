#!/usr/bin/env python3
"""
Discord Archive CLI - Cross-platform helper script
Works on Windows, Linux, and macOS

NEW:
  --include-bots   Include bot-authored messages in the archive (default: off)
"""

import subprocess
import sys
import os
import signal
from pathlib import Path
import webbrowser
import time

# Configuration
SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_ARCHIVE_PATH = SCRIPT_DIR / "discord_archive"
DEFAULT_HTML_PATH = SCRIPT_DIR / "discord_html"
DEFAULT_PORT = 8000
PID_FILE = SCRIPT_DIR / ".archiver.pid"
LOG_FILE = SCRIPT_DIR / "archiver.log"
ENV_FILE = SCRIPT_DIR / ".env"

# Colors 
class Colors:
    if sys.platform == "win32":
        os.system("") 

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_header():
    print(f"{Colors.BLUE}================================{Colors.RESET}")
    print(f"{Colors.BLUE}  Discord Server Archiver{Colors.RESET}")
    print(f"{Colors.BLUE}================================{Colors.RESET}")
    print()


def print_success(msg):
    print(f"{Colors.GREEN}✓{Colors.RESET} {msg}")


def print_error(msg):
    print(f"{Colors.RED}✗{Colors.RESET} {msg}")


def print_warning(msg):
    print(f"{Colors.YELLOW}!{Colors.RESET} {msg}")


def print_info(msg):
    print(f"{Colors.BLUE}→{Colors.RESET} {msg}")


def print_step(step, msg):
    print(f"{Colors.CYAN}[{step}]{Colors.RESET} {msg}")


def load_env():
    """Load environment variables from .env file"""
    env = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env[key.strip()] = value.strip()
    return env


def get_env(key, default=None):
    """Get environment variable from .env or use default"""
    env = load_env()
    return env.get(key, default)


def get_python_cmd():
    """Get the Python command for this system"""
    return sys.executable


def cmd_setup():
    """Install dependencies and create .env file"""
    print_header()

    # Check Python version
    version = sys.version_info
    print_success(f"Python {version.major}.{version.minor}.{version.micro} found")

    # Install dependencies
    print_info("Installing dependencies...")
    req_file = SCRIPT_DIR / "requirements.txt"

    if req_file.exists():
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"])
        print_success("Dependencies installed")
    else:
        print_warning("requirements.txt not found, installing discord.py...")
        subprocess.run([sys.executable, "-m", "pip", "install", "discord.py", "-q"])
        print_success("discord.py installed")

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
        with open(ENV_FILE, 'w') as f:
            f.write(env_content)
        print_warning("Created .env file")
        print_warning("Please edit .env and add your Discord bot token")
    else:
        print_success("Environment file exists")

    print()
    print_success("Setup complete!")
    print_info("Next steps:")
    print("  1. Edit .env and add your Discord bot token")
    print("  2. Run 'python run.py start' to start archiving")
    print("  3. Run 'python run.py view' to generate and view the archive")


def is_archiver_running():
    """Check if archiver process is running"""
    if not PID_FILE.exists():
        return False

    try:
        pid = int(PID_FILE.read_text().strip())

        # Check if process exists
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True
            )
            if str(pid) in result.stdout:
                return True
        else:
            os.kill(pid, 0)
            return True
    except (ValueError, OSError, ProcessLookupError):
        pass

    PID_FILE.unlink(missing_ok=True)
    return False


def _has_flag(flag: str) -> bool:
    """True if CLI flag is present anywhere after the command."""
    return flag in sys.argv[2:]


def cmd_start():
    """Start archiver in background"""
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

    include_bots = _has_flag("--include-bots")

    print_info("Starting Discord archiver in background...")

    archiver_script = SCRIPT_DIR / "discord_archiver.py"

    cmd = [sys.executable, str(archiver_script), token, interval, archive_path]
    if include_bots:
        cmd.append("--include-bots")

    if sys.platform == "win32":
        with open(LOG_FILE, 'w') as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
    else:
        with open(LOG_FILE, 'w') as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )

    PID_FILE.write_text(str(process.pid))

    time.sleep(2)

    if is_archiver_running():
        print_success(f"Archiver started (PID: {process.pid})")
        print_success(f"Include bots: {include_bots}")
        print_info(f"Logs: {LOG_FILE}")
    else:
        print_error("Archiver failed to start. Check archiver.log for details")
        sys.exit(1)


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


def cmd_archive():
    """Run archiver in foreground (blocking)"""
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

    archiver_script = SCRIPT_DIR / "discord_archiver.py"
    cmd = [sys.executable, str(archiver_script), token, interval, archive_path]
    if include_bots:
        cmd.append("--include-bots")

    subprocess.run(cmd)


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
    print_success(f"Opening {Colors.GREEN}{url}{Colors.RESET}")
    print_warning("Press Ctrl+C to stop")
    print()

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

    print_step("1/2", "Generating HTML...")

    archive_path = Path(get_env("ARCHIVE_PATH", str(DEFAULT_ARCHIVE_PATH)))
    output_path = Path(get_env("HTML_OUTPUT_PATH", str(DEFAULT_HTML_PATH)))

    if not archive_path.exists():
        print_error(f"Archive directory not found: {archive_path}")
        sys.exit(1)

    generator_script = SCRIPT_DIR / "html_generator.py"
    subprocess.run([sys.executable, str(generator_script), str(archive_path), str(output_path)])

    print_success(f"HTML generated: {output_path}")
    print()
    print_step("2/2", "Starting server...")

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
    print_success(f"Opening {Colors.GREEN}{url}{Colors.RESET}")
    print_warning("Press Ctrl+C to stop")
    print()

    os.chdir(output_path)

    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port)])
    time.sleep(0.5)
    webbrowser.open(url)

    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()
        server.wait()


def cmd_status():
    """Show current status"""
    print_header()

    archive_path = Path(get_env("ARCHIVE_PATH", str(DEFAULT_ARCHIVE_PATH)))
    output_path = Path(get_env("HTML_OUTPUT_PATH", str(DEFAULT_HTML_PATH)))

    print("Configuration:")
    print(f"  Archive path: {archive_path}")
    print(f"  HTML output:  {output_path}")
    print()

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

    print()


def cmd_logs():
    """Show archiver logs"""
    if LOG_FILE.exists():
        print_info("Showing archiver logs (Ctrl+C to exit)...")
        try:
            with open(LOG_FILE, 'r') as f:
                print(f.read())
                while True:
                    line = f.readline()
                    if line:
                        print(line, end='')
                    else:
                        time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    else:
        print_warning("No log file found")


def cmd_help():
    """Show help message"""
    print_header()
    print("Usage: python run.py <command> [options]")
    print()
    print(f"{Colors.CYAN}Setup Commands:{Colors.RESET}")
    print("  setup              Install dependencies and create .env file")
    print("  status             Show current status of archiver and files")
    print()
    print(f"{Colors.CYAN}Archiver Commands:{Colors.RESET}")
    print("  start [--include-bots]    Start archiver in background (keeps running)")
    print("  stop                      Stop background archiver")
    print("  archive [--include-bots]  Run archiver in foreground (Ctrl+C to stop)")
    print("  logs                      Show archiver logs")
    print()
    print(f"{Colors.CYAN}HTML Commands:{Colors.RESET}")
    print("  generate           Generate HTML from archive")
    print("  serve [port]       Start local web server (default: 8000)")
    print("  view [port]        Generate new HTML and start server")
    print()
    print(f"{Colors.CYAN}Flags:{Colors.RESET}")
    print("  --include-bots     Include bot-authored messages in the archive (default: off)")
    print()
    print(f"{Colors.BLUE}USAGE:{Colors.RESET}")
    print(f"{Colors.BLUE}1){Colors.RESET} python run.py setup{Colors.GREEN}   First time - creates .env{Colors.RESET}")
    print(f"{Colors.BLUE}2){Colors.RESET} python run.py start{Colors.GREEN}   Start archiver in background{Colors.RESET}")
    print(f"{Colors.BLUE}3){Colors.RESET} python run.py view{Colors.GREEN}    Generate HTML and open viewer{Colors.RESET}")
    print()


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
            print("\n")
            print_info("Interrupted by user")
    else:
        print_error(f"Unknown command: {command}")
        print()
        cmd_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
