"""
Cisco Channel Guard - Switch Manager
SSH connection manager using Netmiko for direct Cisco IOS communication.
"""

import threading
from datetime import datetime, timezone

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


class SwitchManager:
    """Manages a single SSH connection to a Cisco IOS switch."""

    def __init__(self):
        self._connection = None
        self._host = None
        self._username = None
        self._connected_at = None
        self._device_info = None
        self._lock = threading.Lock()

    def connect(self, host, username, password, enable_password=None):
        """Establish SSH connection to a Cisco IOS switch.

        Returns a dict with connection info on success.
        Raises RuntimeError on failure.
        """
        with self._lock:
            # Disconnect existing connection first
            self._close_unlocked()

            device = {
                "device_type": "cisco_ios",
                "host": host,
                "username": username,
                "password": password,
                "timeout": 30,
                "conn_timeout": 30,
            }
            if enable_password:
                device["secret"] = enable_password

            try:
                conn = ConnectHandler(**device)
                if enable_password:
                    conn.enable()

                # Get switch info
                info = conn.send_command("show version | include uptime")
                hostname = conn.send_command("show run | include hostname")

                self._connection = conn
                self._host = host
                self._username = username
                self._connected_at = datetime.now(timezone.utc).isoformat()
                self._device_info = info.strip()

                return {
                    "host": host,
                    "username": username,
                    "device_info": self._device_info,
                    "hostname": hostname.strip(),
                    "connected_at": self._connected_at,
                }

            except NetmikoAuthenticationException:
                raise RuntimeError(
                    "Authentication failed. Check username and password."
                )
            except NetmikoTimeoutException:
                raise RuntimeError(
                    f"Connection timed out. Verify that {host} is reachable."
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
            self._device_info = None

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
            "device_info": self._device_info if connected else None,
        }

    def send_config(self, commands):
        """Send configuration commands to the switch.

        Args:
            commands: list of IOS configuration commands.

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
            raise RuntimeError(
                "Connection lost. Please reconnect to the switch."
            )
