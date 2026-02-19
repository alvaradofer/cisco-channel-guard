#!/usr/bin/env python3
"""
Cisco Channel Guard - Web Interface
Self-contained web application for Cisco switch port security management.

Usage:
    pip install -r requirements.txt
    python3 app.py
    Then open http://localhost:5050 in your browser.
"""

import os
import re
import shutil
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
)

import yaml

from switch_manager import SwitchManager
from ios_commands import generate_commands, generate_verify_commands, generate_summary

# ── Configuration ────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
TOPOLOGIES_DIR = BASE_DIR / "topologies"
NETWORK_FILE = TOPOLOGIES_DIR / "network.yml"
NETWORK_EXAMPLE = BASE_DIR / "network.example.yml"

TOPOLOGIES_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB upload limit

# Singleton switch connection
switch = SwitchManager()


# ── Helpers ──────────────────────────────────────────────────

def load_topology():
    """Load the active topology from network.yml."""
    path = NETWORK_FILE if NETWORK_FILE.exists() else NETWORK_EXAMPLE
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def save_topology(data):
    """Save topology to the active network.yml."""
    with open(NETWORK_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def validate_ip(ip):
    """Validate IPv4 address format."""
    pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
    if not re.match(pattern, ip):
        return False
    return all(0 <= int(octet) <= 255 for octet in ip.split("."))


def validate_mac(mac):
    """Validate Cisco MAC format (xxxx.xxxx.xxxx)."""
    pattern = r"^[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}$"
    return bool(re.match(pattern, mac))


def normalize_mac(mac):
    """Normalize various MAC formats to Cisco format (xxxx.xxxx.xxxx)."""
    raw = re.sub(r"[.:\-]", "", mac.strip().lower())
    if len(raw) != 12 or not re.match(r"^[0-9a-f]{12}$", raw):
        return mac
    return f"{raw[0:4]}.{raw[4:8]}.{raw[8:12]}"


def validate_topology_data(data):
    """Validate and normalize topology data. Returns list of errors."""
    errors = []
    channels = data.get("channels", [])

    for i, ch in enumerate(channels):
        label = f"Channel {i + 1}"
        if not ch.get("port"):
            errors.append(f"{label}: Port is required")
        if not ch.get("vlan"):
            errors.append(f"{label}: VLAN is required")

        io = ch.get("io_block", {})
        if io.get("ip") and not validate_ip(io["ip"]):
            errors.append(f"{label}: I/O Block IP '{io['ip']}' is invalid")
        if io.get("mac"):
            io["mac"] = normalize_mac(io["mac"])
            if not validate_mac(io["mac"]):
                errors.append(f"{label}: I/O Block MAC '{io['mac']}' is invalid")

        for j, dev in enumerate(ch.get("devices", [])):
            dev_label = f"{label}, Device {j + 1}"
            if dev.get("ip") and not validate_ip(dev["ip"]):
                errors.append(f"{dev_label}: IP '{dev['ip']}' is invalid")
            if dev.get("mac"):
                dev["mac"] = normalize_mac(dev["mac"])
                if not validate_mac(dev["mac"]):
                    errors.append(f"{dev_label}: MAC '{dev['mac']}' is invalid")

    # Ensure VLANs are integers
    for ch in channels:
        if ch.get("vlan"):
            ch["vlan"] = int(ch["vlan"])

    return errors


def sanitize_filename(name):
    """Sanitize a topology filename."""
    name = re.sub(r"[^a-zA-Z0-9_\-]", "", name)
    if not name:
        name = "untitled"
    return name


# ── Page Route ───────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the single-page application."""
    return render_template("index.html")


# ── Connection API ───────────────────────────────────────────

@app.route("/api/connect", methods=["POST"])
def api_connect():
    """Connect to a Cisco switch via SSH."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    host = data.get("host", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    enable_password = data.get("enable_password", "")

    if not host or not username or not password:
        return jsonify({"success": False, "error": "Host, username, and password are required"}), 400

    if not validate_ip(host):
        return jsonify({"success": False, "error": f"Invalid IP address: {host}"}), 400

    try:
        info = switch.connect(host, username, password, enable_password or None)
        return jsonify({"success": True, **info})
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    """Disconnect from the current switch."""
    switch.disconnect()
    return jsonify({"success": True})


@app.route("/api/status", methods=["GET"])
def api_status():
    """Get current connection status."""
    return jsonify(switch.get_status())


# ── Topology API ─────────────────────────────────────────────

@app.route("/api/topology", methods=["GET"])
def api_get_topology():
    """Get the active topology."""
    topology = load_topology()
    if topology is None:
        return jsonify({"error": "No topology configuration found"}), 404
    stats = generate_summary(topology)
    return jsonify({"topology": topology, "stats": stats})


@app.route("/api/topology", methods=["POST"])
def api_save_topology():
    """Save the active topology."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    errors = validate_topology_data(data)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    save_topology(data)
    return jsonify({"success": True, "message": "Topology saved"})


@app.route("/api/topology/export", methods=["GET"])
def api_export_topology():
    """Download the active topology as a YAML file."""
    topology = load_topology()
    if topology is None:
        return jsonify({"error": "No topology to export"}), 404

    # Write to a temp file and send
    export_path = TOPOLOGIES_DIR / "_export.yml"
    with open(export_path, "w") as f:
        yaml.dump(topology, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return send_file(
        export_path,
        as_attachment=True,
        download_name="channel-guard-topology.yml",
        mimetype="application/x-yaml",
    )


@app.route("/api/topology/import", methods=["POST"])
def api_import_topology():
    """Import a topology from an uploaded YAML file."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    try:
        content = file.read().decode("utf-8")
        data = yaml.safe_load(content)
    except Exception as e:
        return jsonify({"error": f"Invalid YAML file: {e}"}), 400

    if not isinstance(data, dict) or "channels" not in data:
        return jsonify({"error": "Invalid topology format: missing 'channels' key"}), 400

    errors = validate_topology_data(data)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    save_topology(data)
    stats = generate_summary(data)
    return jsonify({"success": True, "topology": data, "stats": stats})


@app.route("/api/topology/list", methods=["GET"])
def api_list_topologies():
    """List all saved topology files."""
    files = []
    for f in sorted(TOPOLOGIES_DIR.glob("*.yml")):
        if f.name.startswith("_"):
            continue
        try:
            with open(f) as fh:
                topo = yaml.safe_load(fh)
            channels = len(topo.get("channels", [])) if topo else 0
        except Exception:
            channels = 0

        files.append({
            "name": f.stem,
            "filename": f.name,
            "channels": channels,
            "size": f.stat().st_size,
            "modified": f.stat().st_mtime,
        })
    return jsonify({"files": files})


@app.route("/api/topology/save-as", methods=["POST"])
def api_save_topology_as():
    """Save current topology under a new name."""
    data = request.get_json()
    name = sanitize_filename(data.get("name", ""))

    topology = load_topology()
    if topology is None:
        return jsonify({"error": "No active topology to save"}), 404

    target = TOPOLOGIES_DIR / f"{name}.yml"
    with open(target, "w") as f:
        yaml.dump(topology, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return jsonify({"success": True, "message": f"Topology saved as '{name}'"})


@app.route("/api/topology/load", methods=["POST"])
def api_load_topology():
    """Load a named topology as the active one."""
    data = request.get_json()
    name = sanitize_filename(data.get("name", ""))
    source = TOPOLOGIES_DIR / f"{name}.yml"

    if not source.exists():
        return jsonify({"error": f"Topology '{name}' not found"}), 404

    with open(source) as f:
        topology = yaml.safe_load(f)

    save_topology(topology)
    stats = generate_summary(topology)
    return jsonify({"success": True, "topology": topology, "stats": stats})


@app.route("/api/topology/delete", methods=["POST"])
def api_delete_topology():
    """Delete a saved topology file."""
    data = request.get_json()
    name = sanitize_filename(data.get("name", ""))
    target = TOPOLOGIES_DIR / f"{name}.yml"

    if not target.exists():
        return jsonify({"error": f"Topology '{name}' not found"}), 404

    # Don't allow deleting the active topology file
    if target.name == "network.yml":
        return jsonify({"error": "Cannot delete the active topology"}), 400

    target.unlink()
    return jsonify({"success": True, "message": f"Topology '{name}' deleted"})


# ── Deploy & Verify API ─────────────────────────────────────

@app.route("/api/preview", methods=["GET"])
def api_preview():
    """Preview the IOS commands that will be deployed."""
    topology = load_topology()
    if topology is None:
        return jsonify({"error": "No topology configured"}), 404

    commands = generate_commands(topology)
    summary = generate_summary(topology)
    return jsonify({"commands": commands, "summary": summary})


@app.route("/api/deploy", methods=["POST"])
def api_deploy():
    """Deploy the configuration to the connected switch."""
    if not switch.is_connected():
        return jsonify({"success": False, "error": "Not connected to any switch. Connect first."}), 400

    topology = load_topology()
    if topology is None:
        return jsonify({"success": False, "error": "No topology configured. Save a topology first."}), 400

    body = request.get_json() or {}
    save_after = body.get("save_config", True)

    commands = generate_commands(topology)

    try:
        output = switch.send_config(commands)
        save_output = ""
        if save_after:
            save_output = switch.save_config()

        return jsonify({
            "success": True,
            "output": output,
            "save_output": save_output,
            "commands_sent": len(commands),
        })
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/verify", methods=["POST"])
def api_verify():
    """Run verification commands on the connected switch."""
    if not switch.is_connected():
        return jsonify({"success": False, "error": "Not connected to any switch. Connect first."}), 400

    topology = load_topology()
    if topology is None:
        return jsonify({"success": False, "error": "No topology configured."}), 400

    verify_cmds = generate_verify_commands(topology)
    results = []

    try:
        for cmd in verify_cmds:
            output = switch.send_command(cmd)
            results.append({"command": cmd, "output": output})

        return jsonify({"success": True, "results": results})
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e), "results": results}), 500


# ── Main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("+" + "=" * 56 + "+")
    print("|  Cisco Channel Guard - Web Interface                  |")
    print("|  Open http://localhost:5050 in your browser            |")
    print("+" + "=" * 56 + "+")
    print()

    app.run(host="127.0.0.1", port=5050, debug=True)
