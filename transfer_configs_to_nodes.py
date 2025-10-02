import yaml
import os
import pprint
import tarfile
from netmiko import ConnectHandler
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import socket
from concurrent.futures import ThreadPoolExecutor


def get_server_ip():
    try:
        # Connect to an external server to determine the primary IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # Google's public DNS server
            ip_address = s.getsockname()[0]
        return ip_address
    except Exception as e:
        print(f"Error retrieving IP. Please manually hardcode the IP of the server into the script")
        return None


def start_http_server():
    server = HTTPServer(('0.0.0.0', 8000), SimpleHTTPRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down the server.")
        server.server_close()


def create_tarball(node_name):
    tar_path = f"{user_directory}/lab_configs/{node_name}.tar"
    with tarfile.open(tar_path, "w") as tar:
        node_config_path = f"{user_directory}/lab_configs/{node_name}"
        for filename in os.listdir(node_config_path):
            tar.add(os.path.join(node_config_path, filename), arcname=filename)
    return tar_path


def copy_files_to_node(node):
    if node['kind'] == 'cisco_csr1000v' or node['kind'] == 'linux':
        router = {
            'device_type': 'cisco_ios',
            'ip': node['mgmt-ipv4'],
            'username': 'admin',
            'password': 'admin'
            }

        net_connect = ConnectHandler(**router)
        for filename in os.listdir(f'{user_directory}/lab_configs/{node["name"]}'):
            net_connect.send_config_set(["ip http client source-interface GigabitEthernet1"])
            net_connect.send_command(f'copy http://{server_ip}:8000/{user_directory}/lab_configs/{node["name"]}/{filename} flash:{filename}',
                expect_string = 'Destination')
            output = net_connect.send_command(filename, expect_string = r'confirm\]|#')
            if 'confirm' in output:
                net_connect.send_command('', expect_string = node["name"])


    if node['kind'] == 'cisco_iol':
        router = {
            'device_type': 'cisco_ios',
            'ip': node['mgmt-ipv4'],
            'username': 'admin',
            'password': 'admin'
            }

        net_connect = ConnectHandler(**router)
        for filename in os.listdir(f'{user_directory}/lab_configs/{node["name"]}'):
            net_connect.send_command(f'copy http://{server_ip}:8000/{user_directory}/lab_configs/{node["name"]}/{filename} unix:{filename}',
                expect_string = 'Destination')
            output = net_connect.send_command(filename, expect_string = r'confirm\]|#')
            if 'confirm' in output:
                net_connect.send_command('', expect_string = node["name"])


    if node['kind'] == 'cisco_xrv':
        router = {
            'device_type': 'cisco_xr',
            'ip': node['mgmt-ipv4'],
            'username': 'cisco',
            'password': 'cisco',
            'read_timeout_override': 90
            }
    
        if user_directory in ['ovi-sr', 'russo-bgp-xr', 'bgp-mh-xr']:
            router = {
                'device_type': 'cisco_xr',
                'ip': node['mgmt-ipv4'],
                'username': 'clab',
                'password': 'clab@123',
                'read_timeout_override': 90
                }


        net_connect = ConnectHandler(**router)

        #tar all config files, and then extract them, because individual file copies take forever
        tar_path = create_tarball(node['name'])

        net_connect.send_command(f'copy http://{server_ip}:8000/{tar_path} bootflash:config_files.tar',
            expect_string = 'Destination')
        output = net_connect.send_command('config_files.tar', expect_string = r'confirm\]|#')
        if 'confirm' in output:
            net_connect.send_command('\n', expect_string=node["name"])
        net_connect.send_command_timing('run cd /bootflash: && tar xvf config_files.tar')
        os.remove(tar_path)

    if node['kind'] == 'cisco_xrd':
        router = {
            'device_type': 'cisco_xr',
            'ip': node['mgmt-ipv4'],
            'username': 'clab',
            'password': 'clab@123',
            'read_timeout_override': 90
            }

        net_connect = ConnectHandler(**router)
        for filename in os.listdir(f'{user_directory}/lab_configs/{node["name"]}'):
            net_connect.send_command(f'copy http://{server_ip}:8000/{user_directory}/lab_configs/{node["name"]}/{filename} disk0:{filename}',
                expect_string = 'Destination')
            output = net_connect.send_command(filename, expect_string = r'confirm\]|#')
            if 'confirm' in output:
                net_connect.send_command('\n', expect_string=node["name"])


server_ip = get_server_ip()
server_thread = threading.Thread(target=start_http_server, daemon=True)
server_thread.start()

user_directory = input('Enter the lab directory (ex. mvpn): ')
for filename in os.listdir(user_directory):
    if filename.endswith('clab.yml'):
        topology_file = os.path.join(user_directory, filename)

with open(topology_file, 'r') as file:
    clab_topology = yaml.safe_load(file)

clab_nodes = [{"name": key, **value} for key, value in clab_topology["topology"]["nodes"].items()]

with ThreadPoolExecutor(max_workers=5) as executor:
    executor.map(copy_files_to_node, clab_nodes)

