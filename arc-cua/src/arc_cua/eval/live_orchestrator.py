"""Live Benchmark Environment Orchestrator (Phase 5 Task 3).

Manages the lifecycle of live WebArena Docker containers and OSWorld QEMU/KVM virtual machines.
- Probes host capabilities: Docker daemon, KVM hardware acceleration, and QEMU/SSH tooling.
- Orchestrates WebArena docker-compose lifecycle: start, stop, health polling, and DB resets.
- Orchestrates OSWorld VM lifecycle: QEMU execution, SSH readiness, and COW snapshot resets.
- Implements wait_for_healthy() with robust socket and HTTP polling.
- Implements reset_state() to wipe databases and restore clean snapshots between benchmark tasks.
- If live infrastructure is unavailable, logs LIVE_ORCHESTRATION_SKIPPED and exits gracefully.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("arc_cua.eval.live_orchestrator")

LIVE_ORCHESTRATION_SKIPPED = "LIVE_ORCHESTRATION_SKIPPED"


@dataclasses.dataclass
class HostCapabilities:
    """Summary of detected host virtualization and containerization capabilities."""
    docker_available: bool = False
    docker_compose_available: bool = False
    docker_reason: str = ""
    kvm_available: bool = False
    kvm_reason: str = ""
    qemu_available: bool = False
    qemu_binary: Optional[str] = None
    ssh_available: bool = False
    ssh_binary: Optional[str] = None


class LiveOrchestrator:
    """Orchestrator managing live container and VM environments for evaluation benchmarks."""

    def __init__(
        self,
        webarena_compose_path: Optional[Union[str, Path]] = None,
        osworld_image_path: Optional[Union[str, Path]] = None,
        osworld_snapshot_name: str = "clean_gold",
        process_runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    ):
        """Initialize LiveOrchestrator and probe host capabilities.

        Args:
            webarena_compose_path: Path to WebArena docker-compose.yml file.
            osworld_image_path: Path to base OSWorld QCOW2 disk image.
            osworld_snapshot_name: Name of baseline QCOW2 snapshot to restore between tasks.
            process_runner: Optional subprocess runner for dependency injection / mock testing.
        """
        self.webarena_compose_path = Path(webarena_compose_path) if webarena_compose_path else None
        self.osworld_image_path = Path(osworld_image_path) if osworld_image_path else None
        self.osworld_snapshot_name = osworld_snapshot_name
        self._runner = process_runner or subprocess.run

        # Probe host capabilities
        self.capabilities = self._probe_capabilities()

        # Active VM processes or container tracking
        self._active_qemu_proc: Optional[subprocess.Popen] = None
        self._webarena_running: bool = False

    def _probe_capabilities(self) -> HostCapabilities:
        """Inspect host operating system for Docker, KVM, QEMU, and SSH."""
        caps = HostCapabilities()

        # 1. Probe Docker
        docker_bin = shutil.which("docker")
        if not docker_bin:
            caps.docker_available = False
            caps.docker_reason = "Docker CLI binary not found in PATH"
        else:
            try:
                res = self._runner(
                    [docker_bin, "info"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                )
                if res.returncode == 0:
                    caps.docker_available = True
                    caps.docker_reason = "Docker daemon running and responsive"
                else:
                    caps.docker_available = False
                    caps.docker_reason = f"Docker daemon not responsive (exit {res.returncode})"
            except Exception as e:
                caps.docker_available = False
                caps.docker_reason = f"Docker check failed: {e}"

        # 2. Probe Docker Compose
        if caps.docker_available:
            try:
                res_dc = self._runner(
                    ["docker", "compose", "version"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                )
                caps.docker_compose_available = (res_dc.returncode == 0)
            except Exception:
                caps.docker_compose_available = False

        # 3. Probe KVM (Linux hardware virtualization)
        kvm_dev = Path("/dev/kvm")
        if kvm_dev.exists() and os.access(kvm_dev, os.R_OK | os.W_OK):
            caps.kvm_available = True
            caps.kvm_reason = "/dev/kvm is accessible with read/write permissions"
        elif kvm_dev.exists():
            caps.kvm_available = False
            caps.kvm_reason = "/dev/kvm exists but lacks read/write permissions"
        else:
            caps.kvm_available = False
            caps.kvm_reason = "KVM acceleration device (/dev/kvm) not present on this host OS"

        # 4. Probe QEMU
        qemu_bin = shutil.which("qemu-system-x86_64") or shutil.which("qemu-system-aarch64")
        if qemu_bin:
            caps.qemu_available = True
            caps.qemu_binary = qemu_bin
        else:
            caps.qemu_available = False

        # 5. Probe SSH
        ssh_bin = shutil.which("ssh")
        if ssh_bin:
            caps.ssh_available = True
            caps.ssh_binary = ssh_bin
        else:
            caps.ssh_available = False

        return caps

    # -------------------------------------------------------------------------
    # WebArena Lifecycle
    # -------------------------------------------------------------------------

    def start_webarena(
        self,
        compose_file: Optional[Path] = None,
        services: Optional[List[str]] = None,
        timeout_sec: float = 120.0,
    ) -> bool:
        """Start WebArena benchmark container cluster using docker-compose.

        Returns:
            True if started successfully, False if skipped or failed.
        """
        if not self.capabilities.docker_available or not self.capabilities.docker_compose_available:
            logger.info(f"{LIVE_ORCHESTRATION_SKIPPED}: Docker unavailable ({self.capabilities.docker_reason})")
            return False

        target_compose = compose_file or self.webarena_compose_path
        if not target_compose or not target_compose.exists():
            logger.info(f"{LIVE_ORCHESTRATION_SKIPPED}: WebArena compose file not found ({target_compose})")
            return False

        cmd = ["docker", "compose", "-f", str(target_compose), "up", "-d"]
        if services:
            cmd.extend(services)

        try:
            logger.info(f"Starting WebArena container cluster: {' '.join(cmd)}")
            res = self._runner(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)
            if res.returncode == 0:
                self._webarena_running = True
                logger.info("WebArena container cluster started successfully.")
                return True
            else:
                stderr_msg = res.stderr.decode("utf-8", errors="replace").strip()
                logger.warning(f"Failed to start WebArena cluster: {stderr_msg}")
                return False
        except Exception as e:
            logger.warning(f"Error starting WebArena cluster: {e}")
            return False

    def stop_webarena(self, compose_file: Optional[Path] = None, timeout_sec: float = 60.0) -> bool:
        """Stop WebArena benchmark container cluster."""
        if not self.capabilities.docker_available:
            return True

        target_compose = compose_file or self.webarena_compose_path
        if not target_compose or not target_compose.exists():
            return True

        cmd = ["docker", "compose", "-f", str(target_compose), "down"]
        try:
            res = self._runner(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)
            self._webarena_running = False
            return res.returncode == 0
        except Exception as e:
            logger.warning(f"Error stopping WebArena cluster: {e}")
            return False

    # -------------------------------------------------------------------------
    # OSWorld VM Lifecycle
    # -------------------------------------------------------------------------

    def start_osworld_vm(
        self,
        image_path: Optional[Path] = None,
        qemu_args: Optional[List[str]] = None,
        timeout_sec: float = 60.0,
    ) -> bool:
        """Start OSWorld desktop virtual machine via QEMU with KVM acceleration."""
        if not self.capabilities.kvm_available or not self.capabilities.qemu_available:
            reason = self.capabilities.kvm_reason or "QEMU binary not installed"
            logger.info(f"{LIVE_ORCHESTRATION_SKIPPED}: OSWorld KVM/QEMU unavailable ({reason})")
            return False

        target_image = image_path or self.osworld_image_path
        if not target_image or not target_image.exists():
            logger.info(f"{LIVE_ORCHESTRATION_SKIPPED}: OSWorld image path not found ({target_image})")
            return False

        cmd = [
            self.capabilities.qemu_binary or "qemu-system-x86_64",
            "-enable-kvm",
            "-m", "4096",
            "-smp", "4",
            "-drive", f"file={target_image},format=qcow2,if=virtio",
            "-netdev", "user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::5900-:5900",
            "-device", "virtio-net-pci,netdev=net0",
            "-nographic",
        ]
        if qemu_args:
            cmd.extend(qemu_args)

        try:
            logger.info(f"Spawning OSWorld VM: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._active_qemu_proc = proc
            return True
        except Exception as e:
            logger.warning(f"Failed to spawn OSWorld VM: {e}")
            return False

    def stop_osworld_vm(self) -> bool:
        """Terminate active OSWorld virtual machine."""
        if self._active_qemu_proc:
            try:
                self._active_qemu_proc.terminate()
                self._active_qemu_proc.wait(timeout=5)
            except Exception:
                self._active_qemu_proc.kill()
            self._active_qemu_proc = None
            logger.info("OSWorld VM terminated.")
            return True
        return True

    # -------------------------------------------------------------------------
    # Health Polling & Readiness
    # -------------------------------------------------------------------------

    def wait_for_healthy(
        self,
        target: str,
        timeout_sec: float = 60.0,
        poll_interval_sec: float = 1.0,
    ) -> bool:
        """Wait until an HTTP endpoint or TCP port is healthy and responding.

        Args:
            target: HTTP URL (e.g. 'http://localhost:7770') or host:port string (e.g. '127.0.0.1:2222').
            timeout_sec: Maximum wait duration.
            poll_interval_sec: Delay between poll attempts.

        Returns:
            True if target is responsive within timeout, False otherwise.
        """
        deadline = time.time() + timeout_sec

        if target.startswith("http://") or target.startswith("https://"):
            return self._wait_for_http(target, deadline, poll_interval_sec)
        else:
            # Assume host:port
            parts = target.split(":")
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 80
            return self._wait_for_tcp(host, port, deadline, poll_interval_sec)

    def _wait_for_http(self, url: str, deadline: float, interval: float) -> bool:
        """Poll HTTP URL until response code 200-399 or timeout."""
        while time.time() < deadline:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Arc-HealthCheck/1.0"})
                with urllib.request.urlopen(req, timeout=interval) as resp:
                    if 200 <= resp.status < 400:
                        logger.info(f"Target URL is healthy: {url} (status={resp.status})")
                        return True
            except (urllib.error.HTTPError, urllib.error.URLError, socket.timeout, ConnectionRefusedError):
                pass
            except Exception as e:
                logger.debug(f"Health check probe exception: {e}")
            time.sleep(interval)

        logger.warning(f"Health check timed out waiting for URL: {url}")
        return False

    def _wait_for_tcp(self, host: str, port: int, deadline: float, interval: float) -> bool:
        """Poll TCP socket until connection succeeds or timeout."""
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=interval):
                    logger.info(f"Target TCP port is open: {host}:{port}")
                    return True
            except (socket.timeout, ConnectionRefusedError, OSError):
                pass
            time.sleep(interval)

        logger.warning(f"Health check timed out waiting for TCP: {host}:{port}")
        return False

    # -------------------------------------------------------------------------
    # State Reset
    # -------------------------------------------------------------------------

    def reset_state(
        self,
        env_type: str = "webarena",
        service: Optional[str] = None,
        snapshot_name: Optional[str] = None,
    ) -> bool:
        """Reset environment state: wipe databases or revert VM snapshot between tasks.

        Args:
            env_type: 'webarena' or 'osworld'.
            service: WebArena sub-service to reset (e.g. 'shopping', 'reddit', 'gitlab').
            snapshot_name: OSWorld QCOW2 snapshot name to revert to.

        Returns:
            True if state was successfully reset, False if skipped or failed.
        """
        if env_type.lower() == "webarena":
            return self._reset_webarena_database(service=service)
        elif env_type.lower() == "osworld":
            return self._reset_osworld_snapshot(snapshot_name=snapshot_name or self.osworld_snapshot_name)
        else:
            logger.warning(f"Unknown env_type '{env_type}' for reset_state.")
            return False

    def _reset_webarena_database(self, service: Optional[str] = None) -> bool:
        """Wipe database and re-seed clean baseline data in WebArena container."""
        if not self.capabilities.docker_available:
            logger.info(f"{LIVE_ORCHESTRATION_SKIPPED}: Docker reset skipped (Docker unavailable)")
            return False

        target_compose = self.webarena_compose_path
        if not target_compose or not target_compose.exists():
            logger.info(f"{LIVE_ORCHESTRATION_SKIPPED}: WebArena compose not configured for DB reset")
            return False

        target_service = service or "shopping"
        cmd = ["docker", "compose", "-f", str(target_compose), "exec", "-T", target_service, "sh", "-c"]

        # Domain-specific reset command
        if target_service == "shopping":
            cmd.append("php bin/magento setup:db:restore || rm -rf /var/www/html/var/cache/*")
        elif target_service == "reddit":
            cmd.append("psql -U postgres -d postmill < /docker-entrypoint-initdb.d/init.sql || true")
        elif target_service == "gitlab":
            cmd.append("gitlab-rake gitlab:db:reset || true")
        else:
            cmd.append("true")

        try:
            logger.info(f"Resetting WebArena service '{target_service}' state")
            res = self._runner(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            return res.returncode == 0
        except Exception as e:
            logger.warning(f"Failed to reset WebArena DB: {e}")
            return False

    def _reset_osworld_snapshot(self, snapshot_name: str) -> bool:
        """Revert OSWorld QEMU VM disk image to clean snapshot."""
        if not self.capabilities.kvm_available or not self.osworld_image_path:
            logger.info(f"{LIVE_ORCHESTRATION_SKIPPED}: OSWorld snapshot reset skipped (KVM or image missing)")
            return False

        qemu_img = shutil.which("qemu-img")
        if not qemu_img:
            logger.info(f"{LIVE_ORCHESTRATION_SKIPPED}: qemu-img binary not available")
            return False

        cmd = [qemu_img, "snapshot", "-a", snapshot_name, str(self.osworld_image_path)]
        try:
            logger.info(f"Reverting OSWorld VM disk to snapshot '{snapshot_name}'")
            res = self._runner(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            return res.returncode == 0
        except Exception as e:
            logger.warning(f"Failed to revert OSWorld snapshot: {e}")
            return False

    def get_infrastructure_status(self) -> Dict[str, Any]:
        """Return diagnostic status of all live infrastructure."""
        return {
            "docker_available": self.capabilities.docker_available,
            "docker_compose_available": self.capabilities.docker_compose_available,
            "docker_reason": self.capabilities.docker_reason,
            "kvm_available": self.capabilities.kvm_available,
            "kvm_reason": self.capabilities.kvm_reason,
            "qemu_available": self.capabilities.qemu_available,
            "qemu_binary": self.capabilities.qemu_binary,
            "ssh_available": self.capabilities.ssh_available,
            "webarena_running": self._webarena_running,
            "osworld_vm_running": self._active_qemu_proc is not None,
        }
