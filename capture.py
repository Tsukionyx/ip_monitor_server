"""
Packet capture and statistics for IP Traffic Monitor.
SPDX-License-Identifier: GPL-2.0-only
"""

import threading
from collections import Counter

from scapy.all import AsyncSniffer, IP, TCP, UDP, ICMP


class CaptureManager:
    """Manage one Scapy capture session and its IPv4 source-IP statistics."""

    def __init__(self):
        self._lock = threading.RLock()
        self._sniffer = None
        self._counts = Counter()
        self._total_packets = 0
        self._last_error = None
        self._running = False

    def _handle_packet(self, packet):
        if IP not in packet:
            return

        source_ip = packet[IP].src
        with self._lock:
            self._counts[source_ip] += 1
            self._total_packets += 1

    def start(self, iface, bpf_filter=""):
        with self._lock:
            if self._running:
                raise RuntimeError("Packet capture is already running.")

            self._last_error = None
            sniffer = AsyncSniffer(
                iface=iface,
                filter=bpf_filter or None,
                prn=self._handle_packet,
                store=False,
            )
            self._sniffer = sniffer

            try:
                sniffer.start()
                self._running = True
            except Exception:
                self._sniffer = None
                self._running = False
                raise

    def stop(self):
        with self._lock:
            sniffer = self._sniffer
            if not sniffer or not self._running:
                self._running = False
                return

        try:
            # AsyncSniffer.stop() signals the capture loop without waiting
            # for another packet to arrive.
            sniffer.stop(join=True)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            raise
        finally:
            with self._lock:
                self._running = False
                self._sniffer = None

    def reset(self):
        with self._lock:
            self._counts.clear()
            self._total_packets = 0
            self._last_error = None

    def get_stats(self):
        with self._lock:
            top_sources = [
                {"ip": ip, "packets": count}
                for ip, count in self._counts.most_common(10)
            ]
            return {
                "running": self._running,
                "total_packets": self._total_packets,
                "unique_ips": len(self._counts),
                "top_sources": top_sources,
                "error": self._last_error,
            }
