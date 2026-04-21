Course Project #2
Course Code: CCEN 356
Course Title: Computer Networks
Project Title: Design, Implementation, and Analysis of HTTP/HTTPS Performance and
Visibility Using Cisco Devices and Python Automation
Project Overview:
This project aims develop an application layer focused on enhancing the performance
and visibility of HTTP and HTTPS protocols using Cisco 2901 routers and switches, along
with Python programming. Students will construct a network topology using Cisco
devices and desktop PCs, configure the necessary settings to monitor and analyze
HTTP/HTTPS traƯic, and develop Python scripts to automate data collection and
analysis, and visualization. This project will provide hands-on experience with both
networking and programming, illustrating the integration of diƯerent technologies to
enhance application performance. Additionally, Scapy will be employed to capture and
inspect packet flow.
Leaning Objectives:
1. Understanding the fundamentals of HTTP/HTTPS protocols and their role in web
communications.
2. Gain hands-on experience in configuring Cisco 2901 routers and switches for
enhanced network performance.
3. Develop Python scripts to automate network monitoring and traƯic analysis, and
that can interact with network devices and perform traƯic simulations.
4. Analyze HTTP/HTTPS traƯic using Scapy to identify latency issues and
performance bottlenecks.
5. Implement practical solutions to optimize network performance based on traƯic
analysis.
Project Requirements:
A. Network Topology
 2 Cisco 2901 Routers
 1 Cisco Switches
 Computers for running scripts and packet capture, and as Clients
 Configuration for multiple clients and web server to simulate web traƯic
B. Network Configuration Tasks
 Set up basic routing and switching configurations
 Enable port mirroring on switches for traƯic analysis
 Configure access control lists (ACLs) to filter traƯic, as needed
 Set up QoS to prioritize HTTP/HTTPs traƯic on routers
C. Python Automation Tasks
Students will write Python scripts to:
 Connect to routers and switches using SSH (recommended library:
netmiko)
 Capture network traƯic using Scapy, and filter for
HTTP/HTTPS packets
 Scripts capable of simulating HTTP/HTTPS requests and monitoring
network performance metrics such as response time, throughput, and
error rates.
 Generate visual reports of traƯic patterns using libraries such as
Matplotlib
 Develop a web-based dashboard using Flask to visualize traƯic data in real time (optional)
Project Deliverables:
A. Written Report
 Network topology diagram
 Network configuration details
 Python automation scripts
 Analysis of HTTP/HTTPS traƯic performance metrics
 Recommendations for improving web performance
B. Demonstration
 Live demonstration of network configuration and traƯic monitoring
 Showcasing Python scripts in action
 Real-time analysis of HTTP/HTTPS traƯic
C. Source Code Repository
 All Python scripts developed throughout the project
 Configuration files (.txt exports from routers and switches)
 Comprehensive documentation of the project steps and configurations
D. Traffic Analysis Report
 A comprehensive report that includes screenshots and analysis of
captured HTTP/HTTPS traƯic, focusing on performance metrics and any
identified issues.
Additional Recommendations (Optional)
1. Automated Performance Monitoring
- Development of additional Python scripts for real-time monitoring and
altering based on performance thresholds.
- Compare performance between HTTP and HTTPS traƯic in terms of latency
and throughput.
2. Advanced Analysis Techniques
- Implementation of machine learning algorithms to predict traƯic patterns
and performance issues based on historical data.
3. Integration with Cloud Services (Optional)
- Explore methods to collect and analyze traƯic data from cloud-based
applications to assess performance in hybrid environments. 