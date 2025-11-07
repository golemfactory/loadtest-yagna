import socket
from testcontainers.core.container import DockerContainer, wait_for_logs

def launch_image(image_to_run: str):
    port = 8545
    golem_base = DockerContainer(image_to_run) \
        .with_bind_ports(port, port) \
        .with_command(["--dev",
                "--http",
                "--http.api",
                "eth,web3,net,debug,golembase,arkiv",
                "--verbosity",
                "5",
                "--http.addr",
                "0.0.0.0",
                "--http.port",
                str(port),
                "--http.corsdomain",
                "*",
                "--http.vhosts",
                "*",
                "--ws",
                "--ws.addr",
                "0.0.0.0",
                "--ws.port",
                str(port)])
    golem_base.start()
    wait_for_logs(golem_base, "HTTP server started")
    return golem_base

def extract_instance_index() -> int:
    """
    Extract the instance index from the hostname.
    
    The hostname follows the pattern: arkiv-loadtest-d2-4-worker-{region}-{timestamp}-{i}
    where {i} is the instance index at the end.
    
    Returns:
        int: The instance index extracted from the hostname
        
    Raises:
        ValueError: If the hostname doesn't match the expected pattern or index cannot be parsed
    """
    hostname = socket.gethostname()
    parts = hostname.split('-')
    
    if len(parts) < 2:
        raise ValueError(f"Hostname '{hostname}' doesn't match expected pattern: arkiv-loadtest-d2-4-worker-{{region}}-{{timestamp}}-{{i}}")
    
    try:
        # The index is the last part after the last '-'
        index = int(parts[-1])
        return index
    except ValueError:
        raise ValueError(f"Could not parse instance index from hostname '{hostname}'. Last part '{parts[-1]}' is not a valid integer")
