# Frey Network Config Management - Setup Guide
## AWX + NetBox + Ansible + Jinja2 Integration

**Purpose**: Centralized configuration management for network devices using NetBox as source of truth and AWX for execution. Part of the Frey project initiative.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Repository Setup](#repository-setup)
4. [Configuration Files](#configuration-files)
5. [Templates](#templates)
6. [Playbooks](#playbooks)
7. [AWX Configuration](#awx-configuration)
8. [NetBox Integration](#netbox-integration)
9. [Testing & Validation](#testing--validation)
10. [Workflow](#workflow)

---

## Architecture Overview

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│   NetBox    │────────▶│     AWX     │────────▶│   Arista    │
│ Source of   │         │  Execution  │         │   Devices   │
│   Truth     │         │   Engine    │         │   (cEOS)    │
└─────────────┘         └─────────────┘         └─────────────┘
      │                       │                        │
      │                       │                        │
      │                 ┌─────▼─────┐                 │
      └────────────────▶│    Git    │◀────────────────┘
                        │Repository │
                        └───────────┘
```

**Components**:
- **NetBox**: Single source of truth (devices, interfaces, IPs, VLANs, config context)
  - **Critical**: All device-specific data lives here, NOT in Git
- **AWX**: Job execution, scheduling, credentials management, inventory sync
  - Pulls inventory dynamically from NetBox
  - The static inventory file in Git is ONLY for local testing
- **Git**: Version control for templates, playbooks, and organizational defaults
  - Contains HOW to configure devices (templates)
  - Contains WHEN/HOW to execute (playbooks)
  - Contains organizational standards (default NTP, banners, etc.)
  - Does NOT contain device-specific data (that's in NetBox)
- **Jinja2**: Configuration templating engine
- **Ansible**: Automation framework with arista.eos collection
- **Containerlab**: Testing environment with Arista cEOS containers

**Key Architectural Principle**: 
- NetBox = WHAT to configure (the data)
- Git = HOW to configure (the templates and logic)
- AWX = WHEN to configure (execution and orchestration)

### Quick Reference: What Goes Where

| Data Type | Store In | Example |
|-----------|----------|---------|
| Device hostnames, IPs | NetBox | spine01, 10.0.0.1 |
| Interface configs | NetBox config context | Ethernet1, description, IP |
| VLANs | NetBox config context | VLAN 10, name: DATA |
| BGP neighbors | NetBox config context | Peer IPs, ASNs |
| Site-specific NTP/DNS | NetBox config context | DC1 NTP servers |
| Device-specific syslog | NetBox config context | Per-device syslog targets |
| Organizational metadata | Git group_vars/all.yml (optional) | Project name, contact email |
| Banner logic | Git templates/ | Role-based banner conditionals |
| Config templates | Git templates/ | How to render EOS config |
| Automation playbooks | Git playbooks/ | Backup, generate, deploy |
| Ansible connection | Git group_vars/platforms_eos.yml | ansible_network_os: eos |
| Policy by role (rare) | Git group_vars/device_roles_*.yml | Border routers must use TACACS |
| Passwords/secrets | AWX credentials | Device passwords, tokens |
| Local test inventory | Git inventory/hosts.yml | Only for testing without AWX |

---

## Prerequisites

### Required Software
- Python 3.8+
- Ansible 2.15+
- Git
- AWX/Ansible Tower (with NetBox dynamic inventory already configured)
- Containerlab (for testing only)
- Arista cEOS image (for testing only)

### Required Access
- NetBox instance with populated Arista devices
- AWX instance with admin access
- Git repository (GitHub, GitLab, etc.)
- Network access to Arista devices

### Ansible Collections
```bash
ansible-galaxy collection install arista.eos
ansible-galaxy collection install netbox.netbox
```

---

## Repository Setup

### Step 1: Initialize Directory Structure

```bash
# Create project directory
mkdir frey-netcfg-mgmt && cd frey-netcfg-mgmt
git init

# Create directory tree
mkdir -p playbooks
mkdir -p templates
mkdir -p configs/backup
mkdir -p configs/generated
mkdir -p group_vars
mkdir -p host_vars
mkdir -p inventory
mkdir -p containerlab
mkdir -p docs

# Create essential files
touch README.md
touch .gitignore
touch ansible.cfg
touch requirements.txt

# Create required group_vars file
touch group_vars/platforms_eos.yml

# Optional: Create group_vars/all.yml if you need organizational metadata
# or are in a migration period. For pure NetBox implementations, omit this file.
# touch group_vars/all.yml

# Note: Only create device_roles_*.yml files if you have
# genuine organizational policy differences by role
```

### Step 2: Directory Structure Overview

```
frey-netcfg-mgmt/
├── README.md                          # Main documentation
├── .gitignore                         # Git ignore rules
├── ansible.cfg                        # Ansible configuration
├── requirements.txt                   # Python dependencies
│
├── playbooks/                         # Ansible playbooks
│   ├── backup_configs.yml             # Backup device configs
│   ├── generate_configs.yml           # Generate from templates
│   └── deploy_configs.yml             # Deploy to devices
│
├── templates/                         # Jinja2 templates
│   ├── arista_base.j2                 # Base configuration
│   ├── arista_interfaces.j2           # Interface configs
│   ├── arista_vlans.j2                # VLAN configs
│   ├── arista_vxlan.j2                # VXLAN/VTEP configs
│   ├── arista_bgp.j2                  # BGP and EVPN configs
│   └── arista_full_config.j2          # Complete config
│
├── configs/
│   ├── backup/                        # Configuration backups
│   └── generated/                     # Generated configs
│
├── group_vars/                        # Group variables
│   └── platforms_eos.yml              # EOS platform connection params
│   # all.yml is optional - can be omitted if all data in NetBox
│   # device_roles_*.yml only if needed for policy differences
│
├── host_vars/                         # Host-specific variables (rarely needed)
│
├── inventory/
│   └── hosts.yml                      # Local testing inventory
│
├── containerlab/
│   └── frey-lab.clab.yml            # Lab topology
│
└── docs/
    ├── AWX_SETUP.md                   # AWX configuration guide
    └── netbox_config_context.md       # NetBox data structure
```

---

## Configuration Files

### .gitignore

```gitignore
# Ansible
*.retry
.vault_pass

# Python
__pycache__/
*.py[cod]
venv/
.venv/

# Configs - Backup live configs but not sensitive data
configs/backup/*.cfg
*.log

# Environment
.env
*.secret

# IDE
.vscode/
.idea/
```

### requirements.txt

```txt
ansible
pynetbox
jinja2
netaddr
```

### ansible.cfg

```ini
[defaults]
# AWX will override inventory setting
inventory = inventory/hosts.yml
host_key_checking = False
retry_files_enabled = False
gathering = explicit
command_warnings = False
callback_whitelist = profile_tasks, timer
collections_paths = ./collections:~/.ansible/collections:/usr/share/ansible/collections

[inventory]
enable_plugins = yaml, ini

[privilege_escalation]
become = False
```

### inventory/hosts.yml

**IMPORTANT**: This inventory is ONLY for local testing without AWX. AWX completely ignores this file and uses NetBox dynamic inventory instead.

```yaml
---
# ============================================
# LOCAL TESTING INVENTORY ONLY
# This file is NOT used by AWX
# AWX gets all inventory from NetBox
# ============================================
all:
  children:
    arista_eos:
      hosts:
        spine01:
          ansible_host: 172.20.20.2
        spine02:
          ansible_host: 172.20.20.3
        leaf01:
          ansible_host: 172.20.20.4
        leaf02:
          ansible_host: 172.20.20.5
      vars:
        ansible_network_os: eos
        ansible_connection: network_cli
        ansible_user: admin
        ansible_password: admin
        ansible_become: yes
        ansible_become_method: enable
```

---

## Group Variables

**CRITICAL UNDERSTANDING**: If NetBox is your true source of truth, group_vars should contain **ONLY Ansible connection parameters**. All configuration data belongs in NetBox.

**Data Ownership Principle**:
- Git repo (group_vars): Ansible connection parameters ONLY
- NetBox config context: ALL device and network configuration data
- AWX credentials: Passwords, secrets, API tokens

### Recommended Setup: Single File

For a pure NetBox-as-source-of-truth implementation, you only need ONE group_vars file:

**group_vars/platforms_eos.yml** - Ansible connection parameters

The `group_vars/all.yml` file is **optional** and can be omitted entirely if all data is in NetBox.

### group_vars/all.yml (Optional - Can Be Empty or Omitted)

**Two approaches for handling this file:**

#### Approach 1: Omit the file entirely (Recommended)
Simply don't create `group_vars/all.yml`. All data comes from NetBox.

#### Approach 2: Create empty file with documentation only
```yaml
---
# ============================================
# NetBox is the Source of Truth
# ============================================
# All network configuration data should be defined in NetBox config context:
#   - DNS servers (per site or device)
#   - NTP servers (per site or device)
#   - Syslog servers (per site or device)
#   - SNMP settings (per site or device)
#   - Timezone (per site or device)
#   - VLANs, interfaces, BGP, etc.
#
# This file intentionally left empty.
# If you find yourself adding data here, ask: "Should this be in NetBox?"
#
# The ONLY exception might be:
#   - Organizational metadata (project_name, contact_email, etc.)
#   - Values that are truly universal and never change
# ============================================

# Example of acceptable metadata (optional)
# project_name: "Frey Network Config Management"
# network_team_email: "netops@example.com"
```

#### Approach 3: Fail-safe defaults (Not Recommended for Production)
Only use this during initial implementation or migration:

```yaml
---
# ============================================
# TEMPORARY DEFAULTS DURING MIGRATION
# Remove these once NetBox is fully populated
# ============================================

# These are fail-safe defaults ONLY
# Better approach: Fail loudly if data missing from NetBox
dns_servers: "{{ netbox_config_context.dns_servers | default([]) }}"
ntp_servers: "{{ netbox_config_context.ntp_servers | default([]) }}"
syslog_servers: "{{ netbox_config_context.syslog_servers | default([]) }}"

# WARNING: Having defaults here can hide missing data in NetBox
# Consider using assertions in playbooks instead to ensure NetBox data exists
```

### group_vars/platforms_eos.yml

These provide **Ansible connection parameters** for the Arista EOS platform.

```yaml
---
# ============================================
# ANSIBLE CONNECTION PARAMETERS
# Arista EOS platform settings
# ============================================

# How Ansible connects to EOS devices
ansible_network_os: eos
ansible_connection: network_cli
ansible_become: yes
ansible_become_method: enable

# Connection timeouts (optional)
ansible_command_timeout: 30
ansible_connect_timeout: 30
```

### When to Create Role-Specific group_vars (Optional)

**Only create `group_vars/device_roles_<role>.yml` files if you have genuine organizational POLICY requirements** that differ by role. 

#### Valid Reasons:
- **Security Policy**: "All border routers must use TACACS+ authentication"
- **Compliance**: "PCI-compliant devices require specific banner text per regulation"
- **Logging Policy**: "All spine switches must log at debugging level"
- **Monitoring**: "Core devices send to different syslog server than access"

#### Invalid Reasons (Use NetBox Instead):
- Different VLANs per role → NetBox config context
- Different interfaces per role → NetBox config context
- Different BGP ASNs per role → NetBox config context
- Banner text variations → Handle in template with conditionals

#### Example: group_vars/device_roles_border.yml (Only If Needed)

```yaml
---
# ============================================
# POLICY REQUIREMENT: Border routers have
# different authentication per security policy
# ============================================

# Border routers must use TACACS per security policy
aaa_authentication: tacacs
tacacs_servers:
  - 10.0.0.150
  - 10.0.0.151

# Border routers require enhanced logging per compliance
logging_level: debugging

# PCI compliance requires specific banner
banner_motd: |
  *****************************************
  * BORDER ROUTER - PCI COMPLIANT ZONE
  * Unauthorized access is prohibited
  * All activity is logged and audited
  * Security Policy XYZ-123 applies
  *****************************************
```

### Handling Banner Customization in Templates (Recommended)

Instead of creating separate group_vars files just for banner text, handle it in your template:

**In templates/arista_base.j2:**
```jinja
!
! Banner
banner motd
{% if 'device_roles_border' in group_names %}
*** BORDER ROUTER - PCI COMPLIANT ZONE - Unauthorized access prohibited ***
{% elif 'device_roles_spine' in group_names %}
*** SPINE SWITCH - Unauthorized access prohibited ***
{% elif 'device_roles_leaf' in group_names %}
*** LEAF SWITCH - Unauthorized access prohibited ***
{% else %}
{{ banner_motd }}
{% endif %}
EOF
!
```

This approach:
- Keeps simple variations in one place (the template)
- Reduces file proliferation
- Makes customization logic visible
- Reserves group_vars for real policy differences

---

## Templates

### templates/arista_base.j2

```jinja
!
! Hostname
hostname {{ inventory_hostname }}
!
! DNS Configuration
{% if netbox_config_context.dns_servers is defined %}
{% for dns in netbox_config_context.dns_servers %}
ip name-server vrf default {{ dns }}
{% endfor %}
{% endif %}
!
! NTP Configuration
{% if netbox_config_context.ntp_servers is defined %}
{% for ntp in netbox_config_context.ntp_servers %}
ntp server {{ ntp }}
{% endfor %}
{% endif %}
!
! Timezone
clock timezone {{ netbox_config_context.timezone | default('UTC') }}
!
! Banner - Customized by device role
banner motd
{% if 'device_roles_border' in group_names %}
*****************************************
* BORDER ROUTER - PCI COMPLIANT ZONE
* Unauthorized access is prohibited
* All activity is logged and audited
*****************************************
{% elif 'device_roles_spine' in group_names %}
*****************************************
* SPINE SWITCH - Unauthorized access prohibited
* All activity is logged and monitored
*****************************************
{% elif 'device_roles_leaf' in group_names %}
*****************************************
* LEAF SWITCH - Unauthorized access prohibited
* All activity is logged and monitored
*****************************************
{% else %}
*****************************************
* Unauthorized access is prohibited
* All activity is logged and monitored
*****************************************
{% endif %}
EOF
!
! SNMP Configuration
{% if netbox_config_context.snmp_community is defined %}
snmp-server community {{ netbox_config_context.snmp_community }} ro
{% endif %}
{% if netbox_config_context.snmp_location is defined %}
snmp-server location {{ netbox_config_context.snmp_location }}
{% endif %}
!
! Logging
{% if netbox_config_context.syslog_servers is defined %}
{% for syslog in netbox_config_context.syslog_servers %}
logging host {{ syslog }}
{% endfor %}
{% endif %}
logging buffered 10000
!
! Users
username admin privilege 15 role network-admin secret admin
!
! AAA
aaa authorization exec default local
!
! Management Interface
interface Management1
   description Management Interface
   vrf default
   ip address {{ ansible_host }}/24
!
```

### templates/arista_vlans.j2

```jinja
!
! VLAN Configuration
{% if netbox_config_context.vlans is defined %}
{% for vlan in netbox_config_context.vlans %}
vlan {{ vlan.vid }}
   name {{ vlan.name }}
!
{% endfor %}
{% endif %}
```

### templates/arista_interfaces.j2

```jinja
!
! Physical Interfaces
{% if netbox_config_context.interfaces is defined %}
{% for interface in netbox_config_context.interfaces %}
interface {{ interface.name }}
   {% if interface.description is defined %}
   description {{ interface.description }}
   {% endif %}
   {% if interface.enabled == false %}
   shutdown
   {% else %}
   no shutdown
   {% endif %}
   {% if interface.mode == 'access' %}
   switchport mode access
   switchport access vlan {{ interface.vlan }}
   {% elif interface.mode == 'trunk' %}
   switchport mode trunk
   switchport trunk allowed vlan {{ interface.allowed_vlans | join(',') }}
   {% elif interface.mode == 'routed' %}
   no switchport
   ip address {{ interface.ip_address }}
   {% endif %}
!
{% endfor %}
{% endif %}
```

### templates/arista_full_config.j2

```jinja
! Device: {{ inventory_hostname }}
! Generated: {{ ansible_date_time.iso8601 }}
! Role: {{ device_role | default('unknown') }}
!
{{ lookup('template', 'arista_base.j2') }}
!
{{ lookup('template', 'arista_vlans.j2') }}
!
{{ lookup('template', 'arista_interfaces.j2') }}
!
{{ lookup('template', 'arista_vxlan.j2') }}
!
{{ lookup('template', 'arista_bgp.j2') }}
!
end
```

### templates/arista_vxlan.j2

```jinja
!
! VXLAN Configuration
{% if netbox_config_context.vxlan is defined %}
{% set vxlan = netbox_config_context.vxlan %}

! Loopback for VTEP
{% if vxlan.vtep_loopback is defined %}
interface Loopback{{ vxlan.vtep_loopback.id }}
   description VTEP Loopback
   ip address {{ vxlan.vtep_loopback.ip }}
!
{% endif %}

! VXLAN interface
interface Vxlan1
   description VXLAN Tunnel Interface
   {% if vxlan.vtep_source_interface is defined %}
   vxlan source-interface {{ vxlan.vtep_source_interface }}
   {% endif %}
   {% if vxlan.udp_port is defined %}
   vxlan udp-port {{ vxlan.udp_port }}
   {% endif %}
   {% if vxlan.vlan_vni_mappings is defined %}
   {% for mapping in vxlan.vlan_vni_mappings %}
   vxlan vlan {{ mapping.vlan }} vni {{ mapping.vni }}
   {% endfor %}
   {% endif %}
   {% if vxlan.flood_vtep_list is defined %}
   {% for vlan_flood in vxlan.flood_vtep_list %}
   vxlan flood vtep {{ vlan_flood.vteps | join(' ') }}
   {% endfor %}
   {% endif %}
!
{% endif %}
```

### templates/arista_bgp.j2

```jinja
!
! BGP Configuration
{% if netbox_config_context.bgp is defined %}
{% set bgp = netbox_config_context.bgp %}

! BGP Loopback (if different from VTEP)
{% if bgp.router_id_loopback is defined %}
interface Loopback{{ bgp.router_id_loopback.id }}
   description BGP Router ID
   ip address {{ bgp.router_id_loopback.ip }}
!
{% endif %}

! Prefix lists (must be defined before route-maps)
{% if bgp.prefix_lists is defined %}
{% for pl in bgp.prefix_lists %}
ip prefix-list {{ pl.name }}
   {% for entry in pl.entries %}
   seq {{ entry.sequence }} {{ entry.action }} {{ entry.prefix }}
   {% endfor %}
!
{% endfor %}
{% endif %}

! Route-map for BGP (defined after prefix-lists)
{% if bgp.route_maps is defined %}
{% for rm in bgp.route_maps %}
route-map {{ rm.name }} {{ rm.action }} {{ rm.sequence }}
   {% for statement in rm.statements %}
   {{ statement }}
   {% endfor %}
!
{% endfor %}
{% endif %}

! BGP Configuration
router bgp {{ bgp.asn }}
   router-id {{ bgp.router_id }}
   {% if bgp.maximum_paths is defined %}
   maximum-paths {{ bgp.maximum_paths }}
   {% endif %}
   {% if bgp.ecmp_paths is defined %}
   maximum-paths {{ bgp.ecmp_paths }} ecmp {{ bgp.ecmp_paths }}
   {% endif %}
   {% if bgp.distance is defined %}
   distance bgp {{ bgp.distance.external }} {{ bgp.distance.internal }} {{ bgp.distance.local }}
   {% endif %}
   !
   {% if bgp.peer_groups is defined %}
   {% for pg in bgp.peer_groups %}
   neighbor {{ pg.name }} peer group
   {% if pg.remote_as is defined %}
   neighbor {{ pg.name }} remote-as {{ pg.remote_as }}
   {% endif %}
   {% if pg.update_source is defined %}
   neighbor {{ pg.name }} update-source {{ pg.update_source }}
   {% endif %}
   {% if pg.ebgp_multihop is defined %}
   neighbor {{ pg.name }} ebgp-multihop {{ pg.ebgp_multihop }}
   {% endif %}
   {% if pg.send_community is defined %}
   neighbor {{ pg.name }} send-community{% if pg.send_community == 'extended' %} extended{% elif pg.send_community == 'both' %} extended{% endif %}
   {% endif %}
   {% if pg.next_hop_self is defined and pg.next_hop_self %}
   neighbor {{ pg.name }} next-hop-self
   {% endif %}
   !
   {% endfor %}
   {% endif %}
   !
   {% if bgp.neighbors is defined %}
   {% for neighbor in bgp.neighbors %}
   neighbor {{ neighbor.ip }} peer group {{ neighbor.peer_group | default('') }}
   {% if neighbor.remote_as is defined %}
   neighbor {{ neighbor.ip }} remote-as {{ neighbor.remote_as }}
   {% endif %}
   {% if neighbor.description is defined %}
   neighbor {{ neighbor.ip }} description {{ neighbor.description }}
   {% endif %}
   {% if neighbor.update_source is defined %}
   neighbor {{ neighbor.ip }} update-source {{ neighbor.update_source }}
   {% endif %}
   !
   {% endfor %}
   {% endif %}
   !
   {% if bgp.redistribute is defined %}
   {% for redist in bgp.redistribute %}
   redistribute {{ redist.protocol }}{% if redist.route_map is defined %} route-map {{ redist.route_map }}{% endif %}
   {% endfor %}
   !
   {% endif %}
   !
   {% if bgp.address_families is defined %}
   {% for af in bgp.address_families %}
   address-family {{ af.afi }} {{ af.safi }}
      {% if af.neighbors is defined %}
      {% for neighbor in af.neighbors %}
      neighbor {{ neighbor.ip }} activate
      {% if neighbor.route_map_in is defined %}
      neighbor {{ neighbor.ip }} route-map {{ neighbor.route_map_in }} in
      {% endif %}
      {% if neighbor.route_map_out is defined %}
      neighbor {{ neighbor.ip }} route-map {{ neighbor.route_map_out }} out
      {% endif %}
      {% if neighbor.send_community is defined %}
      neighbor {{ neighbor.ip }} send-community{% if neighbor.send_community == 'extended' %} extended{% endif %}
      {% endif %}
      {% endfor %}
      {% endif %}
      {% if af.networks is defined %}
      {% for network in af.networks %}
      network {{ network.prefix }}{% if network.route_map is defined %} route-map {{ network.route_map }}{% endif %}
      {% endfor %}
      {% endif %}
   {% endfor %}
   {% endif %}
   !
   {% if bgp.evpn is defined %}
   !
   ! EVPN Configuration
   address-family evpn
      {% if bgp.evpn.neighbors is defined %}
      {% for neighbor in bgp.evpn.neighbors %}
      neighbor {{ neighbor.ip }} activate
      {% if neighbor.encapsulation is defined %}
      neighbor {{ neighbor.ip }} encapsulation {{ neighbor.encapsulation }}
      {% endif %}
      {% endfor %}
      {% endif %}
      {% if bgp.evpn.route_reflector_client is defined and bgp.evpn.route_reflector_client %}
      neighbor {{ bgp.evpn.route_reflector_peer_group }} route-reflector-client
      {% endif %}
   {% endif %}
!
{% endif %}
```

---

## Playbooks

### playbooks/backup_configs.yml

```yaml
---
- name: Backup Arista EOS Configurations
  hosts: all  # AWX will limit to selected inventory group
  gather_facts: no
  
  vars:
    backup_dir: "{{ playbook_dir }}/../configs/backup"
  
  tasks:
    - name: Create backup directory
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
      delegate_to: localhost
      run_once: true

    - name: Backup running configuration
      arista.eos.eos_command:
        commands:
          - show running-config
      register: config_output

    - name: Save configuration to file
      ansible.builtin.copy:
        content: "{{ config_output.stdout[0] }}"
        dest: "{{ backup_dir }}/{{ inventory_hostname }}_{{ ansible_date_time.date }}.cfg"
      delegate_to: localhost

    - name: Display backup location
      ansible.builtin.debug:
        msg: "Configuration backed up to {{ backup_dir }}/{{ inventory_hostname }}_{{ ansible_date_time.date }}.cfg"
```

### playbooks/generate_configs.yml

```yaml
---
- name: Generate Configurations from NetBox Data
  hosts: all  # AWX limits to inventory selection
  gather_facts: yes
  
  vars:
    config_dir: "{{ playbook_dir }}/../configs/generated"
  
  tasks:
    - name: Create generated configs directory
      ansible.builtin.file:
        path: "{{ config_dir }}"
        state: directory
      delegate_to: localhost
      run_once: true

    - name: Verify required NetBox data is present
      ansible.builtin.assert:
        that:
          - inventory_hostname is defined
          - ansible_host is defined
          - netbox_config_context is defined
        fail_msg: |
          Missing required data from NetBox for {{ inventory_hostname }}.
          Ensure device has config context defined in NetBox.
        success_msg: "NetBox data validated for {{ inventory_hostname }}"

    - name: Validate required NetBox config context fields (optional but recommended)
      ansible.builtin.assert:
        that:
          - netbox_config_context.ntp_servers is defined
          - netbox_config_context.dns_servers is defined
          - netbox_config_context.syslog_servers is defined
        fail_msg: |
          Missing required fields in NetBox config context for {{ inventory_hostname }}.
          Required fields: ntp_servers, dns_servers, syslog_servers
          Please add these to the device or site config context in NetBox.
      when: validate_netbox_data | default(true)

    - name: Display device information from NetBox
      ansible.builtin.debug:
        msg: |
          Device: {{ inventory_hostname }}
          Role: {{ group_names | select('match', '^device_roles_') | map('regex_replace', '^device_roles_', '') | first | default('unknown') }}
          Site: {{ group_names | select('match', '^sites_') | map('regex_replace', '^sites_', '') | first | default('unknown') }}
          Platform: {{ group_names | select('match', '^platforms_') | map('regex_replace', '^platforms_', '') | first | default('unknown') }}

    - name: Set device role fact
      ansible.builtin.set_fact:
        device_role: "{{ group_names | select('match', '^device_roles_') | map('regex_replace', '^device_roles_', '') | first | default('unknown') }}"

    - name: Display what data is available from NetBox
      ansible.builtin.debug:
        msg: |
          NetBox config context data:
          - VLANs: {{ netbox_config_context.vlans | default([]) | length }} configured
          - Interfaces: {{ netbox_config_context.interfaces | default([]) | length }} configured
          - BGP: {{ 'configured' if netbox_config_context.bgp.asn is defined else 'not configured' }}
          - NTP: {{ netbox_config_context.ntp_servers | default([]) | length }} servers
          - DNS: {{ netbox_config_context.dns_servers | default([]) | length }} servers
          - Syslog: {{ netbox_config_context.syslog_servers | default([]) | length }} servers

    - name: Generate configuration from template
      ansible.builtin.template:
        src: "{{ playbook_dir }}/../templates/arista_full_config.j2"
        dest: "{{ config_dir }}/{{ inventory_hostname }}.cfg"
      delegate_to: localhost

    - name: Display generated config location
      ansible.builtin.debug:
        msg: "Configuration generated at {{ config_dir }}/{{ inventory_hostname }}.cfg"
```

### playbooks/deploy_configs.yml

```yaml
---
- name: Deploy Generated Configurations to Arista Devices
  hosts: all
  gather_facts: no
  
  vars:
    config_dir: "{{ playbook_dir }}/../configs/generated"
    
  tasks:
    - name: Check if generated config exists
      ansible.builtin.stat:
        path: "{{ config_dir }}/{{ inventory_hostname }}.cfg"
      delegate_to: localhost
      register: config_file

    - name: Fail if config doesn't exist
      ansible.builtin.fail:
        msg: "Configuration file not found. Run generate_configs.yml first."
      when: not config_file.stat.exists

    - name: Display configuration preview
      ansible.builtin.debug:
        msg: "Deploying configuration to {{ inventory_hostname }}"

    - name: Deploy configuration (config mode)
      arista.eos.eos_config:
        src: "{{ config_dir }}/{{ inventory_hostname }}.cfg"
        replace: config
        save_when: modified
      register: config_result
      # Add check mode support for AWX
      check_mode: "{{ ansible_check_mode | default(false) }}"

    - name: Display deployment results
      ansible.builtin.debug:
        msg: "Configuration {{ 'would be' if ansible_check_mode else 'was' }} deployed to {{ inventory_hostname }}"
      when: config_result.changed
```

---

## AWX Configuration

### Step 1: Create Project

1. Navigate to **Resources → Projects**
2. Click **Add**
3. Configure:
   - **Name**: `Frey Network Config Management`
   - **Organization**: Your organization
   - **Source Control Type**: `Git`
   - **Source Control URL**: `https://github.com/yourusername/frey-netcfg-mgmt.git`
   - **Source Control Branch/Tag/Commit**: `main`
   - **Options**: Update Revision on Launch
   - **Options**: Clean (removes any local modifications)
4. Click **Save**

### Step 2: Verify NetBox Inventory

Your existing NetBox inventory should have:
- **Name**: `NetBox - Arista Devices`
- **Organization**: Your organization
- **Source**: NetBox (already configured)
- **Update Options**: Set to sync on launch or schedule

**Verify Groups Created**:
Navigate to the inventory and check that these groups exist:
- `device_roles_spine`
- `device_roles_leaf`
- `platforms_eos`
- `sites_<your_site_name>`

### Step 3: Create Credentials

#### Machine Credential (for Arista Devices)
1. Navigate to **Resources → Credentials**
2. Click **Add**
3. Configure:
   - **Name**: `Arista Device Credentials`
   - **Organization**: Your organization
   - **Credential Type**: `Machine`
   - **Username**: `admin`
   - **Password**: `<your_password>`
   - **Privilege Escalation Method**: `enable`
   - **Privilege Escalation Password**: `<enable_password>` (if different)
4. Click **Save**

#### Source Control Credential (if private repository)
1. Click **Add**
2. Configure:
   - **Name**: `Git Repository Credentials`
   - **Credential Type**: `Source Control`
   - **Username**: Your GitHub username
   - **Password/Token**: Personal access token
3. Click **Save**

### Step 4: Create Job Templates

#### Template 1: Backup Configurations

1. Navigate to **Resources → Templates**
2. Click **Add → Add job template**
3. Configure:
   - **Name**: `Backup - Arista Configs`
   - **Job Type**: `Run`
   - **Inventory**: `NetBox - Arista Devices`
   - **Project**: `Frey Network Config Management`
   - **Playbook**: `playbooks/backup_configs.yml`
   - **Credentials**: 
     - Select `Arista Device Credentials`
   - **Options**: 
     - Enable Fact Storage
     - Enable Concurrent Jobs
   - **Job Slicing**: 1 (or higher for parallel execution)
4. Click **Save**

#### Template 2: Generate Configurations

1. Click **Add → Add job template**
2. Configure:
   - **Name**: `Generate - Arista Configs`
   - **Job Type**: `Run`
   - **Inventory**: `NetBox - Arista Devices`
   - **Project**: `Frey Network Config Management`
   - **Playbook**: `playbooks/generate_configs.yml`
   - **Credentials**: 
     - Select `Arista Device Credentials`
   - **Options**: 
     - Enable Fact Storage
     - Prompt on Launch (Limit)
3. Click **Save**

#### Template 3: Deploy Configurations

1. Click **Add → Add job template**
2. Configure:
   - **Name**: `Deploy - Arista Configs`
   - **Job Type**: `Run`
   - **Inventory**: `NetBox - Arista Devices`
   - **Project**: `Frey Network Config Management`
   - **Playbook**: `playbooks/deploy_configs.yml`
   - **Credentials**: 
     - Select `Arista Device Credentials`
   - **Options**: 
     - Enable Fact Storage
     - Prompt on Launch (Limit)
     - Prompt on Launch (Verbosity)
4. Click **Save**

### Step 5: Create Workflow Template (Optional but Recommended)

1. Navigate to **Resources → Templates**
2. Click **Add → Add workflow template**
3. Configure:
   - **Name**: `Arista Config Management - Full Workflow`
   - **Organization**: Your organization
   - **Inventory**: `NetBox - Arista Devices`
4. Click **Save**
5. Click **Visualizer** to build workflow:

```
START
  │
  ├─→ Sync Project (update Git repo)
  │
  ├─→ Sync Inventory (update from NetBox)
  │
  ├─→ Backup Configurations
  │   │
  │   └─→ Generate Configurations (on success)
  │       │
  │       └─→ [APPROVAL NODE] (manual approval)
  │           │
  │           └─→ Deploy Configurations (on approval)
  │               │
  │               └─→ SUCCESS
```

**Workflow Steps**:
1. Add **Project Sync** node (update from Git)
2. Add **Inventory Sync** node (update from NetBox)
3. Add **Backup** job template (on success)
4. Add **Generate** job template (on success)
5. Add **Approval** node (manual gate before deploy)
6. Add **Deploy** job template (on approval)

### Step 6: Create Schedules

#### Daily Backup Schedule
1. Navigate to your **Backup** job template
2. Click **Schedules** tab
3. Click **Add**
4. Configure:
   - **Name**: `Daily Backup - 2 AM`
   - **Start Date/Time**: Tomorrow at 02:00
   - **Repeat Frequency**: Daily
   - **Time Zone**: Your timezone
5. Click **Save**

#### Weekly Generation Schedule
1. Navigate to your **Generate** job template
2. Click **Schedules** tab
3. Click **Add**
4. Configure:
   - **Name**: `Weekly Config Generation`
   - **Start Date/Time**: Next Sunday at 01:00
   - **Repeat Frequency**: Weekly (Sunday)
5. Click **Save**

---

## NetBox Integration

### Data Ownership and Separation of Concerns

**Understanding where data lives is critical to this architecture:**

| Data Type | Owner | Why | Example |
|-----------|-------|-----|---------|
| Device facts | **NetBox** | Source of truth for network state | Hostnames, IPs, interfaces |
| Network design | **NetBox** | Network architecture decisions | VLANs, subnets, BGP ASNs |
| Device config data | **NetBox** | Device-specific configuration | Interface descriptions, BGP neighbors |
| Organizational standards | **Git repo** | Corporate policy/standards | Banner text, default NTP/DNS |
| Templates | **Git repo** | How to render configs | Jinja2 templates |
| Automation logic | **Git repo** | How to execute changes | Ansible playbooks |
| Connection params | **Git repo** | How Ansible connects | ansible_network_os, become_method |
| Secrets | **AWX** | Secure credential storage | Passwords, API tokens |

### What Belongs in NetBox Config Context

Config context is JSON data in NetBox that becomes variables in Ansible. Put **device-specific** or **site-specific** data here:

 **Use NetBox config context for:**
- VLANs and their assignments
- Interface configurations (IP addresses, descriptions, modes)
- Routing protocol configuration (BGP, OSPF)
- Device-specific NTP/DNS/Syslog servers
- ACLs and security policies
- QoS configurations
- Any data that varies per device or site

 **Don't use NetBox config context for:**
- Organizational banner text (use group_vars)
- Default NTP servers that apply to all devices (use group_vars as default)
- Ansible connection parameters (use group_vars)
- Template logic (that belongs in Jinja2 templates)

### What Belongs in Git Group Variables

Group variables should contain ONLY Ansible connection parameters and (optionally) organizational metadata:

**Use group_vars for:**
- Ansible connection parameters (platforms_eos.yml)
- Organizational metadata (project name, contact info) - optional
- Documented organizational policies that differ by role (rare)

**Do not use group_vars for:**
- Network configuration data (NTP, DNS, syslog, etc.) - use NetBox
- "Default" or "fallback" values - use NetBox site/group config context
- Device-specific data - use NetBox
- IP addresses - use NetBox
- Interface configurations - use NetBox
- VLANs - use NetBox
- Routing configuration - use NetBox
- Any data that could vary by device or site - use NetBox

**Key Principle**: If you find yourself adding configuration data to group_vars, stop and ask: "Why isn't this in NetBox?"

### Variable Precedence and Override Behavior

When the same variable is defined in multiple places, Ansible uses this precedence (highest to lowest):

1. **AWX Extra Vars** (Job template extra_vars) - Highest priority
2. **NetBox Config Context** (Device or group-specific) - **Primary source**
3. **Git host_vars/** (Device-specific overrides)
4. **Git group_vars/** (Group-level defaults) - **Fallback defaults**
5. **Playbook vars**
6. **Role defaults** - Lowest priority

**Best Practice**: Use NetBox config context for all real data, use group_vars only for defaults/standards.

### Understanding AWX's NetBox Groups

AWX automatically creates inventory groups based on NetBox attributes:

| NetBox Attribute | AWX Group Name | Example |
|------------------|----------------|---------|
| Device Role | `device_roles_<role>` | `device_roles_spine` |
| Site | `sites_<site>` | `sites_dc1` |
| Platform | `platforms_<platform>` | `platforms_eos` |
| Tenant | `tenants_<tenant>` | `tenants_customer1` |
| Region | `regions_<region>` | `regions_us_east` |

### NetBox Config Context Structure

Config context is JSON data stored in NetBox that becomes available as variables in AWX. **This is where your actual device configuration data lives.**

**Location in NetBox**: `Devices → Config Contexts`

### VXLAN/EVPN Architecture Overview

This configuration supports a standard spine-leaf VXLAN/EVPN fabric architecture:

**Architecture Components:**
- **Spine Switches**: BGP route reflectors for EVPN overlay, IP fabric underlay
- **Leaf Switches**: VTEPs (VXLAN Tunnel Endpoints), EVPN clients, host connectivity
- **Underlay**: eBGP for IP connectivity between spines and leafs
- **Overlay**: EVPN (MP-BGP) for MAC/IP advertisement and VXLAN tunnel establishment

**Key Design Elements:**
- **ASN Strategy**: Unique ASN per leaf, shared ASN for spines
- **Loopbacks**: Loopback0 for BGP router-id, Loopback1 for VTEP source
- **VNI Mapping**: Standard VLAN-to-VNI mapping (VLAN 10 → VNI 10010)
- **Route Reflectors**: Spines act as EVPN route reflectors
- **ECMP**: Multiple paths between leafs via different spines

**Traffic Flow:**
1. East-West (L2): VXLAN encapsulation between leaf VTEPs
2. North-South: Leaf switches provide gateway functionality
3. Control Plane: EVPN distributes MAC/IP information via BGP

**Design Considerations:**

**ASN Assignment Strategy:**
- Option 1: Unique ASN per leaf (simplifies policy, recommended for scale)
- Option 2: Shared ASN for all spines, shared ASN for all leafs
- This template supports both models

**Loopback Addressing:**
- Loopback0: BGP router-id and overlay peering
- Loopback1: VTEP source address (leaf switches only)
- Use /32 addresses from dedicated ranges

**VNI Numbering:**
- Standard: VLAN + offset (VLAN 10 → VNI 10010)
- L3 VNI: Separate range (VNI 50000+)
- Maintain consistent mapping across fabric

**BGP Configuration:**
- Underlay: eBGP for simplicity and fast convergence
- Overlay: iBGP or eBGP EVPN sessions
- Route Reflectors: Spines provide RR functionality
- ECMP: Enable maximum-paths for load balancing

**Scalability Guidelines:**
- Spine count: Typically 2-4 for redundancy
- Leaf count: Limited by spine port density and RR scale
- VNI count: Arista supports 1000s of VNIs per device
- MAC table: Monitor MAC address table utilization

#### Example Device Config Context (spine01)

**This is the SOURCE OF TRUTH for device-specific configuration:**

```json
{
  "vlans": [
    {
      "vid": 10,
      "name": "DATA"
    },
    {
      "vid": 20,
      "name": "VOICE"
    },
    {
      "vid": 30,
      "name": "GUEST"
    },
    {
      "vid": 99,
      "name": "MANAGEMENT"
    }
  ],
  "interfaces": [
    {
      "name": "Ethernet1",
      "description": "To leaf01 - Ethernet1",
      "enabled": true,
      "mode": "routed",
      "ip_address": "10.0.1.1/30"
    },
    {
      "name": "Ethernet2",
      "description": "To leaf02 - Ethernet1",
      "enabled": true,
      "mode": "routed",
      "ip_address": "10.0.1.5/30"
    },
    {
      "name": "Ethernet3",
      "description": "To spine02 - iBGP peer link",
      "enabled": true,
      "mode": "routed",
      "ip_address": "10.0.0.1/30"
    }
  ],
  "bgp": {
    "asn": 65000,
    "router_id": "10.255.255.1",
    "router_id_loopback": {
      "id": 0,
      "ip": "10.255.255.1/32"
    },
    "maximum_paths": 4,
    "ecmp_paths": 4,
    "peer_groups": [
      {
        "name": "SPINE_UNDERLAY",
        "remote_as": "external",
        "ebgp_multihop": 3,
        "send_community": "extended"
      },
      {
        "name": "EVPN_OVERLAY",
        "remote_as": "external",
        "update_source": "Loopback0",
        "ebgp_multihop": 3,
        "send_community": "extended"
      }
    ],
    "neighbors": [
      {
        "ip": "10.0.1.2",
        "peer_group": "SPINE_UNDERLAY",
        "description": "leaf01 underlay"
      },
      {
        "ip": "10.0.1.6",
        "peer_group": "SPINE_UNDERLAY",
        "description": "leaf02 underlay"
      },
      {
        "ip": "10.255.255.11",
        "peer_group": "EVPN_OVERLAY",
        "description": "leaf01 EVPN"
      },
      {
        "ip": "10.255.255.12",
        "peer_group": "EVPN_OVERLAY",
        "description": "leaf02 EVPN"
      }
    ],
    "address_families": [
      {
        "afi": "ipv4",
        "safi": "unicast",
        "neighbors": [
          {
            "ip": "10.0.1.2"
          },
          {
            "ip": "10.0.1.6"
          }
        ]
      }
    ],
    "evpn": {
      "route_reflector_client": false,
      "neighbors": [
        {
          "ip": "10.255.255.11",
          "encapsulation": "vxlan"
        },
        {
          "ip": "10.255.255.12",
          "encapsulation": "vxlan"
        }
      ]
    }
  },
  "ntp_servers": [
    "10.0.0.100",
    "10.0.0.101"
  ],
  "dns_servers": [
    "10.0.0.50",
    "10.0.0.51"
  ],
  "syslog_servers": [
    "10.0.0.200"
  ]
}
```

#### Example Device Config Context (leaf01 - VTEP)

**Leaf switches are VTEPs (VXLAN Tunnel Endpoints):**

```json
{
  "vlans": [
    {
      "vid": 10,
      "name": "DATA"
    },
    {
      "vid": 20,
      "name": "VOICE"
    },
    {
      "vid": 30,
      "name": "GUEST"
    }
  ],
  "interfaces": [
    {
      "name": "Ethernet1",
      "description": "To spine01 - Uplink",
      "enabled": true,
      "mode": "routed",
      "ip_address": "10.0.1.2/30"
    },
    {
      "name": "Ethernet2",
      "description": "To spine02 - Uplink",
      "enabled": true,
      "mode": "routed",
      "ip_address": "10.0.1.10/30"
    },
    {
      "name": "Ethernet3",
      "description": "Server Port - VLAN 10",
      "enabled": true,
      "mode": "access",
      "vlan": 10
    },
    {
      "name": "Ethernet4",
      "description": "Trunk Port",
      "enabled": true,
      "mode": "trunk",
      "allowed_vlans": [10, 20, 30]
    }
  ],
  "vxlan": {
    "vtep_loopback": {
      "id": 1,
      "ip": "10.255.255.11/32"
    },
    "vtep_source_interface": "Loopback1",
    "udp_port": 4789,
    "vlan_vni_mappings": [
      {
        "vlan": 10,
        "vni": 10010
      },
      {
        "vlan": 20,
        "vni": 10020
      },
      {
        "vlan": 30,
        "vni": 10030
      }
    ]
  },
  "bgp": {
    "asn": 65001,
    "router_id": "10.255.255.11",
    "router_id_loopback": {
      "id": 0,
      "ip": "10.255.255.11/32"
    },
    "maximum_paths": 4,
    "ecmp_paths": 4,
    "peer_groups": [
      {
        "name": "LEAF_UNDERLAY",
        "remote_as": "external",
        "send_community": "extended"
      },
      {
        "name": "EVPN_OVERLAY",
        "remote_as": "external",
        "update_source": "Loopback0",
        "ebgp_multihop": 3,
        "send_community": "extended"
      }
    ],
    "neighbors": [
      {
        "ip": "10.0.1.1",
        "peer_group": "LEAF_UNDERLAY",
        "description": "spine01 underlay"
      },
      {
        "ip": "10.0.1.9",
        "peer_group": "LEAF_UNDERLAY",
        "description": "spine02 underlay"
      },
      {
        "ip": "10.255.255.1",
        "peer_group": "EVPN_OVERLAY",
        "description": "spine01 EVPN"
      },
      {
        "ip": "10.255.255.2",
        "peer_group": "EVPN_OVERLAY",
        "description": "spine02 EVPN"
      }
    ],
    "address_families": [
      {
        "afi": "ipv4",
        "safi": "unicast",
        "neighbors": [
          {
            "ip": "10.0.1.1"
          },
          {
            "ip": "10.0.1.9"
          }
        ],
        "networks": [
          {
            "prefix": "10.255.255.11/32"
          }
        ]
      }
    ],
    "evpn": {
      "route_reflector_client": false,
      "neighbors": [
        {
          "ip": "10.255.255.1",
          "encapsulation": "vxlan"
        },
        {
          "ip": "10.255.255.2",
          "encapsulation": "vxlan"
        }
      ]
    }
  },
  "ntp_servers": [
    "10.0.0.100",
    "10.0.0.101"
  ],
  "dns_servers": [
    "10.0.0.50",
    "10.0.0.51"
  ],
  "syslog_servers": [
    "10.0.0.200"
  ]
}
```

#### Example Site/Group Config Context (All DC1 Devices)

Create a config context with:
- **Name**: `DC1 Site Standards`
- **Weight**: 500 (lower than device-specific contexts)
- **Sites**: DC1
- **Data**:

```json
{
  "ntp_servers": [
    "10.1.0.100",
    "10.1.0.101"
  ],
  "dns_servers": [
    "10.1.0.50",
    "10.1.0.51"
  ],
  "syslog_servers": [
    "10.1.0.200"
  ],
  "snmp_location": "Data Center 1 - Building A",
  "timezone": "America/Chicago"
}
```

#### Example Role Config Context (All Spines)

Create a config context with:
- **Name**: `Spine Device Standards`
- **Weight**: 1000 (higher weight = higher priority)
- **Device Roles**: spine
- **Data**:

```json
{
  "logging_buffer_size": 100000,
  "tacacs_servers": [
    "10.0.0.150",
    "10.0.0.151"
  ]
}
```

### How NetBox Config Context Works with Templates

When the playbook runs, NetBox config context is automatically available. **All configuration data should come from NetBox**:

```jinja
{# In your Jinja2 template #}

{# Access data directly from NetBox config context #}
{% if netbox_config_context.vlans is defined %}
{% for vlan in netbox_config_context.vlans %}
vlan {{ vlan.vid }}
   name {{ vlan.name }}
{% endfor %}
{% endif %}

{# BGP configuration from NetBox #}
{% if netbox_config_context.bgp is defined %}
router bgp {{ netbox_config_context.bgp.asn }}
   router-id {{ netbox_config_context.bgp.router_id }}
{% endif %}

{# NTP servers from NetBox #}
{% if netbox_config_context.ntp_servers is defined %}
{% for ntp in netbox_config_context.ntp_servers %}
ntp server {{ ntp }}
{% endfor %}
{% endif %}
```

### Handling Missing NetBox Data

**Two approaches:**

#### Approach 1: Fail Loudly (Recommended)
Use playbook assertions to ensure required data exists in NetBox:

```yaml
- name: Validate required NetBox data
  ansible.builtin.assert:
    that:
      - netbox_config_context.ntp_servers is defined
      - netbox_config_context.dns_servers is defined
    fail_msg: "Missing required config context in NetBox"
```

#### Approach 2: Gracefully Skip (For Optional Features)
Use conditionals in templates to only render if data exists:

```jinja
{# Only configure SNMP if defined in NetBox #}
{% if netbox_config_context.snmp_community is defined %}
snmp-server community {{ netbox_config_context.snmp_community }} ro
{% endif %}
```

**Don't use "fallback defaults" in group_vars** - this hides missing data in NetBox and defeats the purpose of having a source of truth.

### Required NetBox Data

For the templates to work, ensure NetBox has these minimum requirements:

**Devices**:
- Name (becomes `inventory_hostname`)
- Device Role (spine, leaf, etc.)
- Platform (set to "eos" or "Arista EOS")
- Site
- Primary IP address

**Interfaces** (if using interface templates):
- Name
- Type
- Enabled status
- Description (optional)
- Mode (access/trunk/routed)

**IP Addresses**:
- Assigned to interfaces
- Set as primary IP

**VLANs** (if needed):
- VLAN ID
- Name
- Site assignment

**For VXLAN/EVPN Deployments (in Config Context)**:

**Required for all devices:**
- `bgp.asn` - BGP AS number
- `bgp.router_id` - BGP router ID
- `bgp.router_id_loopback` - Loopback interface for router ID
- `bgp.neighbors` - BGP neighbor definitions
- `bgp.address_families` - IPv4 unicast address family configuration

**Required for spine switches:**
- `bgp.evpn.neighbors` - EVPN overlay peers
- `bgp.peer_groups` - Underlay and overlay peer group definitions

**Required for leaf switches (VTEPs):**
- `vxlan.vtep_loopback` - Loopback interface for VTEP
- `vxlan.vtep_source_interface` - Source interface for VXLAN tunnels
- `vxlan.vlan_vni_mappings` - VLAN to VNI mappings
- `bgp.evpn.neighbors` - EVPN overlay peers (spine route reflectors)
- `vlans` - VLANs that will be extended via VXLAN

**Optional but recommended:**
- `bgp.maximum_paths` - ECMP path count
- `bgp.route_maps` - Route filtering policies
- `bgp.redistribute` - Route redistribution configuration

### Common Mistakes: Data Duplication and Misplaced Data

**INCORRECT - Defining network config data in group_vars:**
```yaml
# DO NOT DO THIS in group_vars/all.yml
dns_servers:
  - 8.8.8.8
  - 8.8.4.4
ntp_servers:
  - 0.pool.ntp.org
  - 1.pool.ntp.org
spine01_vlans:
  - vid: 10
    name: DATA
```
Explanation: This is network configuration data, not Ansible parameters. It belongs in NetBox, not Git.

**CORRECT - Use NetBox config context:**
```json
// In NetBox site config context for DC1
{
  "dns_servers": ["10.1.0.50", "10.1.0.51"],
  "ntp_servers": ["10.1.0.100", "10.1.0.101"]
}

// In NetBox device config context for spine01
{
  "vlans": [{"vid": 10, "name": "DATA"}]
}
```

**INCORRECT - Using "fallback defaults" in group_vars:**
```yaml
# DO NOT DO THIS - hides missing NetBox data
ntp_servers: "{{ netbox_config_context.ntp_servers | default(['0.pool.ntp.org']) }}"
```
Explanation: If NTP servers are missing from NetBox, you want to know about it, not silently use a fallback.

**CORRECT - Fail if required data missing:**
```yaml
# In playbook: Validate NetBox has required data
- name: Ensure NTP servers defined in NetBox
  assert:
    that: netbox_config_context.ntp_servers is defined
    fail_msg: "NTP servers not defined in NetBox for {{ inventory_hostname }}"
```

**INCORRECT - Mixing NetBox and group_vars for same data:**
```yaml
# In group_vars
dns_servers:
  - 8.8.8.8

# In NetBox config context
{
  "dns_servers": ["10.0.0.50"]
}
```
Explanation: Creates confusion about which source is authoritative and leads to inconsistency.

**CORRECT - NetBox is the ONLY source:**
```json
// ALL DNS configuration in NetBox config context
{
  "dns_servers": ["10.0.0.50", "10.0.0.51"]
}
```
```yaml
# group_vars/all.yml - empty or omitted entirely
---
# This file intentionally left empty
# All configuration data in NetBox
```

### How to Structure Your Data

**Decision tree for where to put data:**

```
Is this network configuration data (IPs, VLANs, DNS, NTP, routing, etc.)?
├─ YES → Put in NetBox config context (device, site, or role-based)
│
└─ NO → Is this an Ansible connection parameter?
    ├─ YES → Put in Git group_vars/platforms_eos.yml
    │
    └─ NO → Is this how to render configs (template logic)?
        ├─ YES → Put in Git templates/
        │
        └─ NO → Is this automation logic (when/how to execute)?
            ├─ YES → Put in Git playbooks/
            │
            └─ NO → Is this a genuine organizational POLICY that differs by role?
                ├─ YES → Put in Git group_vars/device_roles_*.yml
                │
                └─ NO → Is this a secret/password?
                    ├─ YES → Put in AWX credentials
                    │
                    └─ NO → Is this just organizational metadata?
                        └─ YES → Optionally put in Git group_vars/all.yml
```

**Simplified Rule**: 
- Network data → NetBox
- Connection params → group_vars/platforms_eos.yml
- Everything else → Templates or playbooks
- Secrets → AWX

---

## Testing & Validation

### Local Testing (Without AWX)

#### Test 1: Verify Repository Structure

```bash
# Clone your repository
git clone https://github.com/yourusername/frey-netcfg-mgmt.git
cd frey-netcfg-mgmt

# Install dependencies
pip install -r requirements.txt
ansible-galaxy collection install arista.eos netbox.netbox

# Verify Ansible can see inventory
ansible-inventory --list -i inventory/hosts.yml

# Check playbook syntax
ansible-playbook playbooks/generate_configs.yml --syntax-check
```

#### Test 2: Generate Configs Locally

```bash
# Generate configs using static inventory
ansible-playbook playbooks/generate_configs.yml -i inventory/hosts.yml

# Check generated config
cat configs/generated/spine01.cfg
```

#### Test 3: Containerlab Testing

Create test environment:

```bash
cd containerlab

# Deploy lab (requires cEOS image)
sudo containerlab deploy -t frey-lab.clab.yml

# Verify containers are running
sudo containerlab inspect -t frey-lab.clab.yml

# Test connectivity
ssh admin@172.20.20.2  # Password: admin

# Destroy lab when done
sudo containerlab destroy -t frey-lab.clab.yml
```

### containerlab/frey-lab.clab.yml

```yaml
name: frey-netcfg-lab

topology:
  nodes:
    spine01:
      kind: ceos
      image: ceos:latest
      mgmt-ipv4: 172.20.20.2
      startup-config: ../configs/generated/spine01.cfg
      
    spine02:
      kind: ceos
      image: ceos:latest
      mgmt-ipv4: 172.20.20.3
      startup-config: ../configs/generated/spine02.cfg
      
    leaf01:
      kind: ceos
      image: ceos:latest
      mgmt-ipv4: 172.20.20.4
      startup-config: ../configs/generated/leaf01.cfg
      
    leaf02:
      kind: ceos
      image: ceos:latest
      mgmt-ipv4: 172.20.20.5
      startup-config: ../configs/generated/leaf02.cfg

  links:
    # Spine to Leaf connections (IP Fabric Underlay)
    - endpoints: ["spine01:eth1", "leaf01:eth1"]
    - endpoints: ["spine01:eth2", "leaf02:eth1"]
    - endpoints: ["spine02:eth1", "leaf01:eth2"]
    - endpoints: ["spine02:eth2", "leaf02:eth2"]
    
    # Optional: Spine to Spine link for redundancy
    # - endpoints: ["spine01:eth3", "spine02:eth3"]
```

**Note on VXLAN/EVPN Testing in Containerlab:**
- VXLAN encapsulation works in containerlab
- EVPN control plane functions normally
- Full fabric testing is possible with cEOS
- Verify overlay connectivity between leaf switches
- Test MAC/IP learning across the fabric

### AWX Testing

#### Test 1: Verify Inventory Sync

1. Navigate to **Resources → Inventories**
2. Select `NetBox - Arista Devices`
3. Click **Sync** button (or **Sources** tab → sync icon)
4. Wait for sync to complete
5. Click **Hosts** tab - verify devices appear
6. Click **Groups** tab - verify groups created

#### Test 2: Test Single Device

1. Navigate to **Resources → Templates**
2. Select `Generate - Arista Configs`
3. Click **Launch**
4. In **Limit** field, enter: `spine01`
5. Click **Next** → **Launch**
6. Monitor job output
7. Check AWX artifacts for generated config

#### Test 3: Dry Run (Check Mode)

1. Select `Deploy - Arista Configs`
2. Click **Launch**
3. In **Limit** field, enter: `spine01`
4. Enable **Check Mode**
5. Click **Next** → **Launch**
6. Review what WOULD change (no actual changes made)

#### Test 4: Full Workflow

1. Navigate to your workflow template
2. Click **Launch**
3. Monitor each step in visualizer
4. At approval node, review generated configs
5. Approve or deny deployment

### Validating VXLAN/EVPN Configuration

After deploying configurations to devices, validate the VXLAN/EVPN fabric:

#### Underlay Validation

```bash
# SSH to spine or leaf
ssh admin@spine01

# Verify BGP underlay sessions
show ip bgp summary

# Check IP connectivity to all loopbacks
ping 10.255.255.11 source 10.255.255.1

# Verify routing table
show ip route bgp
```

#### Overlay Validation

```bash
# Verify EVPN BGP sessions
show bgp evpn summary

# Check EVPN routes
show bgp evpn

# Verify learned MAC addresses
show bgp evpn route-type mac-ip

# Check VXLAN tunnel status (on leaf switches)
show vxlan vtep
show vxlan vni
show vxlan address-table

# Verify VXLAN interface
show interfaces vxlan1
```

#### End-to-End Validation

```bash
# On leaf switch - verify MAC learning
show mac address-table

# Verify VLAN to VNI mapping
show vxlan config-sanity

# Check EVPN control plane
show bgp evpn instance

# Verify VTEP flood lists
show vxlan flood vtep
```

**Common Issues to Check:**
- BGP sessions not established: Check IP connectivity, ASN configuration
- EVPN routes not received: Verify send-community extended is configured
- VXLAN tunnels down: Check VTEP loopback reachability
- MAC addresses not learned: Verify VLAN-VNI mappings are correct
- No traffic flow: Check flood VTEP lists or validate VXLAN encapsulation

---

## Workflow

### Standard Operating Procedure

#### 1. Update NetBox (Source of Truth)

```
Actions in NetBox:
├── Add new device
├── Modify interface configuration
├── Update IP addresses
├── Change VLAN assignments
├── Update config context (BGP, VLANs, etc.)
└── Document changes in device comments
```

#### 2. Sync AWX Inventory

**Option A - Automatic**: 
- Scheduled sync runs every hour
- Project sync on launch enabled

**Option B - Manual**:
1. Go to NetBox inventory in AWX
2. Click sync button
3. Wait for completion

#### 3. Generate Configurations

**Option A - Via Workflow**:
- Run full workflow template
- Automatically syncs, backs up, generates

**Option B - Individual Job**:
1. Run `Generate - Arista Configs` job
2. Use **Limit** for specific devices/groups:
   - Single device: `spine01`
   - Group: `device_roles_spine`
   - Multiple: `spine01,leaf01`
   - Pattern: `spine*`

#### 4. Review Generated Configs

1. Navigate to job output in AWX
2. Check artifacts directory (if configured)
3. Review configs in Git repository
4. Compare against backup if making changes

#### 5. Test in Lab (Optional)

```bash
# Update configs in repo
git pull

# Deploy to Containerlab
cd containerlab
sudo containerlab deploy -t frey-lab.clab.yml

# Test configuration
ssh admin@172.20.20.2
show running-config
```

#### 6. Backup Production

Run `Backup - Arista Configs` job template:
- Backs up current running configs
- Timestamped files in configs/backup/
- Safety net before changes

#### 7. Deploy to Production

**Using Check Mode First**:
1. Run `Deploy - Arista Configs`
2. Enable **Check Mode**
3. Review planned changes
4. If good, run again without check mode

**Using Workflow**:
- Approval node provides manual gate
- Review before approving
- Deploy happens automatically after approval

**Limiting Deployment**:
```
# Examples of limit patterns
spine01                    # Single device
device_roles_spine         # All spines
sites_dc1                  # All devices in DC1
spine01,spine02            # Multiple specific devices
leaf*                      # Pattern match
```

#### 8. Verify Deployment

1. Check AWX job output for errors
2. Verify device connectivity
3. Spot-check critical services
4. Review syslog for issues

---

## Troubleshooting

### AWX Issues

#### Problem: AWX doesn't see my Git changes

**Solution**:
```
1. Check project configuration
2. Ensure "Update Revision on Launch" is enabled
3. Manually sync project: Resources → Projects → Sync
4. Verify Git URL and credentials
5. Check AWX can reach Git repository
```

#### Problem: NetBox inventory not syncing

**Solution**:
```
1. Verify NetBox API is accessible from AWX
2. Check NetBox token has correct permissions
3. Review AWX inventory source configuration
4. Check AWX logs: /var/log/tower/
5. Test NetBox API manually:
   curl -H "Authorization: Token YOUR_TOKEN" \
        https://netbox.example.com/api/dcim/devices/
```

#### Problem: Variables not being applied

**Solution**:
```
1. Check if data is in NetBox config context (should be primary source)
2. Verify NetBox config context JSON is valid
3. Check AWX inventory sync completed successfully
4. Review variable precedence - NetBox overrides group_vars
5. Don't duplicate data in both NetBox and group_vars
6. Add debug task to see what variables AWX provides:
   - debug: var=netbox_config_context
7. Verify group_vars file names match AWX group names exactly
```

#### Problem: Data inconsistency between devices

**Solution**:
```
1. Verify you're not storing device data in group_vars (anti-pattern)
2. Check NetBox config context for each device
3. Ensure AWX inventory sync is recent
4. Review config context weights (higher = priority)
5. Don't hardcode device-specific values in templates
6. Use NetBox as single source of truth
```

### Template Issues

#### Problem: Jinja2 template errors

**Solution**:
```
1. Check template syntax locally:
   ansible-playbook playbooks/generate_configs.yml --syntax-check
2. Add debug tasks to print variable values
3. Verify variable exists and has correct structure
4. Use default filters: {{ var | default('fallback') }}
5. Check for undefined variables in template
```

#### Problem: Generated configs are incomplete

**Solution**:
```
1. Verify NetBox has all required data
2. Check NetBox config context structure
3. Review playbook output for warnings
4. Add conditionals in templates for optional data
5. Validate template logic with test data
```

### Connectivity Issues

#### Problem: Cannot connect to devices

**Solution**:
```
1. Verify AWX can reach device management IPs
2. Check firewall rules
3. Verify credentials in AWX
4. Test manual SSH from AWX container:
   ssh admin@device-ip
5. Check device has SSH enabled and accessible
```

#### Problem: Privilege escalation fails

**Solution**:
```
1. Verify enable password in credentials
2. Check privilege escalation method set to "enable"
3. Test enable manually on device
4. Review device AAA configuration
5. Check for enable secret vs enable password
```

### NetBox Data Issues

#### Problem: Devices not appearing in AWX inventory

**Solution**:
```
1. Verify device has primary IP in NetBox
2. Check device status is "Active"
3. Review inventory source filters in AWX
4. Ensure device has correct platform/role
5. Check NetBox API returns the device:
   GET /api/dcim/devices/?name=spine01
```

#### Problem: Config context not available in playbook

**Solution**:
```
1. Verify config context is assigned in NetBox
2. Check config context weight (higher = priority)
3. Ensure inventory sync completed after changes
4. Review netbox_config_context variable in job
5. Validate JSON syntax in NetBox config context
```

---

## Best Practices

### Data Management Principles

**Recommended practices:**
- NetBox is the ONLY source of truth for network data - No exceptions
- Keep group_vars/ minimal - ideally just platforms_eos.yml
- Fail loudly (with assertions) if required NetBox data is missing
- Use NetBox config context for ALL network configuration data
- Keep templates focused on rendering, not business logic
- Document required NetBox config context structure
- Validate NetBox data in playbooks before generating configs

**Practices to avoid:**
- Putting ANY network configuration data in group_vars (DNS, NTP, VLANs, etc.)
- Using "fallback defaults" - they hide missing NetBox data
- Duplicating data between NetBox and Git
- Overriding NetBox data with static values in Git
- Storing the same data in multiple places
- Using group_vars/all.yml for configuration data

### NetBox Management

**Recommended practices:**
- Use config contexts for device-specific data
- Set appropriate weights (1000 = default, higher = override)
- Document changes in device comments
- Use consistent naming conventions
- Assign devices to proper roles and sites
- Keep primary IPs updated

**Practices to avoid:**
- Storing passwords in config context
- Using invalid JSON in config context
- Leaving devices without primary IPs
- Creating circular dependencies in config context
- Duplicating data between Git and NetBox

### Template Development

**Recommended practices:**
- Use default filters for optional variables
- Add comments explaining complex logic
- Keep templates modular and reusable
- Test with minimal data first
- Version control all templates
- Use meaningful variable names

**Practices to avoid:**
- Hardcoding values that should be in NetBox
- Creating overly complex nested loops
- Assuming all variables exist
- Mixing business logic in templates
- Skipping input validation

### Git Repository Management

**Recommended practices:**
- Keep repository structure minimal
- Only create group_vars files when genuinely needed
- Handle simple role variations in templates, not separate group_vars
- Use meaningful commit messages
- Create branches for major changes
- Tag releases (v1.0.0, v1.1.0)
- Document changes in commits
- Review changes before committing
- Keep sensitive data out of repo

**Practices to avoid:**
- Creating device_roles_*.yml files "just in case"
- Committing passwords or tokens
- Pushing directly to main (use PRs)
- Making untested changes
- Ignoring .gitignore rules
- Storing backup configs in Git
- Proliferating group_vars files unnecessarily

### AWX Job Execution

**Recommended practices:**
- Use check mode before deploying
- Backup before making changes
- Use limits for testing
- Schedule regular backups
- Enable fact caching
- Use workflows for complex tasks

**Practices to avoid:**
- Deploying to all devices without testing
- Skipping backups
- Running jobs without reviewing output
- Disabling approval gates in production
- Ignoring failed job notifications

---

## Quick Reference

### Common AWX Limit Patterns

```bash
# Single device
spine01

# Device role group
device_roles_spine

# Site group
sites_dc1

# Platform group
platforms_eos

# Multiple devices
spine01,spine02,leaf01

# Pattern matching
spine*
leaf0[1-2]

# Boolean operators
device_roles_spine:&sites_dc1    # AND
device_roles_spine:!sites_dc2    # NOT

# Complex patterns
device_roles_spine:&sites_dc1:!spine01
```

### Useful Ansible Commands (Local)

```bash
# List inventory
ansible-inventory --list -i inventory/hosts.yml

# Test connectivity
ansible all -m ping -i inventory/hosts.yml

# Check syntax
ansible-playbook playbooks/generate_configs.yml --syntax-check

# Dry run
ansible-playbook playbooks/generate_configs.yml --check

# Run with limit
ansible-playbook playbooks/generate_configs.yml --limit spine01

# Verbose output
ansible-playbook playbooks/generate_configs.yml -vvv
```

### AWX API Examples

```bash
# Get job templates
curl -X GET https://awx.example.com/api/v2/job_templates/ \
  -H "Authorization: Bearer YOUR_TOKEN"

# Launch job
curl -X POST https://awx.example.com/api/v2/job_templates/123/launch/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"limit": "spine01"}'

# Get job status
curl -X GET https://awx.example.com/api/v2/jobs/456/ \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### VXLAN/EVPN Verification Commands

```bash
# Underlay verification
show ip bgp summary
show ip route bgp
show ip interface brief

# Overlay verification
show bgp evpn summary
show bgp evpn
show bgp evpn route-type mac-ip
show bgp evpn instance

# VXLAN verification (leaf switches)
show vxlan vtep
show vxlan vni
show vxlan address-table
show vxlan config-sanity
show interfaces vxlan1

# Control plane verification
show bgp evpn route-type imet
show mac address-table dynamic

# Troubleshooting
show logging | include BGP|EVPN|VXLAN
show running-config section bgp
show running-config section vxlan
```

---

## Next Steps

### Immediate Actions

1. Clone and set up repository structure
2. Configure AWX project pointing to your Git repo
3. Create job templates in AWX
4. Test with one device using limits
5. Verify generated configurations
6. Set up scheduled backups

### Short Term Enhancements

- Add more device roles (border, access, etc.)
- Expand VXLAN/EVPN capabilities:
  - L3 VNI support (symmetric IRB)
  - Anycast gateway configuration
  - Multi-tenancy with VRFs
  - EVPN multi-homing (ESI/LAG)
- Create templates for additional features:
  - MLAG configuration
  - ACLs and security policies
  - QoS policies
  - Multicast for BUM traffic
- Implement approval workflows
- Add Slack/Teams notifications
- Create dashboards for monitoring

### Long Term Goals

- Integrate with CI/CD pipeline
- Add automated testing (molecule, pytest)
- Implement drift detection
- Create compliance checking
- Build self-service portal
- Expand to multi-vendor support

---

## Additional Resources

### Documentation Links

- **Ansible EOS Collection**: https://docs.ansible.com/ansible/latest/collections/arista/eos/
- **NetBox Ansible Collection**: https://docs.ansible.com/ansible/latest/collections/netbox/netbox/
- **AWX Documentation**: https://ansible.readthedocs.io/projects/awx/
- **NetBox Documentation**: https://docs.netbox.dev/
- **Jinja2 Documentation**: https://jinja.palletsprojects.com/
- **Containerlab**: https://containerlab.dev/

### Example NetBox Queries

```python
# Get all spine devices
/api/dcim/devices/?role=spine

# Get device with interfaces
/api/dcim/devices/?name=spine01&include=interfaces

# Get config context for device
/api/dcim/devices/123/render-config/

# Get all VLANs
/api/ipam/vlans/
```

---

## Support and Contribution

### Getting Help

1. Check AWX job logs for errors
2. Review this documentation
3. Test locally with static inventory
4. Validate NetBox data structure
5. Check Ansible verbose output (-vvv)

### Contributing

1. Fork the repository
2. Create feature branch
3. Test changes thoroughly
4. Update documentation
5. Submit pull request

---

## Appendix: Complete File Listing

```
frey-netcfg-mgmt/
├── .gitignore
├── ansible.cfg
├── requirements.txt
├── README.md
│
├── playbooks/
│   ├── backup_configs.yml
│   ├── generate_configs.yml
│   └── deploy_configs.yml
│
├── templates/
│   ├── arista_base.j2
│   ├── arista_interfaces.j2
│   ├── arista_vlans.j2
│   ├── arista_vxlan.j2
│   ├── arista_bgp.j2
│   └── arista_full_config.j2
│
├── group_vars/
│   └── platforms_eos.yml
│   # all.yml is optional - omit for pure NetBox implementations
│   # Create device_roles_*.yml only if you have
│   # genuine organizational policy differences by role
│
├── host_vars/
│   # Rarely needed - use NetBox config context instead
│
├── configs/
│   ├── backup/
│   └── generated/
│
├── inventory/
│   └── hosts.yml
│
├── containerlab/
│   └── arista-lab.clab.yml
│
└── docs/
    ├── AWX_SETUP.md
    └── netbox_config_context.md
```

---

**Document Version**: 1.0  
**Last Updated**: 2025-10-16  
**Project**: Frey Network Config Management  
**Author**: Rob MacDonald

---

## Critical Reminders

### Architecture Summary

This system follows a strict **separation of concerns**:

1. **NetBox = Source of Truth**
   - All device-specific data (IPs, interfaces, VLANs, BGP, etc.)
   - Site and device-specific configurations
   - Network state and design decisions

2. **Git = Configuration Logic**
   - Jinja2 templates (HOW to render configs)
   - Ansible playbooks (HOW to execute automation)
   - Organizational defaults (fallback values only)
   - Standards and policies (banner text, etc.)

3. **AWX = Execution Engine**
   - Pulls inventory from NetBox (no static inventory)
   - Executes playbooks from Git
   - Manages credentials securely
   - Orchestrates workflows

**Golden Rule**: If it's data about a specific device, site, or network design, it belongs in NetBox—not in Git. Git contains only templates, logic, and Ansible connection parameters.

### The group_vars/ Folder

For pure NetBox implementations, you only need ONE file:
- `group_vars/platforms_eos.yml` - Contains ONLY Ansible connection parameters

You do NOT need:
- `group_vars/all.yml` - Can be omitted entirely; all config data in NetBox
- `group_vars/device_roles_*.yml` - Only create for genuine policy differences (rare)
- `host_vars/` - Never needed; use NetBox config context instead

If you find yourself adding configuration data to group_vars, STOP - that data belongs in NetBox config context.