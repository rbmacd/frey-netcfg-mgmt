#!/usr/bin/env python3

###
# 
# Helper script to seed NetBox inventory from a containerlab YAML file
# 
# Part of the Frey project - https://github.com/rbmacd/frey#
# 
# This script helps users stand up a full NetDevOps environment from a simulated network
#  leveraging containerlab.  This script seeds a fresh install of NetBox from the lab's
#  yaml file, ensuring that a Frey instance starts with a proper source of truth.
#
###

import yaml
import pynetbox # type: ignore
import sys
import os
import logging
import argparse
import urllib3
import json
import re
from ipaddress import ip_interface
from pynetbox.core.query import RequestError # type: ignore
from urllib3.exceptions import InsecureRequestWarning

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('clab_netbox_sync.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Device type mapping for ContainerLab kinds
DEVICE_TYPE_MAP = {
    'ceos': 'Arista cEOS',
    'linux': 'Linux Host'
}

MANUFACTURER_MAP = {
    'ceos': 'Arista',
    'linux': 'Generic'
}

# Default VLANs for leaf switches
DEFAULT_VLANS = [
    {"vid": 10, "name": "DATA"},
    {"vid": 20, "name": "VOICE"},
    {"vid": 30, "name": "GUEST"}
]

# Base IP ranges for config generation
LOOPBACK_BASE = "10.255.255."  # Router IDs and VTEP IPs
SPINE_LOOPBACK_START = 1       # Spine01 = .1, Spine02 = .2
LEAF_LOOPBACK_START = 11       # Leaf01 = .11, Leaf02 = .12
BASE_ASN_SPINE = 65000         # Shared ASN for all spines
BASE_ASN_LEAF = 65001          # Starting ASN for leafs (increments per leaf)

def load_clab_yaml(filepath):
    """Load and parse the ContainerLab YAML file"""
    try:
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
            logger.info(f"Successfully loaded ContainerLab file: {filepath}")
            return data
    except FileNotFoundError:
        logger.error(f"File not found: {filepath}")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading file: {e}")
        raise

def determine_device_role(device_name):
    """Determine device role from hostname"""
    device_lower = device_name.lower()
    if device_lower.startswith('spine'):
        return 'spine'
    elif device_lower.startswith('leaf'):
        return 'leaf'
    elif device_lower.startswith('border'):
        return 'border'
    else:
        return 'unknown'

def extract_device_number(device_name):
    """Extract numeric suffix from device name (e.g., spine01 -> 1)"""
    match = re.search(r'(\d+)$', device_name)
    if match:
        return int(match.group(1))
    return 0

def generate_router_id(device_name, role):
    """Generate router ID based on device name and role"""
    device_num = extract_device_number(device_name)
    
    if role == 'spine':
        octet = SPINE_LOOPBACK_START + device_num - 1
    elif role == 'leaf':
        octet = LEAF_LOOPBACK_START + device_num - 1
    else:
        octet = 100 + device_num
    
    return f"{LOOPBACK_BASE}{octet}"

def generate_asn(device_name, role):
    """Generate BGP ASN based on device role"""
    if role == 'spine':
        return BASE_ASN_SPINE
    elif role == 'leaf':
        device_num = extract_device_number(device_name)
        return BASE_ASN_LEAF + device_num - 1
    else:
        return BASE_ASN_SPINE

def get_connected_devices(device_name, clab_data):
    """Get list of devices connected to this device from topology"""
    connected = []
    links = clab_data['topology'].get('links', [])
    
    for link in links:
        endpoints = link['endpoints']
        dev1_name, _ = endpoints[0].split(':')
        dev2_name, _ = endpoints[1].split(':')
        
        if dev1_name == device_name:
            connected.append(dev2_name)
        elif dev2_name == device_name:
            connected.append(dev1_name)
    
    return connected

def generate_spine_config_context(device_name, device_data, clab_data, all_devices):
    """Generate config context for spine switches"""
    router_id = generate_router_id(device_name, 'spine')
    asn = generate_asn(device_name, 'spine')
    
    # Get connected leaf switches
    connected_devices = get_connected_devices(device_name, clab_data)
    leaf_neighbors = [dev for dev in connected_devices if determine_device_role(dev) == 'leaf']
    
    # Build EVPN neighbor list
    evpn_neighbors = []
    for leaf in leaf_neighbors:
        leaf_router_id = generate_router_id(leaf, 'leaf')
        evpn_neighbors.append({
            "ip": leaf_router_id,
            "encapsulation": "vxlan"
        })
    
    config_context = {
        "bgp": {
            "asn": asn,
            "router_id": router_id,
            "router_id_loopback": {
                "id": 0,
                "ip": f"{router_id}/32"
            },
            "maximum_paths": 4,
            "ecmp_paths": 4,
            "peer_groups": [
                {
                    "name": "SPINE_UNDERLAY",
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
            "evpn": {
                "route_reflector_client": False,
                "neighbors": evpn_neighbors
            }
        },
        "ntp_servers": ["10.0.0.100", "10.0.0.101"],
        "dns_servers": ["10.0.0.50", "10.0.0.51"],
        "syslog_servers": ["10.0.0.200"]
    }
    
    return config_context

def generate_leaf_config_context(device_name, device_data, clab_data, all_devices):
    """Generate config context for leaf switches"""
    router_id = generate_router_id(device_name, 'leaf')
    asn = generate_asn(device_name, 'leaf')
    
    # Get connected spine switches
    connected_devices = get_connected_devices(device_name, clab_data)
    spine_neighbors = [dev for dev in connected_devices if determine_device_role(dev) == 'spine']
    
    # Build EVPN neighbor list
    evpn_neighbors = []
    for spine in spine_neighbors:
        spine_router_id = generate_router_id(spine, 'spine')
        evpn_neighbors.append({
            "ip": spine_router_id,
            "encapsulation": "vxlan"
        })
    
    # Generate VLAN-to-VNI mappings
    vlan_vni_mappings = []
    for vlan in DEFAULT_VLANS:
        vlan_vni_mappings.append({
            "vlan": vlan["vid"],
            "vni": 10000 + vlan["vid"]  # VLAN 10 -> VNI 10010
        })
    
    config_context = {
        "vlans": DEFAULT_VLANS,
        "vxlan": {
            "vtep_loopback": {
                "id": 1,
                "ip": f"{router_id}/32"
            },
            "vtep_source_interface": "Loopback1",
            "udp_port": 4789,
            "vlan_vni_mappings": vlan_vni_mappings
        },
        "bgp": {
            "asn": asn,
            "router_id": router_id,
            "router_id_loopback": {
                "id": 0,
                "ip": f"{router_id}/32"
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
            "evpn": {
                "route_reflector_client": False,
                "neighbors": evpn_neighbors
            }
        },
        "ntp_servers": ["10.0.0.100", "10.0.0.101"],
        "dns_servers": ["10.0.0.50", "10.0.0.51"],
        "syslog_servers": ["10.0.0.200"]
    }
    
    return config_context

def apply_config_context(nb, device, config_context, device_name):
    """Apply config context to a device in NetBox"""
    try:
        # NetBox stores config context as local_context_data on the device
        logger.info(f"Applying config context to {device_name}")
        device.local_context_data = config_context
        device.save()
        logger.info(f"Successfully applied config context to {device_name}")
    except RequestError as e:
        logger.error(f"NetBox API error applying config context to {device_name}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error applying config context to {device_name}: {e}")

def get_or_create_manufacturer(nb, name):
    """Get or create a manufacturer in NetBox"""
    try:
        manufacturer = nb.dcim.manufacturers.get(name=name)
        if not manufacturer:
            logger.info(f"Creating manufacturer: {name}")
            manufacturer = nb.dcim.manufacturers.create(name=name, slug=name.lower())
        else:
            logger.debug(f"Manufacturer already exists: {name}")
        return manufacturer
    except RequestError as e:
        logger.error(f"NetBox API error creating manufacturer {name}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error with manufacturer {name}: {e}")
        raise

def get_or_create_device_type(nb, kind, manufacturer_id):
    """Get or create a device type in NetBox"""
    try:
        device_type_name = DEVICE_TYPE_MAP.get(kind, kind)
        device_type = nb.dcim.device_types.get(model=device_type_name)
        
        if not device_type:
            logger.info(f"Creating device type: {device_type_name}")
            device_type = nb.dcim.device_types.create(
                manufacturer=manufacturer_id,
                model=device_type_name,
                slug=device_type_name.lower().replace(' ', '-')
            )
        else:
            logger.debug(f"Device type already exists: {device_type_name}")
        return device_type
    except RequestError as e:
        logger.error(f"NetBox API error creating device type {device_type_name}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error with device type {device_type_name}: {e}")
        raise

def get_or_create_site(nb, name):
    """Get or create a site in NetBox using the clab name"""
    try:
        site = nb.dcim.sites.get(name=name)
        if not site:
            logger.info(f"Creating site: {name}")
            site = nb.dcim.sites.create(
                name=name,
                slug=name.lower().replace(' ', '-')
            )
        else:
            logger.debug(f"Site already exists: {name}")
        return site
    except RequestError as e:
        logger.error(f"NetBox API error creating site {name}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error with site {name}: {e}")
        raise

def get_or_create_device_role(nb, role_name):
    """Get or create a device role"""
    try:
        role = nb.dcim.device_roles.get(name=role_name)
        if not role:
            logger.info(f"Creating device role: {role_name}")
            role = nb.dcim.device_roles.create(
                name=role_name,
                slug=role_name.lower().replace(' ', '-'),
                color='2196f3'  # Blue color
            )
        else:
            logger.debug(f"Device role already exists: {role_name}")
        return role
    except RequestError as e:
        logger.error(f"NetBox API error creating device role {role_name}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error with device role {role_name}: {e}")
        raise

def create_devices(nb, clab_data, site_id):
    """Create devices from ContainerLab topology"""
    devices = {}
    nodes = clab_data['topology']['nodes']
    
    # Extract management subnet prefix length from clab.yml
    mgmt_config = clab_data.get('mgmt', {})
    mgmt_subnet = mgmt_config.get('ipv4-subnet')
    
    if not mgmt_subnet:
        logger.error("No mgmt.ipv4-subnet found in ContainerLab YAML file")
        raise ValueError("Management subnet not defined in clab.yml")
    
    if '/' not in mgmt_subnet:
        logger.error(f"Management subnet '{mgmt_subnet}' does not contain a prefix length")
        raise ValueError("Management subnet must include prefix length (e.g., 192.168.121.0/24)")
    
    mgmt_prefix_len = mgmt_subnet.split('/')[-1]
    logger.info(f"Using management subnet: {mgmt_subnet} (prefix length: /{mgmt_prefix_len})")
    
    logger.info(f"Processing {len(nodes)} devices")
    
    for node_name, node_data in nodes.items():
        try:
            kind = node_data.get('kind', 'linux')
            mgmt_ip = node_data.get('mgmt-ipv4')
            
            # Determine device role from hostname
            device_role_name = determine_device_role(node_name)
            
            # Get or create manufacturer
            manufacturer_name = MANUFACTURER_MAP.get(kind, 'Generic')
            manufacturer = get_or_create_manufacturer(nb, manufacturer_name)
            
            # Get or create device type
            device_type = get_or_create_device_type(nb, kind, manufacturer.id)
            
            # Get or create device role based on hostname pattern
            if device_role_name in ['spine', 'leaf', 'border']:
                role = get_or_create_device_role(nb, device_role_name.capitalize())
            else:
                role = get_or_create_device_role(nb, 'Network Device' if kind == 'ceos' else 'Host')
            
            # Set platform for Arista devices
            platform = None
            if kind == 'ceos':
                platform = get_or_create_platform(nb, 'Arista EOS', manufacturer.id)
            
            # Check if device exists
            device = nb.dcim.devices.get(name=node_name)
            if not device:
                logger.info(f"Creating device: {node_name} (role: {device_role_name})")
                device_params = {
                    'name': node_name,
                    'device_type': device_type.id,
                    'role': role.id,
                    'site': site_id
                }
                if platform:
                    device_params['platform'] = platform.id
                    
                device = nb.dcim.devices.create(**device_params)
            else:
                logger.info(f"Device already exists: {node_name}")
            
            devices[node_name] = device
            
            # Create management IP if specified
            if mgmt_ip:
                create_management_ip(nb, device, mgmt_ip, mgmt_prefix_len)
                
        except Exception as e:
            logger.error(f"Error processing device {node_name}: {e}")
            continue
    
    logger.info(f"Successfully processed {len(devices)} devices")
    return devices

def get_or_create_platform(nb, platform_name, manufacturer_id):
    """Get or create a platform in NetBox"""
    try:
        platform = nb.dcim.platforms.get(name=platform_name)
        if not platform:
            logger.info(f"Creating platform: {platform_name}")
            platform = nb.dcim.platforms.create(
                name=platform_name,
                slug=platform_name.lower().replace(' ', '-'),
                manufacturer=manufacturer_id
            )
        else:
            logger.debug(f"Platform already exists: {platform_name}")
        return platform
    except RequestError as e:
        logger.error(f"NetBox API error creating platform {platform_name}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error with platform {platform_name}: {e}")
        raise

def create_management_ip(nb, device, mgmt_ip, prefix_len):
    """Create management IP address for a device"""
    try:
        # Add prefix length from the management subnet if not already included
        if '/' not in mgmt_ip:
            ip_addr = f"{mgmt_ip}/{prefix_len}"
        else:
            ip_addr = mgmt_ip
        
        # Validate the IP address format
        try:
            from ipaddress import ip_interface as validate_ip
            validate_ip(ip_addr)
        except ValueError as e:
            logger.error(f"Invalid IP address format {ip_addr}: {e}")
            return
        
        existing_ip = nb.ipam.ip_addresses.get(address=ip_addr)
        
        if not existing_ip:
            logger.info(f"Creating management IP: {ip_addr} for {device.name}")
            # NetBox requires assignment to an interface, not directly to device
            # Create or get a management interface first
            mgmt_interface = get_or_create_interface(nb, device, 'Management1')
            
            if not mgmt_interface:
                logger.error(f"Could not create management interface for {device.name}")
                return
            
            ip_obj = nb.ipam.ip_addresses.create(
                address=ip_addr,
                assigned_object_type='dcim.interface',
                assigned_object_id=mgmt_interface.id,
                description=f"Management IP for {device.name}"
            )
            
            # Set as primary IP for the device
            device.primary_ip4 = ip_obj.id
            device.save()
        else:
            logger.debug(f"IP already exists: {ip_addr}")
    except RequestError as e:
        logger.error(f"NetBox API error creating IP {ip_addr} for {device.name}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error creating IP for {device.name}: {e}")

def create_interfaces_and_links(nb, clab_data, devices):
    """Create interfaces and links from ContainerLab topology"""
    links = clab_data['topology'].get('links', [])
    
    logger.info(f"Processing {len(links)} links")
    successful_links = 0
    
    for link in links:
        try:
            endpoints = link['endpoints']
            
            # Parse endpoints (format: "device:interface")
            device1_name, intf1_name = endpoints[0].split(':')
            device2_name, intf2_name = endpoints[1].split(':')
            
            # Get devices
            device1 = devices.get(device1_name)
            device2 = devices.get(device2_name)
            
            if not device1 or not device2:
                logger.warning(f"Could not find devices for link {endpoints}")
                continue
            
            # Create interfaces
            intf1 = get_or_create_interface(nb, device1, intf1_name)
            intf2 = get_or_create_interface(nb, device2, intf2_name)
            
            # Create cable connection
            if intf1 and intf2:
                create_cable(nb, intf1, intf2)
                successful_links += 1
                
        except ValueError as e:
            logger.error(f"Error parsing link endpoints {link}: {e}")
            continue
        except Exception as e:
            logger.error(f"Error processing link {link}: {e}")
            continue
    
    logger.info(f"Successfully processed {successful_links}/{len(links)} links")

def get_or_create_interface(nb, device, intf_name):
    """Get or create an interface on a device"""
    try:
        interface = nb.dcim.interfaces.get(device_id=device.id, name=intf_name)
        
        if not interface:
            logger.info(f"Creating interface: {device.name}:{intf_name}")
            
            # Determine interface type based on name
            if intf_name.lower().startswith('mgmt') or intf_name.lower().startswith('management'):
                intf_type = '1000base-t'
            else:
                intf_type = '1000base-x-sfp'
            
            interface = nb.dcim.interfaces.create(
                device=device.id,
                name=intf_name,
                type=intf_type
            )
        else:
            logger.debug(f"Interface already exists: {device.name}:{intf_name}")
        
        return interface
    except RequestError as e:
        logger.error(f"NetBox API error creating interface {device.name}:{intf_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error creating interface {device.name}:{intf_name}: {e}")
        return None

def create_cable(nb, intf1, intf2):
    """Create a cable connection between two interfaces"""
    try:
        # Check if cable already exists
        if intf1.cable or intf2.cable:
            logger.debug(f"Cable already exists between {intf1.device.name}:{intf1.name} and {intf2.device.name}:{intf2.name}")
            return
        
        logger.info(f"Creating cable: {intf1.device.name}:{intf1.name} <-> {intf2.device.name}:{intf2.name}")
        
        cable = nb.dcim.cables.create(
            a_terminations=[{
                'object_type': 'dcim.interface',
                'object_id': intf1.id
            }],
            b_terminations=[{
                'object_type': 'dcim.interface',
                'object_id': intf2.id
            }]
        )
    except RequestError as e:
        logger.error(f"NetBox API error creating cable between {intf1.device.name}:{intf1.name} and {intf2.device.name}:{intf2.name}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error creating cable: {e}")

def generate_and_apply_config_contexts(nb, clab_data, devices):
    """Generate and apply config contexts to all devices"""
    logger.info("=" * 50)
    logger.info("Generating and applying config contexts...")
    logger.info("=" * 50)
    
    nodes = clab_data['topology']['nodes']
    
    for device_name, device_obj in devices.items():
        try:
            device_data = nodes.get(device_name, {})
            role = determine_device_role(device_name)
            
            # Only generate config for network devices (cEOS)
            if device_data.get('kind') != 'ceos':
                logger.debug(f"Skipping config context for non-network device: {device_name}")
                continue
            
            config_context = None
            
            if role == 'spine':
                config_context = generate_spine_config_context(
                    device_name, device_data, clab_data, devices
                )
            elif role == 'leaf':
                config_context = generate_leaf_config_context(
                    device_name, device_data, clab_data, devices
                )
            else:
                logger.warning(f"Unknown role '{role}' for device {device_name}, skipping config context")
                continue
            
            if config_context:
                apply_config_context(nb, device_obj, config_context, device_name)
                
        except Exception as e:
            logger.error(f"Error generating config context for {device_name}: {e}")
            continue
    
    logger.info("Config context generation complete")

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Synchronize ContainerLab topology to NetBox with config contexts',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables Required:
  NETBOX_URL        NetBox instance URL (e.g., https://netbox.example.com)
  NETBOX_APITOKEN   NetBox API token

Examples:
  %(prog)s clab.yml
  %(prog)s --no-ssl-verify clab.yml
  %(prog)s --skip-config-context clab.yml
        """
    )
    parser.add_argument('clab_file', help='Path to ContainerLab YAML file')
    parser.add_argument('--no-ssl-verify', action='store_true',
                        help='Disable SSL certificate verification (insecure)')
    parser.add_argument('--skip-config-context', action='store_true',
                        help='Skip generating and applying config contexts')
    
    args = parser.parse_args()
    
    # Get NetBox configuration from environment variables
    NETBOX_URL = os.environ.get('NETBOX_URL')
    NETBOX_APITOKEN = os.environ.get('NETBOX_APITOKEN')
    
    if not NETBOX_URL:
        logger.error("NETBOX_URL environment variable is not set")
        sys.exit(1)
    
    if not NETBOX_APITOKEN:
        logger.error("NETBOX_APITOKEN environment variable is not set")
        sys.exit(1)
    
    # Disable SSL warnings if requested
    if args.no_ssl_verify:
        logger.warning("SSL certificate verification is disabled - this is insecure!")
        urllib3.disable_warnings(InsecureRequestWarning)
    
    try:
        # Load ContainerLab YAML
        logger.info(f"Loading ContainerLab file: {args.clab_file}")
        clab_data = load_clab_yaml(args.clab_file)
        
        # Connect to NetBox
        logger.info(f"Connecting to NetBox: {NETBOX_URL}")
        try:
            nb = pynetbox.api(NETBOX_URL, token=NETBOX_APITOKEN)
            
            # Disable SSL verification if requested
            if args.no_ssl_verify:
                nb.http_session.verify = False
            
            # Test connection
            nb.dcim.sites.count()
            logger.info("Successfully connected to NetBox")
        except Exception as e:
            logger.error(f"Failed to connect to NetBox: {e}")
            sys.exit(1)
        
        # Create site from clab name
        clab_name = clab_data.get('name', 'containerlab')
        site = get_or_create_site(nb, clab_name)
        logger.info(f"Using site: {site.name}")
        
        # Create devices
        logger.info("=" * 50)
        logger.info("Creating devices...")
        logger.info("=" * 50)
        devices = create_devices(nb, clab_data, site.id)
        
        # Create interfaces and links
        logger.info("=" * 50)
        logger.info("Creating interfaces and links...")
        logger.info("=" * 50)
        create_interfaces_and_links(nb, clab_data, devices)
        
        # Generate and apply config contexts
        if not args.skip_config_context:
            generate_and_apply_config_contexts(nb, clab_data, devices)
        else:
            logger.info("Skipping config context generation (--skip-config-context flag set)")
        
        logger.info("=" * 50)
        logger.info("✓ Synchronization complete!")
        logger.info("=" * 50)
        
    except KeyboardInterrupt:
        logger.warning("Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error during synchronization: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()