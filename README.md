# Cisco Channel Guard

> Created by **Nahum Alvarado** ([@alvaradofer](https://github.com/alvaradofer))

Self-contained web application to configure Allen-Bradley Stratix switches with **IP Source Guard**,
**Port Security**, **DHCP Snooping**, **BPDU Guard**, and **PortFast** for industrial OT networks
with a 3-level topology: Switch -> I/O Block -> Peripheral Devices.

---

## What is New in v2.0

Version 2.0 extends support to the full Allen-Bradley Stratix managed switch family and adds
configuration rollback, platform auto-detection, and a built-in compliance reference panel.

| Feature | v1.x | v2.0 |
|---|:---:|:---:|
| Stratix 5700 (IOS Classic) | Yes | Yes |
| Stratix 5400 (IOS Classic) | No | Yes |
| Stratix 5800 (IOS-XE) | No | Yes |
| Platform auto-detection on connect | No | Yes |
| Configuration rollback (undo without factory reset) | No | Yes |
| Rollback preview | No | Yes |
| IEC 62443 / IEC 61508 compliance reference panel | No | Yes |
| device-tracking tracking (IOS-XE syntax) | No | Yes |

---

## Problem It Solves

In industrial networks, devices (printers, barcode readers, cameras) connect to
the switch through an intermediate I/O Block. This creates a "daisy chain" where
multiple devices share a single switch port.

Without protection, anyone can unplug a device and connect a laptop, gaining
network access. **Channel Guard** blocks this by creating a strict whitelist
of allowed IP addresses and MAC addresses per port - enforced at hardware speed
by the switch ASIC, not by polling software.

---

## Supported Platforms

| Switch | Catalog Number | IOS | Netmiko Driver |
|---|---|---|---|
| Stratix 5400 | 1783-HMS | Classic 15.2(x)EA | cisco_ios |
| Stratix 5700 | 1783-BMS | Classic 15.2(x)EA | cisco_ios |
| Stratix 5800 | 1783-MMS | IOS-XE 16.x+ | cisco_xe |

> **Stratix 5400 prerequisite:** SSH requires the Cryptographic IOS image (K9 license).
> See the "Enabling SSH on Stratix 5400" section below.

---

## 3-Level Topology

```
                    +--------------+
                    |    SWITCH    |
                    |  Stratix     |
                    +--+---+---+--+
            Level 1    |   |   |     Physical ports
                       |   |   |     (IP Source Guard + Port Security + BPDU Guard)
                    +--+   |   +--+
                    v      v      v
              +---------+ ... +---------+
              | I/O     |     | I/O     |
              | Block   |     | Block   |
              +--+---+--+     +--+---+--+
          Level 2|   |           |   |    I/O Blocks (static IP+MAC binding)
                 |   |           |   |
              +--+   +--+    +--+   +--+
              v         v    v         v
          +--------+ +--------+ +--------+ +--------+
          |Printer | |Barcode | |Camera  | |Printer |
          |        | |Reader  | |        | |        |
          +--------+ +--------+ +--------+ +--------+
              Level 3: Devices with static IP+MAC whitelists
```

---

## Security Mechanisms

| Mechanism | What It Blocks | IEC 62443-3-3 Requirement |
|---|---|---|
| DHCP Snooping | Rogue DHCP servers, IP starvation attacks | SR 5.2 |
| IP Source Guard (IPSG) | IP spoofing, unauthorized device injection | SR 5.2 RE(1) |
| Port Security | MAC flooding, extra devices beyond the whitelist | SR 5.2 RE(1) |
| BPDU Guard | Unauthorized switch insertion, STP topology attacks | SR 5.3 |
| PortFast | STP 30-second convergence delay on access ports | IEC 61784-3 CIP Safety RPI |

Once deployed, Channel Guard exits the data path entirely. The switch ASIC enforces all
rules at **1-5 microseconds per frame** - zero latency added to the CIP Safety bus.

---

## Requirements

### On your machine

```bash
# Python 3.8+
python3 --version

# Install dependencies
pip3 install -r requirements.txt
```

### On the Cisco switch

- SSH enabled with a privilege-15 user
- For Stratix 5400: Cryptographic IOS image (K9 license) required for SSH

---

## Quick Start

```bash
git clone https://github.com/alvaradofer/cisco-channel-guard.git
cd cisco-channel-guard
pip3 install -r requirements.txt
python3 app.py
```

Open **http://localhost:5050** in your browser.

---

## Web Interface - 5 Sections

| Section | Description |
|---|---|
| Dashboard | Visual topology display with stats |
| Topology Editor | Add/edit channels, I/O blocks, devices. Import/export YAML |
| Deploy & Verify | Connect via SSH, preview commands, deploy, verify, rollback |
| Saved Topologies | Save, load, and manage multiple topology files |
| Compliance | Built-in IEC 62443-3-3 / IEC 61508 reference with timing formulas |

---

## How It Works

1. **Define topology** in the editor (or import a YAML file)
2. **Connect to the switch** via SSH - platform is auto-detected
3. **Preview** the generated IOS / IOS-XE commands
4. **Deploy** the configuration
5. **Verify** that all bindings and security settings are active
6. If needed: **Rollback** removes all Channel Guard config cleanly (no factory reset required)

---

## Topology File Format

```yaml
# ios_version:
#   "classic"  ->  Stratix 5400 / 5700  (IOS 15.2.x, Netmiko driver: cisco_ios)
#   "iosxe"    ->  Stratix 5800          (IOS-XE 16.x, Netmiko driver: cisco_xe)
ios_version: "classic"

uplinks:
  - GigabitEthernet1/0/48   # trusted uplink toward router / GuardLogix

channels:
  - port: GigabitEthernet1/0/1
    vlan: 10
    description: "Robot Cell A"

    io_block:
      name: "IO_Block_CellA"
      ip: "192.168.10.1"
      mac: "0011.2233.4455"      # Cisco format: xxxx.xxxx.xxxx

    devices:
      - name: "Label_Printer"
        type: "printer"
        ip: "192.168.10.10"
        mac: "aa00.bb11.cc22"

      - name: "Barcode_Reader_01"
        type: "reader"
        ip: "192.168.10.11"
        mac: "dd44.ee55.ff66"
```

---

## IOS Commands Generated

### IOS Classic (Stratix 5400 / 5700)

```
! Global prerequisites
ip dhcp snooping
ip dhcp snooping vlan 10
no ip dhcp snooping information option
ip device tracking                      <- IOS Classic syntax

interface GigabitEthernet1/0/48
  ip dhcp snooping trust                <- uplink = trusted

! Static IP+MAC bindings (whitelist)
ip source binding 0011.2233.4455 vlan 10 192.168.10.1  interface GigabitEthernet1/0/1
ip source binding aa00.bb11.cc22 vlan 10 192.168.10.10 interface GigabitEthernet1/0/1
ip source binding dd44.ee55.ff66 vlan 10 192.168.10.11 interface GigabitEthernet1/0/1

! Access port security
interface GigabitEthernet1/0/1
  description Robot Cell A
  switchport mode access
  switchport access vlan 10
  switchport port-security maximum 3    <- 1 I/O Block + 2 devices
  switchport port-security violation restrict
  switchport port-security
  ip verify source port-security        <- IP Source Guard with MAC check
  spanning-tree portfast
  spanning-tree bpduguard enable
  no shutdown
```

### IOS-XE (Stratix 5800)

The only difference from IOS Classic is the device tracking command:

```
device-tracking tracking               <- replaces "ip device tracking"
```

All other commands (`ip source binding`, `ip verify source`, `switchport port-security`,
`spanning-tree bpduguard`) are **identical** on IOS Classic and IOS-XE.

---

## Platform Auto-Detection

When connecting, leave **IOS Version** on **"Auto-detect (recommended)"**.
Channel Guard v2.0 will:

1. Connect using `cisco_ios` driver (works for initial handshake on both platforms)
2. Run `show version` and search for `IOS-XE` or `IOS XE Software` in the output
3. If IOS-XE is detected: disconnect and reconnect using the `cisco_xe` driver
4. Display the detected platform, firmware version, and hostname in the UI badge
5. Generate all configuration commands using the correct syntax for the platform

You can also manually select `IOS Classic` or `IOS-XE` if auto-detect is not needed.

---

## Configuration Rollback

The **Rollback** button in the Deploy & Verify section removes all Channel Guard
configuration from the switch without requiring a factory reset:

- Removes all static `ip source binding` entries
- Removes `ip verify source` from all secured access ports
- Removes `switchport port-security` from all secured access ports
- Removes `spanning-tree bpduguard enable` and `portfast` from all secured ports
- Removes `ip dhcp snooping` globally
- Removes `ip device tracking` (IOS Classic) or `device-tracking tracking` (IOS-XE)

Use **"Preview Rollback"** to review the undo commands before sending them to the switch.

---

## Enabling SSH on Stratix 5400

The Stratix 5400 requires the **Cryptographic IOS image (K9 license)** for SSH.
Verify and configure:

```
! Step 1: Confirm K9 image is installed
show version | include K9
! Expected: ...cryptok9-mz... or similar string containing K9

! Step 2: Generate RSA keys (only once - skip if keys already exist)
ip domain-name plant.local
crypto key generate rsa modulus 2048
ip ssh version 2

! Step 3: Enable SSH on VTY lines and disable Telnet
line vty 0 15
 transport input ssh
 login local

! Step 4: Create privileged user
username admin privilege 15 secret YourSecurePassword
```

**Note:** Rockwell Automation documents that `ip device tracking` may conflict with some
industrial devices, including certain Rockwell I/O modules. If you observe connectivity
issues with field devices after deploying Channel Guard on a Stratix 5400, run
`no ip device tracking` globally. The static `ip source binding` entries that Channel Guard
uses work independently of the device tracking table.

---

## VLAN Segmentation Recommendation

If GuardLogix safety I/O shares the same switch, segment using VLANs:

| Zone | VLAN | Apply Channel Guard | Notes |
|---|---|:---:|---|
| CIP Safety (GuardLogix to Safety I/O) | 100 | No | Uplink = DHCP trusted |
| Standard OT devices (printers, cameras) | 10-99 | Yes | IP Source Guard active |
| Management | 999 | No | Uplink = DHCP trusted |

Safety I/O ports should always be on a separate VLAN configured as DHCP trusted.
Channel Guard should never be applied to ports carrying CIP Safety traffic.

---

## How to Find MAC Addresses

| Method | Command |
|---|---|
| From the switch | `show mac address-table` |
| From Windows | `arp -a` or `getmac` |
| From Linux | `ip neighbor` or `arp -n` |
| Physical device label | Check the sticker on the device |

**Cisco format:** `xxxx.xxxx.xxxx`

The web editor auto-converts any standard format:
`AA:00:BB:11:CC:22` -> `aa00.bb11.cc22`

---

## Project Structure

```
cisco-channel-guard/
├── app.py                   <- Flask web application (API routes + YAML management)
├── switch_manager.py        <- SSH connection manager with platform auto-detection
├── ios_commands.py          <- IOS/IOS-XE command generator and rollback generator
├── requirements.txt         <- Python dependencies
├── network.example.yml      <- Annotated reference topology file
├── templates/
│   └── index.html           <- Single-page web app (CSS + JS inline, no build step)
└── topologies/              <- Saved topology YAML files (created at runtime)
```

---

## IEC Compliance Summary

Channel Guard v2.0 implements the following IEC 62443-3-3 Security Requirements:

| Standard | Requirement | Description | Mechanism |
|---|---|---|---|
| IEC 62443-3-3 | SR 5.2 | Network and Communication Integrity | DHCP Snooping |
| IEC 62443-3-3 | SR 5.2 RE(1) | Network address management (IP/MAC whitelist per port) | IP Source Guard + Port Security |
| IEC 62443-3-3 | SR 5.2 RE(2) | Network resource availability | Port Security (restrict mode) |
| IEC 62443-3-3 | SR 5.3 | Boundary protection against unauthorized switches | BPDU Guard |

**IEC 61508 Safety Path Timing** - Channel Guard adds zero latency to the safety bus:

```
IEC 61508-1 §7.4: SFRT <= (1/2) x PST

SFRT = T_ASIC + T_RPI + T_jitter + T_safety_task + T_output
     = 0.003ms + 10ms + 2ms + 10ms + 3ms
     = 25ms  <=  (1/2) x 50ms  ->  COMPLIANT

T_ASIC = 0.003ms is the Channel Guard ASIC enforcement latency (effectively zero)
```

The built-in **Compliance** tab in the app shows the full reference with all formulas,
standard clause citations, and timing calculations.

---

## Troubleshooting

### Cannot connect to the switch

```bash
# Test basic connectivity
ping 192.168.1.1

# Test SSH manually
ssh admin@192.168.1.1
```

Verify SSH is enabled on the switch and the user has privilege 15.
For Stratix 5400: confirm K9 image is installed with `show version | include K9`.

### A legitimate device has no connectivity after deploy

```
show ip source binding
show ip verify source
show port-security interface GigabitEthernet1/0/1
show mac address-table interface GigabitEthernet1/0/1
```

Confirm the device MAC address and IP address in your topology file exactly match
the values on the physical device. Use the **Verify** button in the app - it runs
all these commands and displays the output.

### IOS-XE device not recognized by auto-detect

Manually set **IOS Version** to `IOS-XE - Stratix 5800` in the connection form
before clicking Connect.

### ip device tracking causes issues with Rockwell industrial devices

```
no ip device tracking
```

Then redeploy from Channel Guard. The static bindings will still be enforced by
IP Source Guard without the device tracking table.

---

## What Happens If...

| Scenario | Result |
|---|---|
| Someone unplugs a device and connects a laptop | Traffic blocked - IP/MAC does not match binding |
| A rogue switch is connected to the I/O Block | BPDU Guard errdisables the port immediately |
| A 3rd unauthorized device is added to a port | Port Security drops its frames (restrict mode, no port shutdown) |
| The switch reboots | Config persists - saved to NVRAM |
| Channel Guard is deployed twice (same topology) | Idempotent - commands re-apply safely |
| Rollback is executed | All Channel Guard config removed cleanly, no factory reset required |

---

## License

Licensed under the **Apache License 2.0** - see [LICENSE](LICENSE) for details.

---

## Disclaimer

This software is provided "as is", without warranty of any kind, express or implied.
**Use at your own risk.** The author is not responsible for any damage, data loss,
network disruption, or security incidents resulting from the use of this tool.

Always test configurations in a lab environment before deploying to production networks.

---

## Trademark Notice

**Cisco**, **Cisco IOS**, **Cisco IOS-XE**, **Allen-Bradley**, **Stratix**, **GuardLogix**,
and all related product names, logos, and trademarks are the property of their respective owners
(**Cisco Systems, Inc.** and **Rockwell Automation, Inc.**). This project is not affiliated
with, endorsed by, sponsored by, or in any way officially connected to Cisco Systems, Inc.
or Rockwell Automation, Inc. All product and company names are used for identification purposes only.
