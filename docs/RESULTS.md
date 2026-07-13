# Results

This summary is based on the final CCEN 356 project report and the curated project figures.

## HTTP vs HTTPS

Baseline measurements showed that HTTP generally had lower average latency than HTTPS. This matched the expected protocol behavior:

- HTTP sends application data without a TLS handshake.
- HTTPS adds TLS negotiation and encryption/decryption work.
- Both protocols achieved high success rates in the lab when routing and firewall rules were correct.

![HTTP vs HTTPS performance comparison](assets/performance-comparison.png)

The charted benchmark showed HTTP as faster on average in the baseline run, while HTTPS had higher tail latency due to TLS and connection setup costs. HTTPS remained the correct protocol for real deployments because it provides confidentiality, integrity, and server authentication.

## TLS Overhead

The observed HTTPS latency overhead came from:

- TLS handshake messages before encrypted application data is exchanged.
- Certificate validation and key exchange.
- Symmetric encryption/decryption for application records.
- Larger packet and connection setup patterns compared with plain HTTP.

This overhead is most visible in short-lived request tests. In long-lived sessions, connection reuse can reduce the relative cost.

## Packet Capture Observations

Scapy packet capture confirmed the visibility difference:

- HTTP traffic was identifiable on TCP/80 and could be inspected as plaintext.
- HTTPS traffic was identifiable on TCP/443, but application payloads were encrypted.
- Packet flows followed the expected path from client to switch, R1, R2, and server.

![Packet capture analysis](assets/traffic-analysis.png)

The packet analysis chart shows protocol share, packet-size behavior, top conversations, and capture timing.

## QoS Impact

The QoS experiment prioritized HTTPS traffic on R1. With QoS enabled, HTTPS traffic became more stable and, under the configured lab conditions, faster than HTTP. Without QoS, HTTPS generally remained slower because of TLS overhead.

The main lesson is that QoS cannot remove cryptographic overhead, but it can change queueing behavior and reduce latency variation for selected traffic classes.

## Dashboard Observations

The Flask dashboard provided a live view of:

- HTTP and HTTPS average latency
- TLS overhead delta
- Endpoint UP/DOWN status
- P95/P99 latency
- Reliability and failure counts
- QoS mode comparison
- Simple trend and risk indicators

![Live dashboard overview](assets/dashboard-overview.png)

The dashboard was useful during demos because it made latency changes visible without manually opening CSV files or chart outputs.

## Key Lessons Learned

- Static routes are essential in a two-router topology when no dynamic routing protocol is used.
- HTTP is easier to inspect but unsuitable for sensitive real-world traffic.
- HTTPS protects payloads but introduces measurable overhead in short request sequences.
- ACLs are useful both for traffic control and for classification in QoS policies.
- QoS effects should be verified with both router counters and endpoint measurements.
- Python automation with Netmiko, Scapy, Requests, Matplotlib, and Flask can turn manual lab checks into a repeatable observability workflow.
