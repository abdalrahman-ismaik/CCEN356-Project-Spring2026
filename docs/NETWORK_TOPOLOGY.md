# Network Topology

The final CCEN 356 lab used a small enterprise-like topology with a client LAN, a server LAN, and a point-to-point WAN link between two routers.

![Network topology](assets/network-topology.jpeg)

## Roles

| Device | Role |
|---|---|
| R1 | Client-side Cisco 2901 router. Hosts the ACL and QoS policy used for web traffic classification and prioritization. |
| R2 | Server-side Cisco 2901 router. Provides the server LAN gateway and the return route to the client LAN. |
| SW1 | Layer 2 switch connecting PC1, PC2, and R1's client-side interface. |
| PC1 | Client workstation used for connectivity tests, SSH automation, and/or HTTP/HTTPS requests. |
| PC2 | Client workstation used for benchmark traffic and Scapy capture in the final experiment. |
| Server PC | Hosts the Flask HTTP service, Flask HTTPS service, and optionally the dashboard. |

## IP Addressing

The addresses below are lab-specific defaults. Change them in your router configuration and environment variables if your lab uses different subnets.

| Device | Interface | IP Address | Mask | Gateway |
|---|---|---:|---:|---:|
| R1 | Gi0/0 | 10.1.5.21 | 255.255.255.252 | N/A |
| R1 | Gi0/1 | 192.165.10.37 | 255.255.255.0 | N/A |
| R2 | Gi0/0 | 10.1.5.22 | 255.255.255.252 | N/A |
| R2 | Gi0/1 | 192.165.20.37 | 255.255.255.0 | N/A |
| PC1 | NIC | 192.165.10.92 | 255.255.255.0 | 192.165.10.37 |
| PC2 | NIC | 192.165.10.79 | 255.255.255.0 | 192.165.10.37 |
| Server PC | NIC | 192.165.20.79 | 255.255.255.0 | 192.165.20.37 |

## Static Routing

R1 needs a route to the server LAN through R2:

```text
ip route 192.165.20.0 255.255.255.0 10.1.5.22
```

R2 needs a route back to the client LAN through R1:

```text
ip route 192.165.10.0 255.255.255.0 10.1.5.21
```

Without these routes, local gateway pings may work while end-to-end client-to-server traffic fails.

## ACL Design

The lab used named extended ACLs to permit and classify web traffic:

```text
ip access-list extended HTTP_HTTPS_ONLY
 permit tcp any any eq www
 permit tcp any any eq 443
 permit tcp any eq www any established
 permit tcp any eq 443 any established
 permit icmp any any

ip access-list extended HTTPS_ONLY
 permit tcp any any eq 443
 permit tcp any eq 443 any

ip access-list extended HTTP_ONLY
 permit tcp any any eq www
 permit tcp any eq www any
```

The sanitized R1 example applies `HTTP_HTTPS_ONLY` to the WAN-facing interface and uses `HTTPS_ONLY` and `HTTP_ONLY` as classification anchors for QoS.

## QoS Design

The R1 QoS policy uses Cisco MQC:

```text
class-map match-any CM_HTTPS
 match access-group name HTTPS_ONLY

class-map match-any CM_HTTP
 match access-group name HTTP_ONLY

policy-map WEB_QOS
 class CM_HTTPS
  priority percent 30
 class CM_HTTP
  bandwidth percent 10
 class class-default
  fair-queue

interface GigabitEthernet0/0
 service-policy output WEB_QOS
```

This policy gives HTTPS a priority class and gives HTTP a smaller bandwidth guarantee. The exact percentages can be changed for other labs.

## Switch

The switch operated as a basic Layer 2 device in the final topology. No VLAN segmentation was required. If you add SPAN/mirroring for packet capture, document the source and destination ports clearly and avoid mirroring unauthorized traffic.

## Configuration Files

Sanitized configuration examples are stored in:

- `configs/R1_config.txt`
- `configs/R2_config.txt`

These files are examples, not direct production backups. Local router secrets must be configured on the devices and must not be committed.
