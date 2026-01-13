"""Builder process manager for starting OpenCode in project directories.

This module manages the Layer 3 (Builder) OpenCode instance that runs in the
user's project directory. Unlike the orchestration layer (Layer 2), this
doesn't need custom agents - it uses the project's own .opencode/ config
or OpenCode defaults.
"""

import asyncio
import logging
import os
import re
import select
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class BuilderManager:
    """Manages OpenCode subprocess for the builder layer.

    This manager starts OpenCode in a specific project directory when the user
    selects a project to work on. It handles:
    - Starting OpenCode with the correct working directory
    - Waiting for health check to pass
    - Clean shutdown when switching projects or exiting
    """

    def __init__(self, port: int = 8001, start_timeout: float = 30.0):
        """Initialize builder manager.

        Args:
            port: Port for OpenCode HTTP server
            start_timeout: Timeout in seconds for OpenCode to become healthy
        """
        self.port = port
        self.start_timeout = start_timeout
        self.working_dir: Optional[Path] = None
        self.process: Optional[subprocess.Popen] = None
        self._started_by_us = False
        self._base_url = f"http://localhost:{port}"

    async def start(self, project_dir: str) -> bool:
        """Start OpenCode builder in the specified project directory.

        Args:
            project_dir: Path to the project directory

        Returns:
            True if OpenCode is running (started by us or already was)
        """
        self.working_dir = Path(project_dir)

        if not self.working_dir.exists():
            logger.error(f"Project directory does not exist: {project_dir}")
            return False

        # Stop any existing builder first
        if self.process and self._started_by_us:
            await self.stop()

        # Check if already running externally
        if await self._is_healthy():
            logger.info(f"OpenCode builder already running at port {self.port}")
            return True

        # Check for stale processes holding the port
        await self._cleanup_stale_processes()

        # Start the process
        logger.info(f"Starting OpenCode builder on port {self.port} in {project_dir}...")

        try:
            cmd = self._get_opencode_command()
            if cmd is None:
                logger.error("Could not find opencode command - is it installed?")
                return False

            self.process = subprocess.Popen(
                cmd,
                cwd=str(self.working_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._started_by_us = True

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
                logger.info(f"OpenCode builder started successfully on port {self.port}")
                return True

            # Check if process died
            if self.process.poll() is not None:
                logger.error(f"OpenCode process exited with code {self.process.returncode}")
                self.process = None
                self._started_by_us = False
                return False

            check_count += 1
            if check_count % 10 == 0:  # Log every 5 seconds
                print(f"  Waiting for builder to start... ({check_count * 0.5:.0f}s)")

            await asyncio.sleep(0.5)

        logger.error(f"OpenCode failed to become healthy within {self.start_timeout}s")
        await self.stop()
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
        """Clean up any stale OpenCode processes holding the port."""
        try:
            # Use ss to find processes listening on our port
            result = subprocess.run(
                ["ss", "-tlnp", f"sport = :{self.port}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and "opencode" in result.stdout:
                # Extract PID from output
                match = re.search(r'pid=(\d+)', result.stdout)
                if match:
                    pid = int(match.group(1))
                    logger.warning(f"Found stale OpenCode process (PID {pid}) on port {self.port}, killing...")
                    try:
                        os.kill(pid, 15)  # SIGTERM
                        await asyncio.sleep(2)
                        try:
                            os.kill(pid, 0)  # Just check
                            os.kill(pid, 9)  # SIGKILL
                            await asyncio.sleep(1)
                        except OSError:
                            pass
                    except OSError as e:
                        logger.debug(f"Could not kill PID {pid}: {e}")
        except Exception as e:
            logger.debug(f"Stale process cleanup failed: {e}")

    async def _log_output(self) -> None:
        """Background task to log OpenCode output (non-blocking)."""
        if self.process and self.process.stdout:
            try:
                while self.process.poll() is None:
                    ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
                    if ready:
                        line = self.process.stdout.readline()
                        if line:
                            line = line.rstrip()
                            if "error" in line.lower() or "Error" in line:
                                print(f"  [Builder] {line}")
                            elif "listening" in line.lower():
                                print(f"  [Builder] {line}")
                            else:
                                logger.debug(f"[Builder] {line}")
                    else:
                        await asyncio.sleep(0.1)
            except Exception:
                pass

    async def stop(self) -> None:
        """Stop OpenCode if we started it."""
        if self.process and self._started_by_us:
            logger.info("Stopping OpenCode builder...")
            try:
                self.process.terminate()
                # Wait up to 5 seconds for graceful shutdown
                for _ in range(50):
                    if self.process.poll() is not None:
                        break
                    await asyncio.sleep(0.1)
                else:
                    logger.warning("OpenCode did not terminate gracefully, killing...")
                    self.process.kill()
            except Exception as e:
                logger.error(f"Error stopping OpenCode: {e}")
            finally:
                self.process = None
                self._started_by_us = False

    async def health_check(self) -> bool:
        """Check if OpenCode is healthy."""
        return await self._is_healthy()

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

    @property
    def project_name(self) -> Optional[str]:
        """Get the current project name."""
        if self.working_dir:
            return self.working_dir.name
        return None
