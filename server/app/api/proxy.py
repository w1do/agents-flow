import ipaddress

from fastapi import Request


def _address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _networks(values: list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    mapped_range = ipaddress.IPv6Network("::ffff:0:0/96")
    networks = []
    for value in values:
        network = ipaddress.ip_network(value, strict=False)
        if isinstance(network, ipaddress.IPv6Network):
            if network.subnet_of(mapped_range):
                networks.append(network)
                networks.append(ipaddress.IPv4Network((
                    network.network_address.ipv4_mapped, network.prefixlen - 96)))
                continue
        networks.append(network)
    return networks


def _is_trusted(address, networks) -> bool:
    addresses = [address]
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        addresses.append(address.ipv4_mapped)
    return any(candidate.version == network.version and candidate in network
               for candidate in addresses for network in networks)


def client_ip(request: Request, trusted_proxy_ips: list[str]) -> str:
    peer = request.client.host if request.client else "unknown"
    try:
        raw_peer = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    peer_ip = _address(peer)
    networks = _networks(trusted_proxy_ips)
    if not _is_trusted(raw_peer, networks):
        return peer_ip.compressed
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return peer_ip.compressed
    try:
        chain = [ipaddress.ip_address(item.strip()) for item in forwarded.split(",")]
    except ValueError:
        return peer_ip.compressed
    for address in reversed([*chain, raw_peer]):
        if not _is_trusted(address, networks):
            return _address(str(address)).compressed
    return peer_ip.compressed


def request_is_secure(request: Request, trusted_proxy_ips: list[str]) -> bool:
    if request.url.scheme == "https":
        return True
    peer = request.client.host if request.client else "unknown"
    try:
        raw_peer = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if not _is_trusted(raw_peer, _networks(trusted_proxy_ips)):
        return False
    return request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower() == "https"
