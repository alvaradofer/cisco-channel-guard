# Cisco Channel Guard

> Created by **Nahum Alvarado** ([@alvaradofer](https://github.com/alvaradofer))

Self-contained web application to configure Cisco switches with **IP Source Guard** and
**Port Security** for industrial networks with a 3-level topology:
Switch -> I/O Block -> Peripheral Devices.

## Problem It Solves

In industrial networks, devices (printers, barcode readers, cameras) connect to
the switch through an intermediate I/O Block. This creates a "daisy chain" where
multiple devices share a single switch port.

Without protection, anyone can unplug a device and connect a laptop, gaining
network access. **Channel Guard** blocks this by creating a strict whitelist
of allowed IPs and MACs per port.

## 3-Level Topology

```
                    +--------------+
                    |    SWITCH    |
                    |  Cisco IOS   |
                    +--+---+---+--+
            Level 1    |   |   |     Physical ports
                       |   |   |
                    +--+   |   +--+
                    v      v      v
              +---------+ ... +---------+
              | I/O     |     | I/O     |
              | Block   |     | Block   |
              +--+---+--+     +--+---+--+
          Level 2|   |           |   |    I/O Blocks
                 |   |           |   |
              +--+   +--+    +--+   +--+
              v         v    v         v
          +--------+ +--------+ +--------+ +--------+
          |Printer | |Barcode | |Camera  | |Printer |
          |        | |Reader  | |        | |        |
          +--------+ +--------+ +--------+ +--------+
              Level 3: Devices with static IPs
```

## Security Applied Per Port

| Mechanism | Function |
|---|---|
| **IP Source Guard** | Only allows traffic from IPs/MACs registered in static bindings |
| **Port Security** | Limits MAC count to exactly the number of known devices |
| **DHCP Snooping** | Required by IP Source Guard; prevents rogue DHCP servers |
| **BPDU Guard** | Disables the port if an unauthorized switch is connected |
| **PortFast** | Speeds up STP convergence on access ports |

## Requirements

### On your laptop

```bash
# Python 3.8+
python3 --version

# Install dependencies (Flask + Netmiko)
pip3 install -r requirements.txt
```

### On the Cisco switch

- IOS 12.2(50)+ or IOS-XE 16.x+
- SSH enabled
- User with privilege 15 or enable access

## Quick Start

```bash
cd cisco-channel-guard
pip3 install -r requirements.txt
python3 app.py
```

Then open **http://localhost:5050** in your browser.

The web interface has 4 sections:

1. **Dashboard** - Visual topology display with stats and security info
2. **Topology Editor** - Forms to add/edit channels, I/O blocks, and devices. Import/export YAML
3. **Deploy & Verify** - Connect to a switch via SSH, preview IOS commands, deploy, and verify
4. **Saved Topologies** - Save, load, and manage multiple topology configurations

## How It Works

1. **Define your topology** in the editor (or import a YAML file)
2. **Connect to a switch** via SSH (enter IP, username, password)
3. **Preview** the IOS commands that will be generated
4. **Deploy** the configuration to the switch
5. **Verify** that bindings and security settings are active

### Save and Apply to Another Switch

You can save a topology configuration and apply it to a different switch:

1. Create your topology in the editor
2. Click **"Save Current As..."** in the Saved Topologies section
3. Connect to a different switch
4. Load the saved topology and deploy

### Import/Export

- **Export**: Download your topology as a YAML file
- **Import**: Upload a YAML file to load a topology from another machine

## Network Topology Format

Each **channel** represents a switch port with its device chain:

```yaml
ios_version: "classic"
uplinks:
  - GigabitEthernet1/0/48

channels:
  - port: GigabitEthernet1/0/1
    vlan: 10
    description: "Robot Cell A"

    io_block:
      name: "IO_Block_CellA"
      ip: "192.168.10.1"
      mac: "0011.2233.4455"

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

## Project Structure

```
cisco-channel-guard/
├── app.py                  <- Web application (Flask)
├── switch_manager.py       <- SSH connection manager (Netmiko)
├── ios_commands.py          <- IOS command generator
├── requirements.txt         <- Python dependencies
├── network.example.yml      <- Example topology for reference
├── templates/
│   └── index.html           <- Single-page web app (self-contained)
└── topologies/              <- Saved topology files
```

## IOS Commands Generated

For a channel with 1 I/O Block and 2 devices, the tool generates:

```
! Global
ip dhcp snooping
ip dhcp snooping vlan 10
ip device tracking

! Uplink
interface GigabitEthernet1/0/48
  ip dhcp snooping trust

! Bindings (IP+MAC whitelist)
ip source binding 0011.2233.4455 vlan 10 192.168.10.1 interface GigabitEthernet1/0/1
ip source binding aa00.bb11.cc22 vlan 10 192.168.10.10 interface GigabitEthernet1/0/1
ip source binding dd44.ee55.ff66 vlan 10 192.168.10.11 interface GigabitEthernet1/0/1

! Access port
interface GigabitEthernet1/0/1
  description Robot Cell A
  switchport mode access
  switchport access vlan 10
  switchport port-security maximum 3
  switchport port-security violation restrict
  switchport port-security
  ip verify source port-security
  spanning-tree portfast
  spanning-tree bpduguard enable
  no shutdown
```

## How to Find MAC Addresses

| Method | Command |
|---|---|
| From the switch | `show mac address-table` |
| From Windows | `arp -a` or `getmac` |
| From Linux | `ip neighbor` or `arp -n` |
| Physical label | Check the device sticker |

**Cisco format:** `xxxx.xxxx.xxxx` (no dashes or colons)

The web editor auto-converts formats: `AA:00:BB:11:CC:22` -> `aa00.bb11.cc22`

## What Happens If...

| Scenario | Result |
|---|---|
| Someone unplugs a device and plugs in a laptop | Switch blocks traffic (IP/MAC doesn't match binding) |
| A rogue switch is connected to the I/O Block | BPDU Guard disables the port |
| A 3rd device is added to the I/O Block (max=2+1) | Port Security blocks the extra MAC |
| The switch reboots | Configuration persists (saved to NVRAM) |
| The tool runs twice | Nothing changes (commands are idempotent) |

## Troubleshooting

### Cannot connect to the switch

```bash
# Test connectivity
ping 192.168.1.1

# Test SSH
ssh admin@192.168.1.1
```

### A legitimate device has no connectivity

On the switch, verify:

```
show ip source binding
show ip verify source
show port-security interface Gi1/0/1
show mac address-table interface Gi1/0/1
```

Ensure the device MAC/IP matches what is configured in your topology.

## License

This project is licensed under the **Apache License 2.0** - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This software is provided "as is", without warranty of any kind, express or implied.
**Use at your own risk.** The author is not responsible for any damage, data loss,
network disruption, or security incidents resulting from the use of this tool.

Always test configurations in a lab environment before deploying to production networks.

## Trademark Notice

**Cisco**, **Cisco IOS**, **Cisco IOS-XE**, and all related product names, logos, and
trademarks are the property of **Cisco Systems, Inc.** This project is **not** affiliated
with, endorsed by, sponsored by, or in any way officially connected to Cisco Systems, Inc.

All product and company names mentioned herein are for identification purposes only and are
the property of their respective owners.
