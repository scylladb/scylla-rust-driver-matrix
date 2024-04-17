import logging
import socket
from pathlib import Path
from typing import Dict, Tuple

from ccmlib import scylla_cluster as ccm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def acquire_ip_prefix() -> Tuple[socket.socket, str]:
    """gets unique ip prefix across whole machine,
    so it's possible to run tests in parallel.

    Returns tuple of lock (socket in that case) and ip prefix, where lock later needs to be released."""
    logger.info("Getting machine-unique ip prefix to support parallel tests...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    for index in range(1, 126):
        try:
            ip_prefix = f'127.0.{index}.'
            sock.bind((f'{ip_prefix}1', 48783))  # random port
            logger.info("Cluster ip prefix acquired: %s", ip_prefix)
            return sock, ip_prefix
        except OSError:
            continue
    raise ValueError(f"Couldn't acquire ip prefix - looks clusters are not cleared properly")


def release_ip_prefix_lock(sock: socket.socket) -> None:
    sock.close()


class TestCluster:
    """Responsible for configuring, starting and stopping cluster for tests"""

    def __init__(self, driver_directory: Path, version: str, nodes: int) -> None:
        self.cluster_directory = driver_directory / "ccm"
        self.cluster_directory.mkdir(parents=True, exist_ok=True)
        logger.info("Preparing test cluster binaries and configuration...")
        self._ip_prefix_lock, ip_prefix = acquire_ip_prefix()
        self._cluster: ccm.ScyllaCluster = ccm.ScyllaCluster(self.cluster_directory, 'test', cassandra_version=version)
        self._cluster.set_ipprefix(ip_prefix)
        self._cluster.populate(nodes)
        logger.info("Cluster prepared")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.remove()
        release_ip_prefix_lock(self._ip_prefix_lock)

    @property
    def ip_addresses(self):
        storage_interfaces = [node.network_interfaces['storage'][0] for node in list(self._cluster.nodes.values()) if node.is_live()]
        return ",".join(storage_interfaces)

    def nodes_addresses(self):
        cluster_nodes_ip = {}
        for node in list(self._cluster.nodes.values()):
            cluster_nodes_ip[node.name] = node.address()

        return cluster_nodes_ip

    def start(self) -> str:
        logger.info("Starting test cluster...")
        self._cluster.start(wait_for_binary_proto=True)
        nodes_count = len(self._cluster.nodes)
        nodes = [(node.is_running(), node.is_live(), node.address()) for node in list(self._cluster.nodes.values())]
        logger.info("test cluster started: %s", nodes)
        return f"-rf={nodes_count} -clusterSize={nodes_count} -cluster={self.ip_addresses}"

    def remove(self):
        logger.info("Removing test cluster...")
        self._cluster.remove()
        logger.info("test cluster removed")
