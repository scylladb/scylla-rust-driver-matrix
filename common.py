import logging
import re
import subprocess
from collections import defaultdict
from pathlib import Path

# CCM_CLUSTER_IP_PREFIX = "127.0.1"
# CCM_CLUSTER_NODES = 3


def run_command_in_shell(driver_repo_path: str, cmd: str, environment: dict = None):
    logging.debug("Execute the cmd '%s'", cmd)
    with subprocess.Popen(cmd, shell=True, executable="/bin/bash", env=environment,
                          cwd=Path(driver_repo_path), stderr=subprocess.PIPE) as proc:
        stderr = proc.communicate()
        status_code = proc.returncode
    assert status_code == 0, stderr


def get_nodes_ip_from_ccm():
    lines = subprocess.check_output('ccm status -v | egrep "node|binary"', shell=True).decode().splitlines()
    # 'ccm status' output example:
    # node1: UP
    #        binary=('127.0.1.1', 9042)
    # node2: UP
    #        binary=('127.0.1.2', 9042)
    # node3: UP
    #        binary=('127.0.1.3', 9042)
    nodes_ip = defaultdict(str)
    node_name = None
    for line in lines:
        stripped_line = re.split(": |=", line.strip())
        if "node" in line:
            if stripped_line[1] != "UP":
                raise ValueError(f"Node '{stripped_line[0]}' is in status '{stripped_line[1]}'. Expected 'UP'")

            node_name = stripped_line[0]
        else:
            if not node_name:
                raise ValueError(f"Failed analyze ccm output: {lines}. Not found node for line '{line}'")

            nodes_ip[node_name] = stripped_line[1].split("'")[1]
            node_name = None

    return nodes_ip


def scylla_uri_per_node(nodes_ips):
    uri_per_node = []
    for node, ip in nodes_ips.items():
        node_index = node.replace("node", "").replace("1", "")
        uri_per_node.append(f"SCYLLA_URI{node_index}={ip}:9042")
        # uri_per_node = "SCYLLA_URI=127.0.1.1:9042 " + " ".join([f"SCYLLA_URI{i+1}=127.0.1.{i+1}:9042" for i in range(1, nodes)])
    return " ".join(uri_per_node)
