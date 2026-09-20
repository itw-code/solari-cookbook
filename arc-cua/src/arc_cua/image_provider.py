"""Dynamic Arc MicroVM Image and Kernel Provider.

Remediates Task 1.1:
- Eliminates hardcoded kernel and rootfs file paths.
- Resolves guest kernel and rootfs images dynamically via environment variables,
  template identifiers, standard search paths, and fallback test fixtures.
- Aligns with Arc Cloud specification (ARC_BASE_TEMPLATE, ARC_KERNEL_PATH).
"""

from __future__ import annotations

import dataclasses
import logging
import os
import tempfile
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("arc_cua.image_provider")

# Standard search paths for Arc MicroVM images in production environments
DEFAULT_SEARCH_PATHS: List[Path] = [
    Path("/usr/share/arc"),
    Path("/var/lib/arc/images"),
    Path("/opt/arc/images"),
    Path.home() / ".arc" / "images",
]


@dataclasses.dataclass(frozen=True)
class VMImageSpec:
    """Resolved specification for guest microVM kernel and rootfs drives."""
    kernel_path: Path
    rootfs_path: Path
    template_name: str
    is_mock: bool
    description: str


class ArcImageProvider:
    """Resolves and provisions microVM kernel and root filesystem images dynamically."""

    def __init__(
        self,
        base_dir: Optional[Path | str] = None,
        search_paths: Optional[List[Path]] = None,
    ):
        """Initialize image provider.

        Args:
            base_dir: Optional override directory for image assets.
            search_paths: List of filesystem search directories.
        """
        self.base_dir = Path(base_dir) if base_dir else None
        self.search_paths = list(search_paths) if search_paths else list(DEFAULT_SEARCH_PATHS)
        if self.base_dir and self.base_dir not in self.search_paths:
            self.search_paths.insert(0, self.base_dir)

    def resolve(
        self,
        template_name: Optional[str] = None,
        kernel_override: Optional[str | Path] = None,
        rootfs_override: Optional[str | Path] = None,
        allow_mock: bool = True,
    ) -> VMImageSpec:
        """Dynamically resolve guest kernel and rootfs image paths.

        Resolution precedence:
        1. Explicit overrides passed as arguments.
        2. Environment variables:
           - ARC_KERNEL_PATH
           - ARC_ROOTFS_PATH
           - ARC_IMAGE_DIR
           - ARC_BASE_TEMPLATE (defaults to 'base')
        3. Standard host image search paths.
        4. Mock fixture auto-generation if allow_mock=True.

        Returns:
            VMImageSpec with validated or provisioned paths.
        """
        # 1. Template name resolution
        template = (
            template_name
            or os.environ.get("SOLARI_BASE_TEMPLATE")
            or os.environ.get("ARC_BASE_TEMPLATE")
            or "base"
        )

        # 2. Kernel resolution
        kernel_path: Optional[Path] = None
        if kernel_override:
            kernel_path = Path(kernel_override)
        elif os.environ.get("SOLARI_KERNEL_PATH") or os.environ.get("ARC_KERNEL_PATH"):
            kernel_path = Path(os.environ.get("SOLARI_KERNEL_PATH") or os.environ["ARC_KERNEL_PATH"])
        else:
            kernel_path = self._find_in_search_paths([
                f"vmlinux-{template}",
                "vmlinux-6.1.guest",
                "vmlinux.bin",
                "vmlinux",
            ])

        # 3. Rootfs resolution
        rootfs_path: Optional[Path] = None
        if rootfs_override:
            rootfs_path = Path(rootfs_override)
        elif os.environ.get("SOLARI_ROOTFS_PATH") or os.environ.get("ARC_ROOTFS_PATH"):
            rootfs_path = Path(os.environ.get("SOLARI_ROOTFS_PATH") or os.environ["ARC_ROOTFS_PATH"])
        else:
            rootfs_path = self._find_in_search_paths([
                f"rootfs-{template}.ext4",
                f"{template}.ext4",
                "rootfs.ext4",
                "rootfs",
            ])

        # 4. Check if resolved files actually exist on host
        kernel_exists = kernel_path is not None and kernel_path.exists()
        rootfs_exists = rootfs_path is not None and rootfs_path.exists()

        if kernel_exists and rootfs_exists:
            assert kernel_path is not None and rootfs_path is not None
            return VMImageSpec(
                kernel_path=kernel_path.resolve(),
                rootfs_path=rootfs_path.resolve(),
                template_name=template,
                is_mock=False,
                description=f"Resolved live production image for template '{template}'",
            )

        # 5. Fallback: provision mock/minimal fixture if allowed
        if allow_mock:
            mock_dir = Path(tempfile.gettempdir()) / "arc_mock_images" / template
            mock_dir.mkdir(parents=True, exist_ok=True)
            mock_kernel = mock_dir / "vmlinux-mock.bin"
            mock_rootfs = mock_dir / "rootfs-mock.ext4"

            if not mock_kernel.exists():
                mock_kernel.write_bytes(b"\x7fELF" + b"\x00" * 4092)
            if not mock_rootfs.exists():
                mock_rootfs.write_bytes(b"\x00" * 8192)

            logger.info(f"Provisioned mock image fixtures for template '{template}' at {mock_dir}")
            return VMImageSpec(
                kernel_path=mock_kernel.resolve(),
                rootfs_path=mock_rootfs.resolve(),
                template_name=template,
                is_mock=True,
                description=f"Auto-provisioned mock fixture for template '{template}'",
            )

        raise FileNotFoundError(
            f"Could not resolve valid microVM images for template '{template}'. "
            f"Set ARC_KERNEL_PATH and ARC_ROOTFS_PATH or place images in {self.search_paths}."
        )

    def _find_in_search_paths(self, candidates: List[str]) -> Optional[Path]:
        """Check all search paths for candidate filenames."""
        # Also check env ARC_IMAGE_DIR if set
        dirs = list(self.search_paths)
        env_img_dir = os.environ.get("ARC_IMAGE_DIR")
        if env_img_dir:
            dirs.insert(0, Path(env_img_dir))

        for base in dirs:
            if not base.exists():
                continue
            for name in candidates:
                candidate = base / name
                if candidate.exists():
                    return candidate
        return None
