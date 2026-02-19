"""
Cisco Channel Guard v2.0 - Switch Manager
SSH connection manager with multi-platform support:
  - Stratix 5400 / 5700  → Cisco IOS Classic (cisco_ios)
  - Stratix 5800         → Cisco IOS-XE     (cisco_xe)

Supports auto-detection of IOS version from 'show version' output.
"""

import re
import threading
from datetime import datetime, timezone

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


# ── IOS version detection ────────────────────────────────────

STRATIX_MODELS = {
    "1783-HMS": "Stratix 5400",
    "1783-BMS": "Stratix 5700",
    "1783-ZMS": "ArmorStratix 5700",
    "1783-MMS": "Stratix 5800",
    "1783-IMS": "Stratix 5410",
}


def detect_ios_version(show_version_output: str) -> dict:
    """Parse 'show version' to determine IOS type, version, and switch model.

    Returns:
        dict with keys:
            ios_type:    "classic" | "iosxe"
            ios_version: version string, e.g. "15.2(6)E2" or "16.12.4"
            model:       detected model string
            platform:    human-readable platform name
            netmiko_type: Netmiko device_type string
    """
    text = show_version_output

    # Detect IOS-XE (Stratix 5800)
    is_xe = bool(
        re.search(r"IOS[\s-]+XE", text, re.IGNORECASE)
        or re.search(r"XE Software", text, re.IGNORECASE)
    )

    # Extract IOS version number
    version_match = re.search(
        r"(?:Cisco IOS Software.*?Version|Version)\s+([\d().a-zA-Z]+)",
        text,
        re.IGNORECASE,
    )
    ios_version_str = version_match.group(1) if version_match else "Unknown"

    # Detect Stratix model from catalog number
    model_str = "Unknown"
    platform_str = "Cisco IOS Switch"

    for catalog, name in STRATIX_MODELS.items():
        if catalog in text:
            model_str = catalog
            platform_str = name
            break

    # Fallback: look for generic Catalyst / WS-C model
    if model_str == "Unknown":
        cat_match = re.search(r"(WS-C[\w-]+|C\d{4}[\w-]+)", text)
        if cat_match:
            model_str = cat_match.group(1)
            platform_str = f"Cisco Catalyst {model_str}"

    return {
        "ios_type": "iosxe" if is_xe else "classic",
        "ios_version": ios_version_str,
        "model": model_str,
        "platform": platform_str,
        "netmiko_type": "cisco_xe" if is_xe else "cisco_ios",
    }


# ── SwitchManager ────────────────────────────────────────────

