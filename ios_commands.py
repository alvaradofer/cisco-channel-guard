"""
Cisco Channel Guard v2.0 - IOS Command Generator

Generates platform-aware Cisco CLI commands from a network topology definition.
Supports both Cisco IOS Classic (Stratix 5400/5700) and IOS-XE (Stratix 5800).

IOS Classic (ios_version: "classic"):
  - ip device tracking
  - ip source binding <mac> vlan <id> <ip> interface <port>
  - ip verify source port-security

IOS-XE (ios_version: "iosxe"):
  - device-tracking tracking
  - ip source binding <mac> vlan <id> <ip> interface <port>  (same)
  - ip verify source port-security                           (same)

Security mechanisms deployed (compliant with IEC 62443-3-3, SR 5.2):
  1. DHCP Snooping          — prevents rogue DHCP servers
  2. IP Source Guard (IPSG) — blocks IP/MAC spoofing per port
  3. Port Security          — limits MAC count per access port
  4. BPDU Guard             — blocks unauthorized switch insertion
  5. PortFast               — fast STP convergence on access ports
"""

from typing import List, Dict, Any


# ── Internal helpers ─────────────────────────────────────────

def _normalize_ios_version(ios_version: str) -> str:
    """Normalize ios_version string to canonical form.

    Accepted inputs:  "classic", "xe", "iosxe", "ios-xe"
    Returns:          "classic" | "iosxe"
    """
    v = ios_version.lower().strip().replace("-", "").replace("_", "")
    if v in ("xe", "iosxe", "ioxe"):
        return "iosxe"
    return "classic"


def _get_vlans(channels: list) -> List[int]:
    """Return sorted unique VLAN IDs from channel list."""
    return sorted(set(int(ch["vlan"]) for ch in channels if ch.get("vlan")))


# ── Command generators ───────────────────────────────────────

def _global_prerequisites(ios_version: str, channels: list, uplinks: list) -> List[str]:
    """Generate global prerequisite commands (DHCP snooping, device tracking).

    IEC 62443-3-3 SR 5.2: Protection of the integrity of information on
    communication networks — DHCP snooping implements this at Layer 2.
    """
    cmds = []
    ios = _normalize_ios_version(ios_version)

    # DHCP Snooping — global enable
    cmds.append("ip dhcp snooping")

    # Disable option-82 insertion (prevents issues with industrial devices)
    cmds.append("no ip dhcp snooping information option")

    # DHCP Snooping — per VLAN
    for vlan in _get_vlans(channels):
        cmds.append(f"ip dhcp snooping vlan {vlan}")

    # Device tracking — syntax differs between IOS versions
    # IOS Classic (Stratix 5400/5700): ip device tracking
    # IOS-XE      (Stratix 5800):      device-tracking tracking
    # NOTE: Rockwell warns that ip device tracking may conflict with some
    #       industrial devices. Omit if only using static bindings.
    if ios == "iosxe":
        cmds.append("device-tracking tracking")
    else:
        cmds.append("ip device tracking")

    # Mark uplink ports as DHCP snooping trusted
    for uplink in uplinks:
        cmds.append(f"interface {uplink}")
        cmds.append("  ip dhcp snooping trust")

    return cmds


def _static_bindings(channels: list) -> List[str]:
    """Generate static IP source binding entries (whitelist).

    One binding per device (IP + MAC + VLAN + port).
    These are the core enforcement entries for IP Source Guard.
    Syntax is identical on IOS Classic and IOS-XE.

    IEC 62443-3-3 SR 5.2 RE(1): Network address management — static
    bindings provide a verified IP/MAC whitelist per access port.
    """
    cmds = []

    # Level 2: I/O Block bindings
    for ch in channels:
        io = ch.get("io_block", {})
        if io.get("mac") and io.get("ip"):
            cmds.append(
                f"ip source binding {io['mac']} "
                f"vlan {ch['vlan']} "
                f"{io['ip']} "
                f"interface {ch['port']}"
            )

    # Level 3: End device bindings
    for ch in channels:
        for dev in ch.get("devices", []):
            if dev.get("mac") and dev.get("ip"):
                cmds.append(
                    f"ip source binding {dev['mac']} "
                    f"vlan {ch['vlan']} "
                    f"{dev['ip']} "
                    f"interface {ch['port']}"
                )

    return cmds


def _secure_access_ports(channels: list) -> List[str]:
    """Generate per-port security configuration commands.

    COMMAND ORDER IS CRITICAL on IOS and IOS-XE:
      1. switchport mode access        — must be before port-security
      2. switchport access vlan        — assign VLAN
      3. port-security maximum N       — set limit BEFORE enabling
      4. port-security violation       — set action BEFORE enabling
      5. switchport port-security      — enable port security
      6. ip verify source port-security — enable IPSG with MAC check
      7. spanning-tree portfast        — fast STP convergence
      8. spanning-tree bpduguard       — block unauthorized switches
      9. no shutdown                   — ensure port is active

    Security mechanisms per IEC 62443-3-3:
      - ip verify source  → SR 5.2 (IPSG: IP+MAC whitelist enforcement)
      - port-security     → SR 5.2 RE(1) (MAC count limit per port)
      - bpduguard         → SR 5.3 (prevent unauthorized switch insertion)
    """
    cmds = []

    for ch in channels:
        # max_macs = I/O Block + all end devices
        max_macs = 1 + len(ch.get("devices", []))
        desc = ch.get("description", ch["port"])

        cmds.append(f"interface {ch['port']}")
        cmds.append(f"  description {desc}")
        cmds.append("  switchport mode access")
        cmds.append(f"  switchport access vlan {ch['vlan']}")
        cmds.append(f"  switchport port-security maximum {max_macs}")
        cmds.append("  switchport port-security violation restrict")
        cmds.append("  switchport port-security")
        cmds.append("  ip verify source port-security")
        cmds.append("  spanning-tree portfast")
        cmds.append("  spanning-tree bpduguard enable")
        cmds.append("  no shutdown")

    return cmds


