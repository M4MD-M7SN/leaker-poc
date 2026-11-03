"""
analytics.py — Clustering and Trend Analysis  (Post-Indexing Layer)
====================================================================

ROLE IN THE PIPELINE
--------------------
  Raw files  →  [extractors/]  →  Elasticsearch  →  [analytics.py]
               (parse/organize)   (store/index)      (cluster/trends)

This module is DATA-DRIVEN.  It does NOT assume the indexed data contains
only emails and passwords.  It first discovers what field types actually
exist in the index, then runs appropriate analysis for each one.

FIELD TYPES UNDERSTOOD
-----------------------
  email        domain clustering  (gmail, yahoo, corporate …)
  phone        country / area-code clustering  (+1-415, +44-20 …)
  ip_address   subnet clustering  (/24 prefix)
  hash         type breakdown  (MD5 / SHA1 / SHA256 / bcrypt …)
  password     frequency  (most common plaintext passwords)
  username     frequency  (most repeated usernames)
  name         frequency
  user_id      frequency
  ssn          count only  (no value display — sensitive)
  credit_card  count only  (no value display — sensitive)
  address      frequency
  date         frequency
  url          domain clustering
  *any other*  generic top-N frequency

USAGE (CLI)
-----------
  python cli.py analyze                          # full auto report
  python cli.py analyze --topic fields           # what field types exist
  python cli.py analyze --topic field email      # deep-dive into one type
  python cli.py analyze --topic passwords        # password frequency
  python cli.py analyze --topic domains          # email domain clustering
  python cli.py analyze --topic phones           # phone prefix clustering
  python cli.py analyze --topic ips              # IP subnet clustering
  python cli.py analyze --topic hashes           # hash type breakdown
  python cli.py analyze --topic sources          # records per source file
  python cli.py analyze --top 50                 # show top 50 per section
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from elasticsearch import Elasticsearch
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

console = Console()

# ── Regex helpers ──────────────────────────────────────────────────────────────
_HASH_MD5    = re.compile(r"^[0-9a-fA-F]{32}$")
_HASH_SHA1   = re.compile(r"^[0-9a-fA-F]{40}$")
_HASH_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_HASH_SHA512 = re.compile(r"^[0-9a-fA-F]{128}$")
_HASH_BCRYPT = re.compile(r"^\$(2[aby]?|1|5|6)\$")

# Fields that are too sensitive to display top values for
_SENSITIVE_FIELDS = {"ssn", "credit_card"}

# Fields that benefit from domain/prefix clustering instead of raw top-N
_CLUSTER_FIELDS = {"email", "url", "phone", "ip_address"}

# Human-readable display names for field types
_FIELD_LABELS: dict[str, str] = {
    "email":       "Email Addresses",
    "password":    "Passwords",
    "hash":        "Hashes",
    "phone":       "Phone Numbers",
    "username":    "Usernames",
    "name":        "Names",
    "first_name":  "First Names",
    "last_name":   "Last Names",
    "user_id":     "User IDs",
    "ip_address":  "IP Addresses",
    "url":         "URLs",
    "address":     "Addresses",
    "date":        "Dates",
    "postal_code": "Postal Codes",
    "ssn":         "Social Security Numbers",
    "credit_card": "Credit Card Numbers",
}


# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FieldTypeSummary:
    field_type: str
    count:      int

@dataclass
class TopValueStat:
    value: str
    count: int

@dataclass
class ClusterStat:
    """A group of values clustered by a common prefix/pattern."""
    cluster: str   # e.g. "gmail.com", "+1-415", "192.168.1"
    count:   int

@dataclass
class HashTypeStat:
    hash_type: str   # "MD5", "SHA1", "SHA256", "SHA512", "bcrypt", "other"
    count:     int

@dataclass
class SourceStat:
    source: str
    count:  int
    types:  list[str]

@dataclass
class FieldReport:
    """Full analysis for one field type."""
    field_type:  str
    count:       int
    top_values:  list[TopValueStat]     = field(default_factory=list)
    clusters:    list[ClusterStat]      = field(default_factory=list)
    hash_types:  list[HashTypeStat]     = field(default_factory=list)
    is_sensitive: bool                  = False

@dataclass
class AnalyticsReport:
    field_type_counts: list[FieldTypeSummary]   # what types exist and how many
    field_reports:     list[FieldReport]        # deep analysis per type
    source_stats:      list[SourceStat]
    total_records:     int = 0
    combo_records:     int = 0


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class Analytics:
    """
    Runs aggregation queries against the Leaker Elasticsearch index.

    All methods use ES aggregations — no full table scan.
    """

    def __init__(self, es: Elasticsearch, index: str):
        self.es    = es
        self.index = index

    # ── Discover what's in the index ──────────────────────────────────────

    def field_types(self, top_n: int = 50) -> list[FieldTypeSummary]:
        """
        Return every column_name that exists in the index with its record count.
        This is the foundation of the data-driven approach — we see what's
        actually there before deciding what to analyse.
        """
        resp = self.es.search(
            index=self.index,
            size=0,
            aggs={
                "by_col": {
                    "terms": {
                        "field": "column_name",
                        "size":  top_n,
                        "order": {"_count": "desc"},
                    }
                }
            },
        )
        return [
            FieldTypeSummary(field_type=b["key"], count=b["doc_count"])
            for b in resp["aggregations"]["by_col"]["buckets"]
        ]

    # ── Generic top-N values for any field type ────────────────────────────

    def top_values(
        self,
        field_type: str,
        top_n: int = 30,
        skip_hashes: bool = False,
    ) -> list[TopValueStat]:
        """
        Return the most frequent values for a given column_name.

        skip_hashes=True filters out MD5/SHA/bcrypt-looking values
        (useful for the "password" field type which may contain mixed data).
        """
        resp = self.es.search(
            index=self.index,
            size=0,
            query={"term": {"column_name": field_type}},
            aggs={
                "vals": {
                    "terms": {
                        "field": "content.keyword",
                        "size":  top_n * 3,
                        "order": {"_count": "desc"},
                    }
                }
            },
        )
        stats = []
        for bucket in resp["aggregations"]["vals"]["buckets"]:
            val = bucket["key"]
            if skip_hashes and (
                _HASH_MD5.match(val)
                or _HASH_SHA1.match(val)
                or _HASH_SHA256.match(val)
                or _HASH_SHA512.match(val)
                or _HASH_BCRYPT.match(val)
            ):
                continue
            stats.append(TopValueStat(value=val, count=bucket["doc_count"]))
            if len(stats) >= top_n:
                break
        return stats

    # ── Email: cluster by domain ───────────────────────────────────────────

    def email_domains(self, top_n: int = 30) -> list[ClusterStat]:
        """Group email addresses by their domain (everything after @)."""
        resp = self.es.search(
            index=self.index,
            size=0,
            query={
                "bool": {
                    "should": [
                        {"term":   {"column_name": "email"}},
                        {"regexp": {"content.keyword": ".+@.+\\..+"}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            aggs={
                "domains": {
                    "terms": {
                        "script": {
                            "source": (
                                "String c = doc['content.keyword'].value; "
                                "int at = c.indexOf('@'); "
                                "return (at >= 0)"
                                "  ? c.substring(at + 1).toLowerCase()"
                                "  : 'unknown';"
                            ),
                            "lang": "painless",
                        },
                        "size":  top_n,
                        "order": {"_count": "desc"},
                    }
                }
            },
        )
        return [
            ClusterStat(cluster=b["key"], count=b["doc_count"])
            for b in resp["aggregations"]["domains"]["buckets"]
        ]

    # ── URL: cluster by host ───────────────────────────────────────────────

    def url_hosts(self, top_n: int = 30) -> list[ClusterStat]:
        """Group URLs by their hostname."""
        resp = self.es.search(
            index=self.index,
            size=0,
            query={"term": {"column_name": "url"}},
            aggs={
                "hosts": {
                    "terms": {
                        "script": {
                            "source": (
                                "String u = doc['content.keyword'].value; "
                                "int s = u.indexOf('://'); "
                                "if (s < 0) return u; "
                                "String rest = u.substring(s + 3); "
                                "int sl = rest.indexOf('/'); "
                                "return (sl >= 0) ? rest.substring(0, sl) : rest;"
                            ),
                            "lang": "painless",
                        },
                        "size":  top_n,
                        "order": {"_count": "desc"},
                    }
                }
            },
        )
        return [
            ClusterStat(cluster=b["key"], count=b["doc_count"])
            for b in resp["aggregations"]["hosts"]["buckets"]
        ]

    # ── Phone: cluster by country/area code prefix ─────────────────────────

    def phone_prefixes(self, top_n: int = 30) -> list[ClusterStat]:
        """
        Group phone numbers by their leading digits (country + area code).
        Uses first 4–6 digits after stripping non-digit characters.
        """
        resp = self.es.search(
            index=self.index,
            size=0,
            query={"term": {"column_name": "phone"}},
            aggs={
                "prefixes": {
                    "terms": {
                        "script": {
                            "source": (
                                "String p = doc['content.keyword'].value"
                                "  .replaceAll('[^0-9]', ''); "
                                "return (p.length() >= 4)"
                                "  ? p.substring(0, Math.min(p.length(), 4))"
                                "  : p;"
                            ),
                            "lang": "painless",
                        },
                        "size":  top_n,
                        "order": {"_count": "desc"},
                    }
                }
            },
        )
        return [
            ClusterStat(cluster=b["key"], count=b["doc_count"])
            for b in resp["aggregations"]["prefixes"]["buckets"]
        ]

    # ── IP: cluster by /24 subnet ──────────────────────────────────────────

    def ip_subnets(self, top_n: int = 30) -> list[ClusterStat]:
        """Group IP addresses by their first three octets (/24 subnet)."""
        resp = self.es.search(
            index=self.index,
            size=0,
            query={"term": {"column_name": "ip_address"}},
            aggs={
                "subnets": {
                    "terms": {
                        "script": {
                            "source": (
                                "String ip = doc['content.keyword'].value; "
                                "int last = ip.lastIndexOf('.'); "
                                "return (last >= 0)"
                                "  ? ip.substring(0, last) + '.0/24'"
                                "  : ip;"
                            ),
                            "lang": "painless",
                        },
                        "size":  top_n,
                        "order": {"_count": "desc"},
                    }
                }
            },
        )
        return [
            ClusterStat(cluster=b["key"], count=b["doc_count"])
            for b in resp["aggregations"]["subnets"]["buckets"]
        ]

    # ── Hash: classify by type ─────────────────────────────────────────────

    def hash_types(self, top_n: int = 10) -> list[HashTypeStat]:
        """
        Break down indexed hashes by algorithm, determined by string length
        and prefix patterns.
        """
        resp = self.es.search(
            index=self.index,
            size=0,
            query={"term": {"column_name": "hash"}},
            aggs={
                "by_type": {
                    "terms": {
                        "script": {
                            "source": (
                                "String h = doc['content.keyword'].value; "
                                "if (h.startsWith('$2') || h.startsWith('$1') "
                                "    || h.startsWith('$5') || h.startsWith('$6')) "
                                "  return 'bcrypt/crypt'; "
                                "int l = h.length(); "
                                "if (l == 32)  return 'MD5'; "
                                "if (l == 40)  return 'SHA-1'; "
                                "if (l == 56)  return 'SHA-224'; "
                                "if (l == 64)  return 'SHA-256'; "
                                "if (l == 96)  return 'SHA-384'; "
                                "if (l == 128) return 'SHA-512'; "
                                "return 'other (' + l + ' chars)';"
                            ),
                            "lang": "painless",
                        },
                        "size":  top_n,
                        "order": {"_count": "desc"},
                    }
                }
            },
        )
        return [
            HashTypeStat(hash_type=b["key"], count=b["doc_count"])
            for b in resp["aggregations"]["by_type"]["buckets"]
        ]

    # ── Source statistics ──────────────────────────────────────────────────

    def source_stats(self, top_n: int = 30) -> list[SourceStat]:
        """Record count and source_type breakdown per source file / connection."""
        resp = self.es.search(
            index=self.index,
            size=0,
            aggs={
                "by_source": {
                    "terms": {
                        "field": "source",
                        "size":  top_n,
                        "order": {"_count": "desc"},
                    },
                    "aggs": {
                        "by_type": {
                            "terms": {"field": "source_type", "size": 15}
                        }
                    },
                }
            },
        )
        return [
            SourceStat(
                source=b["key"],
                count=b["doc_count"],
                types=[t["key"] for t in b["by_type"]["buckets"]],
            )
            for b in resp["aggregations"]["by_source"]["buckets"]
        ]

    # ── Overview counts ────────────────────────────────────────────────────

    def overview(self) -> dict[str, int]:
        """High-level document counts: total, combo, and per source_type."""
        resp = self.es.search(
            index=self.index,
            size=0,
            aggs={
                "total":    {"value_count": {"field": "content.keyword"}},
                "by_type":  {"terms": {"field": "source_type",  "size": 30}},
            },
        )
        type_counts = {
            b["key"]: b["doc_count"]
            for b in resp["aggregations"]["by_type"]["buckets"]
        }
        return {
            "total_records": resp["aggregations"]["total"]["value"],
            "combo_records": type_counts.get("combo", 0),
            **{k: v for k, v in type_counts.items() if k != "combo"},
        }

    # ── Per-field deep analysis ────────────────────────────────────────────

    def analyse_field(self, field_type: str, count: int, top_n: int) -> FieldReport:
        """
        Run the best analysis for a given field type:
          - sensitive fields  → count only, no values displayed
          - email / url       → cluster by domain / host
          - phone             → cluster by prefix
          - ip_address        → cluster by /24 subnet
          - hash              → break down by algorithm
          - password          → top-N, skipping hashes
          - everything else   → generic top-N
        """
        report = FieldReport(
            field_type=field_type,
            count=count,
            is_sensitive=field_type in _SENSITIVE_FIELDS,
        )

        if field_type in _SENSITIVE_FIELDS:
            return report   # never display values for SSN / CC

        if field_type == "email":
            report.clusters = self.email_domains(top_n)

        elif field_type == "url":
            report.clusters = self.url_hosts(top_n)

        elif field_type == "phone":
            report.clusters  = self.phone_prefixes(top_n)
            report.top_values = self.top_values(field_type, top_n)

        elif field_type == "ip_address":
            report.clusters = self.ip_subnets(top_n)

        elif field_type == "hash":
            report.hash_types = self.hash_types()

        elif field_type == "password":
            report.top_values = self.top_values(field_type, top_n, skip_hashes=True)

        else:
            report.top_values = self.top_values(field_type, top_n)

        return report

    # ── Full report ────────────────────────────────────────────────────────

    def full_report(self, top_n: int = 20) -> AnalyticsReport:
        """
        Discover what field types exist in the index, then run the
        appropriate analysis for each one.  Fully data-driven.
        """
        ov     = self.overview()
        fields = self.field_types(top_n=50)

        field_reports = [
            self.analyse_field(f.field_type, f.count, top_n)
            for f in fields
        ]

        return AnalyticsReport(
            field_type_counts = fields,
            field_reports     = field_reports,
            source_stats      = self.source_stats(top_n),
            total_records     = ov.get("total_records", 0),
            combo_records     = ov.get("combo_records", 0),
        )


# ══════════════════════════════════════════════════════════════════════════════
# DISPLAY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _label(field_type: str) -> str:
    return _FIELD_LABELS.get(field_type, field_type.replace("_", " ").title())


def display_field_types(summaries: list[FieldTypeSummary]) -> None:
    """Print a summary table of all field types found in the index."""
    if not summaries:
        console.print("[yellow]No typed fields in the index yet.[/yellow]")
        return
    t = Table("Field Type", "Records", box=box.ROUNDED)
    for s in summaries:
        label = _label(s.field_type)
        t.add_row(label, f"{s.count:,}")
    console.print(Panel(t, title="[bold cyan]Field Types in Index[/bold cyan]", expand=False))


def display_field_report(r: FieldReport) -> None:
    """Print the analysis for one field type."""
    title = f"[bold cyan]{_label(r.field_type)}[/bold cyan]  [dim]({r.count:,} records)[/dim]"

    if r.is_sensitive:
        console.print(Panel(
            f"[yellow]{r.count:,} records found — values not displayed for privacy.[/yellow]",
            title=title, expand=False,
        ))
        return

    if r.hash_types:
        t = Table("Hash Type", "Count", box=box.ROUNDED)
        for h in r.hash_types:
            t.add_row(h.hash_type, f"{h.count:,}")
        console.print(Panel(t, title=title, expand=False))
        return

    if r.clusters:
        heading = {
            "email":      "Domain",
            "url":        "Host",
            "phone":      "Prefix",
            "ip_address": "Subnet (/24)",
        }.get(r.field_type, "Cluster")

        t = Table("Rank", heading, "Count", box=box.ROUNDED)
        for i, c in enumerate(r.clusters, 1):
            t.add_row(str(i), c.cluster, f"{c.count:,}")
        console.print(Panel(t, title=title, expand=False))

        # If phone also has top-N values, print them separately
        if r.field_type == "phone" and r.top_values:
            t2 = Table("Rank", "Phone Number", "Count", box=box.ROUNDED)
            for i, v in enumerate(r.top_values[:10], 1):
                t2.add_row(str(i), v.value, f"{v.count:,}")
            console.print(Panel(t2, title=f"[cyan]Top Phone Numbers[/cyan]", expand=False))
        return

    if r.top_values:
        t = Table("Rank", _label(r.field_type), "Count", box=box.ROUNDED)
        for i, v in enumerate(r.top_values, 1):
            # Truncate very long values for display
            display_val = v.value[:80] + "…" if len(v.value) > 80 else v.value
            t.add_row(str(i), display_val, f"{v.count:,}")
        console.print(Panel(t, title=title, expand=False))


def display_overview(ov: dict[str, int]) -> None:
    t = Table("Metric", "Count", box=box.SIMPLE_HEAD)
    for k, v in ov.items():
        t.add_row(k.replace("_", " ").title(), f"{v:,}")
    console.print(Panel(t, title="[bold cyan]Overview[/bold cyan]", expand=False))


def display_sources(stats: list[SourceStat]) -> None:
    if not stats:
        console.print("[yellow]No sources indexed.[/yellow]")
        return
    t = Table("Source", "Records", "Types", box=box.ROUNDED)
    for s in stats:
        display_path = "/".join(s.source.replace("\\", "/").split("/")[-2:])
        t.add_row(display_path, f"{s.count:,}", ", ".join(s.types))
    console.print(Panel(t, title="[bold cyan]Source Statistics[/bold cyan]", expand=False))


def display_full_report(report: AnalyticsReport) -> None:
    """Print the complete analytics report — adapts to whatever is in the index."""
    console.rule("[bold cyan]Leaker Analytics Report[/bold cyan]")

    # Overview
    display_overview({
        "Total Records": report.total_records,
        "Combo Records": report.combo_records,
    })

    # Field type summary table first
    display_field_types(report.field_type_counts)

    # Deep analysis per field type
    for r in report.field_reports:
        display_field_report(r)

    # Sources
    display_sources(report.source_stats)

    console.rule()