class SwitchManager:
    """
    Manages a single SSH connection to a Cisco IOS / IOS-XE switch.

    Supported platforms:
      - Stratix 5400 (1783-HMS) — IOS Classic, device_type: cisco_ios
      - Stratix 5700 (1783-BMS) — IOS Classic, device_type: cisco_ios
      - Stratix 5800 (1783-MMS) — IOS-XE,     device_type: cisco_xe
    """

    def __init__(self):
        self._connection = None
        self._host = None
        self._username = None
        self._connected_at = None
        self._device_info = {}
        self._lock = threading.Lock()

    def connect(self, host, username, password, enable_password=None, ios_version="auto"):
        """Establish SSH connection to a Cisco IOS or IOS-XE switch.

        Args:
            host:            Switch management IP address.
            username:        SSH username (privilege 15 recommended).
            password:        SSH password.
            enable_password: Enable secret (optional, used if needed).
            ios_version:     "auto" | "classic" | "iosxe"
                             "auto" → connect with cisco_ios first, then
                             run 'show version' to detect and reconnect if XE.

        Returns:
            dict with connection details including detected platform info.
        Raises:
            RuntimeError on connection failure.
        """
        with self._lock:
            self._close_unlocked()

            # ── Phase 1: Determine Netmiko device_type ────────────
            if ios_version == "iosxe":
                netmiko_type = "cisco_xe"
            elif ios_version == "classic":
                netmiko_type = "cisco_ios"
            else:
                # auto: start with cisco_ios (works for both in most cases)
                netmiko_type = "cisco_ios"

            device = {
                "device_type": netmiko_type,
                "host": host,
                "username": username,
                "password": password,
                "timeout": 30,
                "conn_timeout": 30,
                "fast_cli": False,
            }
            if enable_password:
                device["secret"] = enable_password

            try:
                conn = ConnectHandler(**device)
                if enable_password:
                    try:
                        conn.enable()
                    except Exception:
                        pass  # Already in privileged mode

                # ── Phase 2: Detect IOS version ───────────────────
                show_ver = conn.send_command("show version", read_timeout=30)
                detected = detect_ios_version(show_ver)

                # ── Phase 3: Reconnect with cisco_xe if needed ────
                # If we connected as cisco_ios but it's actually IOS-XE
                if (ios_version == "auto"
                        and detected["netmiko_type"] == "cisco_xe"
                        and netmiko_type == "cisco_ios"):
                    try:
                        conn.disconnect()
                    except Exception:
                        pass

                    device["device_type"] = "cisco_xe"
                    conn = ConnectHandler(**device)
                    if enable_password:
                        try:
                            conn.enable()
                        except Exception:
                            pass
                    # Re-run show version on new connection
                    show_ver = conn.send_command("show version", read_timeout=30)
                    detected = detect_ios_version(show_ver)

                # ── Phase 4: Gather switch info ───────────────────
                hostname_raw = conn.send_command(
                    "show running-config | include hostname",
                    read_timeout=15
                )
                hostname = hostname_raw.replace("hostname", "").strip()

                uptime_raw = conn.send_command(
                    "show version | include uptime",
                    read_timeout=15
                )

                self._connection = conn
                self._host = host
                self._username = username
                self._connected_at = datetime.now(timezone.utc).isoformat()
                self._device_info = {
                    **detected,
                    "hostname": hostname,
                    "uptime": uptime_raw.strip(),
                }

                return {
                    "host": host,
                    "username": username,
                    "connected_at": self._connected_at,
                    **self._device_info,
                }

            except NetmikoAuthenticationException:
                raise RuntimeError(
                    "Authentication failed. Check username and password."
                )
            except NetmikoTimeoutException:
                raise RuntimeError(
                    f"Connection timed out. Verify that {host} is reachable "
                    f"and SSH is enabled (requires Cryptographic IOS image on Stratix 5400)."
                )
            except Exception as e:
                raise RuntimeError(f"Connection failed: {e}")

    def disconnect(self):
        """Close the SSH connection."""
        with self._lock:
            self._close_unlocked()

    def _close_unlocked(self):
        """Close connection without acquiring the lock (caller must hold it)."""
        if self._connection:
            try:
                self._connection.disconnect()
            except Exception:
                pass
            self._connection = None
            self._host = None
            self._username = None
            self._connected_at = None
            self._device_info = {}

    def is_connected(self):
        """Check if the SSH connection is still alive."""
        with self._lock:
            if self._connection is None:
                return False
            try:
                return self._connection.is_alive()
            except Exception:
                return False

    def get_status(self):
        """Return current connection status."""
        connected = self.is_connected()
        return {
            "connected": connected,
            "host": self._host if connected else None,
            "username": self._username if connected else None,
            "connected_at": self._connected_at if connected else None,
            **({k: v for k, v in self._device_info.items()} if connected else {}),
        }

    def get_ios_type(self):
        """Return detected ios_type string: 'classic' | 'iosxe' | None."""
        return self._device_info.get("ios_type") if self._connection else None

    def send_config(self, commands):
        """Send configuration commands to the switch.

        Args:
            commands: list of IOS/IOS-XE configuration command strings.

        Returns:
            Command output string.
        Raises:
            RuntimeError if not connected or command fails.
        """
        with self._lock:
            self._ensure_connected()
            try:
                output = self._connection.send_config_set(
                    commands,
                    cmd_verify=False,
                    exit_config_mode=True,
                    read_timeout=60,
                )
                return output
            except Exception as e:
                raise RuntimeError(f"Failed to send configuration: {e}")

    def send_command(self, command):
        """Send a single show/exec command.

        Returns:
            Command output string.
        """
        with self._lock:
            self._ensure_connected()
            try:
                return self._connection.send_command(command, read_timeout=30)
            except Exception as e:
                raise RuntimeError(f"Command failed: {e}")

    def save_config(self):
        """Save running configuration to NVRAM (write memory)."""
        with self._lock:
            self._ensure_connected()
            try:
                return self._connection.save_config()
            except Exception as e:
                raise RuntimeError(f"Failed to save configuration: {e}")

    def _ensure_connected(self):
        """Verify connection is alive. Must be called with lock held."""
        if self._connection is None:
            raise RuntimeError("Not connected to any switch.")
        try:
            if not self._connection.is_alive():
                self._close_unlocked()
                raise RuntimeError(
                    "Connection lost. Please reconnect to the switch."
                )
        except RuntimeError:
            raise
        except Exception:
            self._close_unlocked()
            raise RuntimeError("Connection lost. Please reconnect to the switch.")
