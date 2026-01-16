"""OpenCode process manager for auto-starting and lifecycle management.

This module handles the Conversator orchestration layer (Layer 2) which provides
subagents for planning, context retrieval, and summarization. This is CRITICAL
for the voice conversation to have "brains".

Architecture:
- Layer 2 (this): OpenCode on port 4158 - orchestration/subagents
- Layer 3: Builder OpenCode server on port 4096
"""

import asyncio
import logging
import os
import select
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class OpenCodeManager:
    """Manages OpenCode subprocess lifecycle for the orchestration layer.

    This manager is responsible for:
    - Setting up isolated OpenCode config (separate from user's .opencode/)
    - Syncing versioned agents to runtime location
    - Starting OpenCode with proper environment
    - Waiting for health check to pass
    - Clean shutdown when Conversator exits
    """

    def __init__(
        self,
        port: int = 4158,
        working_dir: Optional[str] = None,
        start_timeout: float = 30.0,
        config_dir: str = ".conversator/opencode",
        agents_source: str = "conversator/agents",
    ):
        """Initialize OpenCode manager.

        Args:
            port: Port for OpenCode HTTP server (Layer 2)
            working_dir: Working directory for OpenCode (project root)
            start_timeout: Timeout in seconds for OpenCode to become healthy
            config_dir: Isolated OpenCode config directory (relative to working_dir)
            agents_source: Path to versioned agents (relative to working_dir)
        """
        self.port = port
        self.working_dir = Path(working_dir or Path.cwd())
        self.start_timeout = start_timeout
        self.config_dir = self.working_dir / config_dir
        self.agents_source = self.working_dir / agents_source
        self.process: Optional[subprocess.Popen] = None
        self._started_by_us = False
        self._base_url = f"http://localhost:{port}"

    async def start(self) -> bool:
        """Start OpenCode with proper setup if not already running.

        This performs the same setup as scripts/start-conversator.sh:
        - Sets OPENCODE_CONFIG_DIR for isolation
        - Syncs versioned agents to runtime location
        - Starts OpenCode serve on the configured port

        Returns:
            True if OpenCode is running (started by us or already was)
        """
        # Check if already running externally
        if await self._is_healthy():
            logger.info(f"OpenCode orchestration already running at port {self.port}")
            return True

        # Check for stale processes holding the port (ss is more reliable than lsof)
        await self._cleanup_stale_processes()

        # Setup isolated config directory
        if not self._setup_config_dir():
            logger.error("Failed to setup OpenCode config directory")
            return False

        # Sync agents from versioned source
        if not self._sync_agents():
            logger.error("Failed to sync agents - check that conversator/agents/ exists")
            return False

        # Start the process with isolated environment
        logger.info(f"Starting OpenCode orchestration on port {self.port}...")

        try:
            cmd = self._get_opencode_command()
            if cmd is None:
                logger.error("Could not find opencode command - is it installed?")
                return False

            # Set isolated config directory via environment
            env = os.environ.copy()
            env["OPENCODE_CONFIG_DIR"] = str(self.config_dir)

            self.process = subprocess.Popen(
                cmd,
                cwd=str(self.working_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._started_by_us = True

            # Write PID file (used for safe stale-process cleanup).
            try:
                pid_path = self.working_dir / ".conversator" / "cache" / "conversator.pid"
                pid_path.parent.mkdir(parents=True, exist_ok=True)
                pid_path.write_text(str(self.process.pid))
            except Exception as e:
                logger.debug(f"Failed to write pid file: {e}")

            # Start a background task to log output
            asyncio.create_task(self._log_output())

        except FileNotFoundError:
            logger.error("opencode command not found - is it installed?")
            return False
        except Exception as e:
            logger.error(f"Failed to start OpenCode: {e}")
            return False

        # Wait for health check to pass
        start_time = asyncio.get_event_loop().time()
        check_count = 0
        while (asyncio.get_event_loop().time() - start_time) < self.start_timeout:
            if await self._is_healthy():
                logger.info(f"OpenCode orchestration started successfully on port {self.port}")
                return True

            # Check if process died
            if self.process.poll() is not None:
                logger.error(f"OpenCode process exited with code {self.process.returncode}")
                self.process = None
                self._started_by_us = False
                return False

            check_count += 1
            if check_count % 10 == 0:  # Log every 5 seconds
                print(f"  Waiting for OpenCode to start... ({check_count * 0.5:.0f}s)")

            await asyncio.sleep(0.5)

        logger.error(f"OpenCode failed to become healthy within {self.start_timeout}s")
        await self.stop()
        return False

    def _setup_config_dir(self) -> bool:
        """Setup isolated OpenCode config directory.

        Returns:
            True if successful
        """
        try:
            # Create config and agent directories
            self.config_dir.mkdir(parents=True, exist_ok=True)
            (self.config_dir / "agent").mkdir(exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"Failed to create config directory: {e}")
            return False

    def _sync_agents(self) -> bool:
        """Sync versioned agents to runtime location.

        Returns:
            True if successful
        """
        try:
            if not self.agents_source.exists():
                logger.warning(f"Agents source not found: {self.agents_source}")
                # Not fatal - might have agents already in place
                return True

            agent_dir = self.config_dir / "agent"
            synced = []

            for agent_file in self.agents_source.glob("*.md"):
                dest = agent_dir / agent_file.name
                shutil.copy2(agent_file, dest)
                synced.append(agent_file.name)

            if synced:
                logger.info(f"Synced agents: {', '.join(synced)}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync agents: {e}")
            return False

    def _get_opencode_command(self) -> Optional[list[str]]:
        """Get the command to start OpenCode.

        Returns:
            Command list or None if not found
        """
        # Try 'opencode' directly first
        try:
            result = subprocess.run(
                ["which", "opencode"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return [
                    "opencode", "serve",
                    "--port", str(self.port),
                    "--hostname", "127.0.0.1"
                ]
        except Exception:
            pass

        # Try python -m opencode
        try:
            result = subprocess.run(
                [sys.executable, "-m", "opencode", "--help"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return [
                    sys.executable, "-m", "opencode", "serve",
                    "--port", str(self.port),
                    "--hostname", "127.0.0.1"
                ]
        except Exception:
            pass

        return None

    async def _is_healthy(self) -> bool:
        """Check if OpenCode is responding to health checks.

        Uses /agent endpoint which is used by start-conversator.sh

        Returns:
            True if healthy
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/agent")
                return response.status_code == 200
        except Exception:
            return False

    async def _cleanup_stale_processes(self) -> None:
        """Clean up stale OpenCode processes started by Conversator.

        Safety policy: never kill arbitrary `opencode` processes.

        We only attempt cleanup if a pid file exists (written by
        scripts/start-conversator.sh or when this manager starts OpenCode).
        """
        pid_path = self.working_dir / ".conversator" / "cache" / "conversator.pid"
        if not pid_path.exists():
            return

        try:
            pid = int(pid_path.read_text().strip())
        except Exception:
            try:
                pid_path.unlink()
            except OSError:
                pass
            return

        try:
            os.kill(pid, 0)
        except OSError:
            # Stale pid file.
            try:
                pid_path.unlink()
            except OSError:
                pass
            return

        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_text(errors="ignore")
        except OSError:
            cmdline = ""

        cmdline_lower = cmdline.replace("\x00", " ").lower()
        if "opencode" not in cmdline_lower or "serve" not in cmdline_lower:
            logger.warning(
                f"PID file {pid_path} points to a non-OpenCode process; leaving it alone."
            )
            return

        if f"--port {self.port}" not in cmdline_lower:
            logger.warning(
                f"PID file {pid_path} does not appear to match port {self.port}; leaving it alone."
            )
            return

        logger.warning(
            f"Found stale Conversator OpenCode process (PID {pid}) on port {self.port}, terminating..."
        )
        try:
            os.kill(pid, 15)  # SIGTERM
            await asyncio.sleep(2)
            try:
                os.kill(pid, 0)
            except OSError:
                return
            os.kill(pid, 9)  # SIGKILL
            await asyncio.sleep(1)
        except OSError as e:
            logger.debug(f"Could not terminate PID {pid}: {e}")

    async def _log_output(self) -> None:
        """Background task to log OpenCode output (non-blocking)."""
        if self.process and self.process.stdout:
            try:
                while self.process.poll() is None:
                    # Use select to check if there's data available (non-blocking)
                    ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
                    if ready:
                        line = self.process.stdout.readline()
                        if line:
                            line = line.rstrip()
                            if "error" in line.lower() or "Error" in line:
                                print(f"  [OpenCode] {line}")
                            elif "listening" in line.lower():
                                print(f"  [OpenCode] {line}")
                            else:
                                logger.debug(f"[OpenCode] {line}")
                    else:
                        await asyncio.sleep(0.1)
            except Exception:
                pass

    async def stop(self) -> None:
        """Stop OpenCode if we started it."""
        if self.process and self._started_by_us:
            logger.info("Stopping OpenCode orchestration...")
            try:
                self.process.terminate()
                # Wait up to 5 seconds for graceful shutdown
                for _ in range(50):
                    if self.process.poll() is not None:
                        break
                    await asyncio.sleep(0.1)
                else:
                    # Force kill if still running
                    logger.warning("OpenCode did not terminate gracefully, killing...")
                    self.process.kill()
            except Exception as e:
                logger.error(f"Error stopping OpenCode: {e}")
            finally:
                try:
                    pid_path = self.working_dir / ".conversator" / "cache" / "conversator.pid"
                    pid_path.unlink(missing_ok=True)
                except Exception:
                    pass
                self.process = None
                self._started_by_us = False

    @property
    def is_running(self) -> bool:
        """Check if the managed process is running."""
        if self.process:
            return self.process.poll() is None
        return False

    @property
    def is_managed(self) -> bool:
        """Check if we started this OpenCode instance."""
        return self._started_by_us

    async def health_check(self) -> bool:
        """Check if OpenCode is healthy (alias for external use)."""
        return await self._is_healthy()
