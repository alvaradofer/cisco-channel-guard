"""
Cisco Channel Guard - IOS Command Generator
Generates Cisco IOS CLI commands from a network topology definition.

Replicates the exact logic from the Ansible role:
  - roles/channel_guard/tasks/prerequisites.yml
  - roles/channel_guard/tasks/bindings.yml
  - roles/channel_guard/tasks/ports.yml
"""


def generate_commands(topology):
    """Generate the full ordered list of IOS configuration commands.

    Args:
        topology: dict with keys: ios_version, uplinks, channels.

    Returns:
        List of IOS CLI command strings.
    """
    commands = []

    ios_version = topology.get("ios_version", "classic")
    uplinks = topology.get("uplinks", [])
    channels = topology.get("channels", [])

    # ── Step 1: Global prerequisites ──────────────────────────
    # (from prerequisites.yml)

    # Enable DHCP snooping globally
    commands.append("ip dhcp snooping")

    # Enable DHCP snooping per VLAN (deduplicated)
    vlans = sorted(set(ch["vlan"] for ch in channels))
    for vlan in vlans:
        commands.append(f"ip dhcp snooping vlan {vlan}")

    # Enable device tracking
    if ios_version == "xe":
        commands.append("device-tracking tracking")
    else:
        commands.append("ip device tracking")

    # Mark uplinks as DHCP snooping trusted
    for uplink in uplinks:
        commands.append(f"interface {uplink}")
        commands.append("  ip dhcp snooping trust")

    # ── Step 2: Static IP source bindings ─────────────────────
    # (from bindings.yml)

    # Level 2: I/O Block bindings
    for ch in channels:
        io = ch.get("io_block", {})
        commands.append(
            f"ip source binding {io['mac']} "
            f"vlan {ch['vlan']} "
            f"{io['ip']} "
            f"interface {ch['port']}"
        )

    # Level 3: End device bindings
    for ch in channels:
        for dev in ch.get("devices", []):
            commands.append(
                f"ip source binding {dev['mac']} "
                f"vlan {ch['vlan']} "
                f"{dev['ip']} "
                f"interface {ch['port']}"
            )

    # ── Step 3: Secure access ports ──────────────────────────
    # (from ports.yml)
    # COMMAND ORDER MATTERS:
    #   1. switchport mode access (first)
    #   2. switchport access vlan
    #   3. port-security maximum and violation (before enabling)
    #   4. switchport port-security (enable)
    #   5. ip verify source (IP Source Guard)

    for ch in channels:
        max_macs = len(ch.get("devices", [])) + 1  # devices + I/O block
        commands.append(f"interface {ch['port']}")
        commands.append(f"  description {ch.get('description', '')}")
        commands.append("  switchport mode access")
        commands.append(f"  switchport access vlan {ch['vlan']}")
        commands.append(f"  switchport port-security maximum {max_macs}")
        commands.append("  switchport port-security violation restrict")
        commands.append("  switchport port-security")
        commands.append("  ip verify source port-security")
        commands.append("  spanning-tree portfast")
        commands.append("  spanning-tree bpduguard enable")
        commands.append("  no shutdown")

    return commands


def generate_verify_commands(topology):
    """Generate show commands for verification.

    Args:
        topology: dict with keys: channels.

    Returns:
        List of IOS show command strings.
    """
    commands = [
        "show ip source binding",
        "show ip verify source",
        "show ip dhcp snooping",
        "show port-security",
    ]
    for ch in topology.get("channels", []):
        commands.append(f"show port-security interface {ch['port']}")
    return commands


def generate_summary(topology):
    """Generate a human-readable summary of the topology.

    Returns:
        Dict with topology statistics.
    """
    channels = topology.get("channels", [])
    total_devices = sum(len(ch.get("devices", [])) for ch in channels)
    vlans = sorted(set(ch.get("vlan", 0) for ch in channels))

    return {
        "channels": len(channels),
        "io_blocks": len(channels),
        "devices": total_devices,
        "bindings": total_devices + len(channels),
        "vlans": vlans,
        "total_commands": len(generate_commands(topology)),
    }
