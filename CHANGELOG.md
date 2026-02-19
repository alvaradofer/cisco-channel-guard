# Changelog

All notable changes to Cisco Channel Guard are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.0.0] - 2025-02-19

### Added

**Multi-Platform Support (Stratix 5400 / 5700 / 5800)**

- `switch_manager.py`: Three-phase SSH connection with automatic IOS / IOS-XE detection.
  - Phase 1: Connect with `cisco_ios` driver (universal).
  - Phase 2: Run `show version` and parse output for `IOS-XE` / `IOS XE Software` keywords.
  - Phase 3: Reconnect with `cisco_xe` Netmiko driver if IOS-XE is detected.
  - Exposes `get_ios_type()` method so `app.py` can sync the detected platform to the
    command generator at deploy time.
  - `detect_ios_version()`: standalone helper that parses `show version` output and returns
    `ios_type`, `ios_version`, `model`, `platform`, and `netmiko_type` fields.
  - Stratix model catalog number detection from `show version` output:
    1783-HMS (5400), 1783-BMS (5700), 1783-MMS (5800), 1783-IMS (5410), 1783-ZMS (ArmorStratix).

**IOS-XE Command Syntax Support (Stratix 5800)**

- `ios_commands.py`: `_normalize_ios_version()` maps `"xe"`, `"iosxe"`, `"ios-xe"` to `"iosxe"`;
  all other values map to `"classic"`.
- On IOS-XE, generates `device-tracking tracking` instead of `ip device tracking`.
- All other security mechanism commands are identical on both platforms.
- `generate_rollback_commands()`: generates per-platform rollback commands, including
  `no device-tracking tracking` (IOS-XE) vs `no ip device tracking` (Classic).
- `generate_verify_commands()`: includes `show device-tracking database` on IOS-XE
  and `show ip device tracking all` on IOS Classic.
- `generate_summary()`: now returns `ios_version`, `platform_label`, and `security_mechanisms`
  fields in addition to the original channel/device/binding counts.

**Configuration Rollback**

- `app.py`: New `/api/preview/rollback` endpoint (GET) — returns rollback commands without
  sending them to the switch.
- `app.py`: New `/api/rollback` endpoint (POST) — removes all Channel Guard configuration
  from the connected switch and saves the running config to NVRAM.
- `index.html`: "Rollback" card in the Deploy & Verify view with confirmation dialog,
  "Preview Rollback" button, and inline output console.

**Platform Auto-Detection in the UI**

- `index.html`: IOS Version selector in the connection form with three options:
  `auto` (default), `classic`, `iosxe`.
- `index.html`: Platform detection badge displayed after successful connection,
  showing the detected Stratix model, IOS version string, and hostname.

**IEC Compliance Reference Panel**

- `index.html`: New "Compliance" sidebar tab with:
  - IEC 62443-3-3 SR mapping table (SR 5.2, SR 5.2 RE1, SR 5.3).
  - IEC 61508-1 §7.4 SFRT formula rendered inline.
  - IEC 61784-3 CIP Safety CRT formula.
  - Platform compatibility matrix (5400 / 5700 / 5800).
  - Stratix 5400 SSH prerequisite warning block.

**API Additions**

- `app.py`: `/api/version` (GET) — returns version string and supported platform list.
- `app.py`: `/api/topology/list` now includes `ios_version` field per saved file.
- `app.py`: `/api/deploy` now auto-syncs the detected IOS type from the switch connection
  to the topology before generating commands, preventing mismatches when `ios_version`
  was left as `"classic"` in the topology file but the connected switch is IOS-XE.

### Changed

- `switch_manager.py`: `connect()` now accepts an `ios_version` parameter
  (`"auto"` | `"classic"` | `"iosxe"`). Default is `"auto"`.
- `switch_manager.py`: `get_status()` now includes all detected device info fields
  (`ios_type`, `ios_version`, `model`, `platform`, `hostname`, `uptime`).
- `ios_commands.py`: `generate_commands()` now calls `_normalize_ios_version()` on the
  topology `ios_version` field, accepting `"xe"` in addition to `"classic"` / `"iosxe"`.
- `ios_commands.py`: `_static_bindings()` now skips entries with missing `mac` or `ip`
  fields gracefully, instead of raising a KeyError.
- `network.example.yml`: Updated with `ios_version: "classic"` / `"iosxe"` documentation,
  IEC compliance annotations per channel, and Stratix 5400 SSH setup instructions in comments.
- `index.html`: IOS Version selector labels updated to include model names
  (`IOS Classic - Stratix 5400 / 5700`, `IOS-XE - Stratix 5800`).
- `index.html`: Sidebar footer updated to show IEC standard references.
- `app.py`: Version constant `VERSION = "2.0.0"` added; displayed in startup banner
  and returned by `/api/version`.

### Fixed

- `ios_commands.py`: `no ip dhcp snooping information option` added to global prerequisites.
  This prevents DHCP relay agent information (option 82) insertion that can break DHCP
  for industrial devices that do not support it.
- `switch_manager.py`: `enable()` call is now wrapped in a try/except to handle switches
  where the connected user is already in privileged EXEC mode (avoids "already enabled" error).
- `switch_manager.py`: `fast_cli=False` explicitly set to prevent timing issues with
  Stratix switches that have slower CLI response than enterprise Catalyst switches.

---

## [1.0.0] - 2024 (initial release)

### Added

- Flask web application with single-page UI.
- SSH connection manager using Netmiko (`cisco_ios` driver).
- IOS command generator: DHCP Snooping, IP Source Guard, Port Security, BPDU Guard, PortFast.
- Static IP+MAC binding table per access port.
- Topology editor with YAML import/export.
- Dashboard with visual 3-level topology display.
- Deploy, Verify, and Saved Topologies views.
- Support for Stratix 5700 (IOS Classic 15.2.x).
