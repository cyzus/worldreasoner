#!/usr/bin/env python3
"""
WorldReasoner Graph Visualization Startup Script
Starts both backend and frontend servers
"""

import subprocess
import sys
import time
import signal
import os
import platform
from pathlib import Path
from typing import Optional

# ANSI color codes
class Colors:
    CYAN = '\033[36m'
    YELLOW = '\033[33m'
    GREEN = '\033[32m'
    RED = '\033[31m'
    RESET = '\033[0m'

def print_colored(message: str, color: str = Colors.RESET):
    """Print colored message"""
    print(f"{color}{message}{Colors.RESET}")

def run_command(command: list[str], cwd: Optional[Path] = None, check: bool = True, shell: bool = False) -> bool:
    """Run a command and return success status"""
    try:
        subprocess.run(command, cwd=cwd, check=check, capture_output=False, shell=shell)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print_colored(f"Command failed: {e}", Colors.RED)
        return False

def check_backend_dependencies() -> bool:
    """Check and install backend dependencies"""
    print_colored("\nChecking backend dependencies...", Colors.YELLOW)
    if run_command(["uv", "sync"]):
        print_colored("Backend dependencies OK", Colors.GREEN)
        return True
    else:
        print_colored("Failed to install backend dependencies", Colors.RED)
        return False

def check_frontend_dependencies() -> bool:
    """Check and install frontend dependencies"""
    print_colored("\nChecking frontend dependencies...", Colors.YELLOW)
    frontend_dir = Path("frontend")
    node_modules = frontend_dir / "node_modules"
    
    if not node_modules.exists():
        print_colored("Installing frontend dependencies (first time only)...", Colors.YELLOW)
        if run_command(["npm", "install"], cwd=frontend_dir, shell=True):
            print_colored("Frontend dependencies installed", Colors.GREEN)
            return True
        else:
            print_colored("Failed to install frontend dependencies", Colors.RED)
            return False
    else:
        print_colored("Frontend dependencies OK", Colors.GREEN)
        return True

def start_servers():
    """Start both backend and frontend servers"""
    print_colored("\nStarting backend server...", Colors.YELLOW)
    
    # Start backend
    # Configure subprocess flags for better signal handling on Windows
    is_windows = platform.system() == "Windows"
    creationflags = 0
    if is_windows:
        # Create a new process group so we can send CTRL_BREAK_EVENT
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    backend_process = subprocess.Popen(
        ["uv", "run", "worldreasoner", "--reload"],
        stdout=None,  # inherit parent stdout for direct logs
        stderr=None,
        text=True,
        bufsize=1,
        shell=False,
        creationflags=creationflags
    )
    
    # Wait for backend to start
    print_colored("Waiting for backend to initialize...", Colors.YELLOW)
    time.sleep(3)
    
    # Start frontend
    print_colored("Starting frontend dev server...", Colors.YELLOW)
    # Resolve npm command on Windows (npm.cmd) vs Unix (npm)
    npm_cmd = "npm"
    if is_windows:
        npm_cmd = "npm.cmd"

    frontend_process = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=Path("frontend"),
        stdout=None,
        stderr=None,
        text=True,
        bufsize=1,
        shell=False,
        creationflags=creationflags
    )
    
    # Print success message
    print_colored("\n=== WorldReasoner Graph Visualization Started ===", Colors.GREEN)
    print_colored("Backend API: http://localhost:8018", Colors.CYAN)
    print_colored("API Docs:    http://localhost:8018/docs", Colors.CYAN)
    print_colored("Frontend:    http://localhost:3000", Colors.CYAN)
    print_colored("\nPress Ctrl+C to stop both servers", Colors.YELLOW)
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print_colored("\n\nStopping servers...", Colors.YELLOW)
        try:
            if is_windows:
                # Send CTRL_BREAK_EVENT to process group for graceful shutdown
                backend_process.send_signal(signal.CTRL_BREAK_EVENT)
                frontend_process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                backend_process.terminate()
                frontend_process.terminate()
        except Exception:
            # Fallback to terminate
            try:
                backend_process.terminate()
            except Exception:
                pass
            try:
                frontend_process.terminate()
            except Exception:
                pass
        
        # Wait for processes to terminate
        try:
            backend_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend_process.kill()
        
        try:
            frontend_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            frontend_process.kill()
        
        print_colored("Servers stopped", Colors.GREEN)
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Wait for processes
    try:
        # Wait until either process exits; keep the script responsive to Ctrl+C
        while True:
            ret_backend = backend_process.poll()
            ret_frontend = frontend_process.poll()
            if ret_backend is not None and ret_frontend is not None:
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        signal_handler(None, None)

def main():
    """Main entry point"""
    print_colored("Starting WorldReasoner Graph Visualization...", Colors.CYAN)
    
    # Check dependencies
    if not check_backend_dependencies():
        sys.exit(1)
    
    if not check_frontend_dependencies():
        sys.exit(1)
    
    # Start servers
    start_servers()

if __name__ == "__main__":
    main()