# ── Public API ───────────────────────────────────────────────

def generate_commands(topology: Dict[str, Any]) -> List[str]:
    """Generate the full ordered list of IOS/IOS-XE configuration commands.

    Args:
        topology: dict with keys:
            ios_version: "classic" | "iosxe" (default: "classic")
            uplinks:     list of uplink port names
            channels:    list of channel dicts

    Returns:
        List of IOS CLI command strings ready to send via Netmiko.
    """
    ios_version = topology.get("ios_version", "classic")
    uplinks = topology.get("uplinks", [])
    channels = topology.get("channels", [])

    commands = []
    commands.extend(_global_prerequisites(ios_version, channels, uplinks))
    commands.extend(_static_bindings(channels))
    commands.extend(_secure_access_ports(channels))

    return commands


def generate_verify_commands(topology: Dict[str, Any]) -> List[str]:
    """Generate verification show commands.

    Produces commands to confirm all five security mechanisms are active
    after deployment. Results can be used to validate IEC 62443 compliance.

    Args:
        topology: dict with channels list.

    Returns:
        List of IOS show command strings.
    """
    ios_version = _normalize_ios_version(topology.get("ios_version", "classic"))
    channels = topology.get("channels", [])

    cmds = [
        "show ip dhcp snooping",
        "show ip source binding",
        "show ip verify source",
        "show port-security",
    ]

    # IOS-XE: device-tracking has its own show command
    if ios_version == "iosxe":
        cmds.append("show device-tracking database")
    else:
        cmds.append("show ip device tracking all")

    # Per-port verification
    for ch in channels:
        cmds.append(f"show port-security interface {ch['port']}")
        cmds.append(f"show ip verify source interface {ch['port']}")
        cmds.append(f"show spanning-tree interface {ch['port']} detail")

    return cmds


def generate_rollback_commands(topology: Dict[str, Any]) -> List[str]:
    """Generate commands to remove all Channel Guard configuration (rollback).

    Useful for testing or undoing a deployment without factory-resetting.

    Args:
        topology: dict with channels and uplinks.

    Returns:
        List of IOS CLI command strings to remove Channel Guard config.
    """
    ios_version = _normalize_ios_version(topology.get("ios_version", "classic"))
    channels = topology.get("channels", [])
    uplinks = topology.get("uplinks", [])

    cmds = []

    # Remove static bindings
    for ch in channels:
        io = ch.get("io_block", {})
        if io.get("mac") and io.get("ip"):
            cmds.append(
                f"no ip source binding {io['mac']} "
                f"vlan {ch['vlan']} {io['ip']} interface {ch['port']}"
            )
        for dev in ch.get("devices", []):
            if dev.get("mac") and dev.get("ip"):
                cmds.append(
                    f"no ip source binding {dev['mac']} "
                    f"vlan {ch['vlan']} {dev['ip']} interface {ch['port']}"
                )

    # Remove port security per interface
    for ch in channels:
        cmds.append(f"interface {ch['port']}")
        cmds.append("  no ip verify source")
        cmds.append("  no switchport port-security")
        cmds.append("  no spanning-tree bpduguard enable")
        cmds.append("  no spanning-tree portfast")

    # Remove uplink trust
    for uplink in uplinks:
        cmds.append(f"interface {uplink}")
        cmds.append("  no ip dhcp snooping trust")

    # Remove global settings
    vlans = _get_vlans(channels)
    for vlan in vlans:
        cmds.append(f"no ip dhcp snooping vlan {vlan}")
    cmds.append("no ip dhcp snooping")

    if ios_version == "iosxe":
        cmds.append("no device-tracking tracking")
    else:
        cmds.append("no ip device tracking")

    return cmds


def generate_summary(topology: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a human-readable summary of the topology.

    Returns:
        Dict with topology statistics.
    """
    ios_version = _normalize_ios_version(topology.get("ios_version", "classic"))
    channels = topology.get("channels", [])
    total_devices = sum(len(ch.get("devices", [])) for ch in channels)
    vlans = _get_vlans(channels)

    platform_map = {
        "classic": "IOS Classic (Stratix 5400 / 5700)",
        "iosxe": "IOS-XE (Stratix 5800)",
    }

    return {
        "channels": len(channels),
        "io_blocks": len(channels),
        "devices": total_devices,
        "bindings": total_devices + len(channels),
        "vlans": vlans,
        "ios_version": ios_version,
        "platform_label": platform_map.get(ios_version, ios_version),
        "total_commands": len(generate_commands(topology)),
        "security_mechanisms": [
            "DHCP Snooping",
            "IP Source Guard (IPSG)",
            "Port Security",
            "BPDU Guard",
            "PortFast",
        ],
    }
