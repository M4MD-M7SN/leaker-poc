# Leaker Application - Technical Analysis Report

**Date:** 2026-03-03
**Version Analyzed:** Latest (commit ff73cec)
**Status:** Functional with Python 3.14 compatibility fixes applied

---

## 1. FUNCTIONALITIES AND FEATURES

### 1.1 Core Purpose
Leaker is a **data extraction and search engine** that indexes multi-format data sources into Elasticsearch, enabling instant full-text search across disparate data formats from a single interface.

**Key Value Proposition:**
- **No LLM / No API keys** - Pure deterministic parsers
- **Index once, search everything** - Unified search across all formats
- **Offline-first** - No external dependencies beyond Elasticsearch
- **Terminal-native** - REPL interface for rapid searching

---

### 1.2 Supported Data Sources

#### File Formats (Auto-detected by Extension)
| Format | Extensions | What Gets Indexed |
|--------|-----------|-------------------|
| **CSV/Delimited** | `.csv`, `.tsv`, `.psv` | Per-cell + full-row records; column names preserved |
| **Plain Text** | `.txt`, `.log` | One record per non-empty line; smart combo detection (email:password) |
| **PDF** | `.pdf` | Text lines + table cells; page numbers preserved |
| **JSON** | `.json`, `.jsonl`, `.ndjson` | Nested objects flattened to dotpath field names |
| **XML** | `.xml` | Text nodes + attributes; XPath field names |
| **Excel** | `.xlsx`, `.xls`, `.ods` | All sheets; sheet name + row + column metadata |
| **SQLite** | `.db`, `.sqlite`, `.sqlite3` | All tables, all rows, per-cell indexing |
| **SQL Dumps** | `.sql` | Parses INSERT statements; fallback line-by-line |
| **Word Docs** | `.docx` | Paragraphs + table cells |

#### Live Databases
- **PostgreSQL** - All schemas/tables with row-level extraction
- **MySQL/MariaDB** - Full database extraction
- **MongoDB** - Collection/document extraction
- **Redis** - Keys across all data types (string, hash, list, set, zset)

#### Archive Support
- **ZIP, TAR, GZ, TGZ, BZ2, 7z** - Auto-extracted recursively (max depth: 4 levels)
- **Nested archives** - Handled automatically with zip-bomb protection

---

### 1.3 Data Model

Every indexed value is stored as a **LeakerRecord** with full provenance:

```python
{
  "content":      "alice@example.com",        # The actual value
  "source":       "/data/users.csv",          # File path or DB label
  "source_type":  "csv",                      # Format identifier
  "line_number":  42,                         # Row/line (1-based)
  "column_name":  "email",                    # Field/column name
  "table_name":   "users",                    # DB table/sheet name
  "page_number":  3,                          # PDF page (if applicable)
  "doc_id":       "sha256_hash"               # Deterministic ID (prevents duplicates)
}
```

**Key Feature:** Re-indexing the same file is **idempotent** - no duplicates created.

---

### 1.4 Search Capabilities

#### Search Modes
1. **Full-Text (Default)** - Fuzzy matching with relevance scoring
2. **Exact Match** - Case-sensitive keyword search (`:exact` toggle)

#### Filtering
- **Source Type:** Restrict to specific formats (`csv`, `sqlite`, `postgres`, etc.)
- **Source Path:** Filter by file path or database label
- **Pagination:** Configurable results per page (default: 20)

#### Email/URL Preservation
Custom `email_analyzer` keeps `alice@gmail.com` as a **single token** (standard analyzers would split on `@`).

---

### 1.5 Advanced Features

#### Drop Zone Watcher
```bash
python cli.py watch --dropzone /mnt/dumps
```
- **Auto-indexing:** Drop files → auto-extracted → auto-indexed → moved to `processed/`
- **Archive handling:** ZIP/TAR/7z extracted automatically
- **Nested archive protection:** Max depth 4 (prevents zip bombs)
- **Settle timer:** Waits 2s after file creation before processing (configurable)

#### Analytics Engine
```bash
python cli.py analyze
```
**Data-Driven Analysis:**
- **Field Classification:** Auto-detects field types (email, phone, IP, hash, password, username, etc.)
- **Email Domain Clustering:** Groups by `@domain.com`
- **Phone Prefix Analysis:** Geographic clustering by country code
- **IP Subnet Analysis:** /24 subnet grouping
- **Hash Algorithm Detection:** Identifies MD5, SHA-1, SHA-256, bcrypt, etc.
- **Password Frequency:** Most common plaintext passwords
- **Trend Analysis:** Record counts per source, field type distribution

#### Interactive REPL Shell
```bash
./leak  # or: python main.py
```
**Features:**
- **Command history:** Saved to `~/.leak_history` (1000 entries)
- **Live status:** Prompt shows active filters (EXACT mode, type filters)
- **In-shell indexing:** Add new sources without exiting (`:index <path>`)
- **Session state:** Persistent settings (exact mode, type filters, page size)

---

## 2. COMMANDS AND INTERNAL OPERATIONS

### 2.1 Command-Line Interface (Non-Interactive)

#### Index Files/Directories
```bash
# Single file
./leak index /data/breach.csv

# Multiple files
./leak index users.db dump.sql passwords.txt

# Entire directory (recursive)
./leak index /mnt/data/

# Glob patterns
./leak index "exports/**/*.csv"

# Options
./leak index /data --no-progress        # Disable progress bar
./leak index /data --index custom_idx   # Custom index name
```

**Internal Flow:**
```
extract_path(path) → extract_directory() or extract_file()
  ↓
EXTENSION_MAP lookup → specific extractor (CSVExtractor, PDFExtractor, etc.)
  ↓
yield LeakerRecord objects (generator, memory-efficient)
  ↓
index_records(es, records) → streaming_bulk() to Elasticsearch
  ↓
Returns (success_count, error_count)
```

---

#### Index Live Databases
```bash
# PostgreSQL
./leak index-db postgres \
  --host localhost --port 5432 \
  --db mydb --user postgres \
  --schemas public,audit  # Optional: specific schemas

# MySQL
./leak index-db mysql \
  --host localhost --db mydb --user root

# MongoDB
./leak index-db mongo \
  --uri mongodb://localhost:27017 --db mydb

# Redis
./leak index-db redis \
  --host localhost --port 6379
```

**PostgreSQL Internal Flow:**
1. Connect via `psycopg3` (psycopg2 → psycopg3 migrated for Python 3.14)
2. Query `information_schema.tables` for schema/table list
3. `SELECT * FROM schema.table` for each table
4. Yield one `LeakerRecord` per cell (non-null, non-empty values)
5. Bulk index to Elasticsearch

---

#### List Sources
```bash
./leak sources
```
**Output:** Rich table showing:
- Source path/label
- Source types (csv, sqlite, postgres, etc.)
- Document count per source

**Implementation:** Uses Elasticsearch aggregations (no full scan).

---

#### Delete Index
```bash
./leak delete               # Prompts for confirmation
./leak delete --yes         # Skip confirmation
./leak delete --index xyz   # Custom index name
```
**Warning:** This wipes **all indexed data** - cannot be undone.

---

### 2.2 Interactive REPL Commands

#### Session Commands (Prefix: `:`)

| Command | Effect | Examples |
|---------|--------|----------|
| `:help` | Show help text | `:help` |
| `:exact` | Toggle exact-match mode (on/off) | `:exact` |
| `:type csv sqlite` | Filter results by source types | `:type csv postgres` |
| `:type` | Clear type filter | `:type` |
| `:size 50` | Set results per page (default: 20) | `:size 100` |
| `:sources` | List all indexed sources | `:sources` |
| `:index <path>` | Index files without leaving shell | `:index /data/new.csv` |
| `:exit` / `q` / `Ctrl-C` | Quit | `:exit` |

**Prompt Indicators:**
```
leak>                           # Default (fuzzy search)
EXACT leak>                     # Exact mode enabled
type:csv,sqlite leak>           # Type filter active
EXACT type:csv leak>            # Both filters active
```

---

#### Search Queries (Direct Input)
Any non-command input triggers a search:

```
leak> alice@gmail.com           # Full-text search
leak> @hotmail.com              # Partial match (all emails at domain)
leak> 555-867-5309              # Phone number
leak> password123               # Plaintext password
leak> 5f4dcc3b5aa765d61d8327    # Hash lookup
leak> John Smith                # Multi-word search
```

**Internal Search Flow:**
```
count_hits(es, query) → Lightweight ES count query (shows total)
  ↓
search(es, query, exact, source_types, size, page) → ES query execution
  ↓
Build query:
  - Exact: {"term": {"content.keyword": query}}
  - Fuzzy: {"multi_match": {query, fields: [content, column_name, table_name], fuzziness: "AUTO"}}
  ↓
Apply filters (source_type, source path)
  ↓
Highlight matching terms in results
  ↓
display_results() → Rich table or plain text output
```

---

## 3. DEPENDENCIES

### 3.1 Core Dependencies (Production)

#### Document Parsing (No LLM)
```
pypdf==4.3.1              # PDF text extraction
pdfplumber==0.11.4        # PDF table extraction (preferred)
pandas>=2.2.0             # CSV, Excel (upgraded for Python 3.14)
openpyxl==3.1.5           # Excel .xlsx
xlrd==2.0.1               # Excel .xls (legacy)
python-docx==1.1.2        # Word .docx
odfpy==1.4.1              # OpenDocument .ods
```

**Note:** `pandas>=2.2.0` uses version 3.0.1 on Python 3.14 (auto-selected for compatibility).

---

#### Database Drivers
```
psycopg[binary]>=3.1.0    # PostgreSQL (psycopg3 for Python 3.14)
pymysql==1.1.1            # MySQL/MariaDB
pymongo==4.8.0            # MongoDB
redis==5.0.8              # Redis
```

**Critical Change:** Migrated from `psycopg2-binary==2.9.9` → `psycopg3` due to lack of Python 3.14 wheels.

**Code Changes Required:**
```python
# OLD (psycopg2)
import psycopg2
import psycopg2.extras
conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# NEW (psycopg3)
import psycopg
from psycopg.rows import dict_row
conn.cursor(row_factory=dict_row)
```

---

#### Elasticsearch
```
elasticsearch==8.15.1     # Official client (bulk indexing + search)
```

**Configuration:**
- Host: `http://localhost:9200` (default)
- Auth: Basic (username/password)
- SSL verification: Disabled (local dev setup)
- Request timeout: 30s
- Batch size: 500 documents per bulk request

---

#### CLI & Display
```
click==8.1.7              # Command-line argument parsing
rich==13.7.1              # Terminal tables, colors, panels
tqdm==4.66.5              # Progress bars
```

---

#### Filesystem & Config
```
python-dotenv==1.0.1      # .env file loading
watchdog==4.0.1           # Drop zone filesystem watcher
py7zr==0.21.0             # 7-zip archive support
```

---

#### Testing
```
pytest==8.3.3             # Unit tests (no Elasticsearch required)
```

---

### 3.2 System Requirements

#### Required Services
1. **Elasticsearch 8.15.0** (via Docker)
   - Memory: 1GB heap (configured via `ES_JAVA_OPTS=-Xms1g -Xmx1g`)
   - Storage: Persistent volume (`es_data`)
   - Health check: Polls every 15s (10 retries)

2. **Kibana 8.15.0** (optional - UI for Elasticsearch)
   - Port: 5601
   - Depends on Elasticsearch health check

#### Python Version
- **Minimum:** Python 3.10+ (uses `from __future__ import annotations`)
- **Tested on:** Python 3.14.2 (with compatibility fixes)

---

### 3.3 Dependency Issues Encountered (Python 3.14)

| Package | Issue | Solution |
|---------|-------|----------|
| `pandas==2.2.2` | No wheel for Python 3.14; build fails (missing `ios` header) | Changed to `pandas>=2.2.0` (installs 3.0.1) |
| `psycopg2-binary==2.9.9` | No wheel for Python 3.14 | Migrated to `psycopg[binary]>=3.1.0` |

**Impact:** Code changes required in `functions.py` and `extractors/postgres_extractor.py` (see section 3.1).

---

## 4. ERROR HANDLING AND CHOKE POINTS

### 4.1 Error Handling Strategy

#### Philosophy
**Graceful degradation** - Never let a single bad file crash the entire indexing job.

---

### 4.2 File Extraction Error Handling

#### CSV Extractor
```python
try:
    df = pd.read_csv(path, engine="python", ...)
except Exception:
    # Fallback to stdlib csv reader
    yield from _csv_fallback(path, encoding)
    return
```
**Fallback Chain:** pandas → stdlib csv → skip file

---

#### Unknown File Types
```python
ext = os.path.splitext(path)[1].lower()
fn  = EXTENSION_MAP.get(ext)
if fn is None:
    # Unknown extension → try plain text
    try:
        yield from extract_txt(path)
    except Exception:
        pass  # Silently skip unparseable files
```

**Behavior:** Unknown extensions attempt plain-text parsing, then silently skip on failure.

---

#### Archive Extraction
```python
try:
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path, "r") as zf:
            # Filter out directory traversal attacks
            safe_names = [n for n in zf.namelist()
                          if not os.path.isabs(n) and ".." not in n]
            ...
except Exception as e:
    logger.error(f"Failed to unpack {archive_path}: {e}")
    return []
```

**Security:** Path traversal protection (`../`, absolute paths rejected).

---

### 4.3 Elasticsearch Error Handling

#### Bulk Indexing
```python
for success, info in streaming_bulk(es, gen, chunk_size=500, raise_on_error=False):
    if success:
        ok += 1
    else:
        err += 1
        console.print(f"[red][!] Index error:[/red] {info}")
```

**Behavior:**
- **Errors logged** but don't stop indexing
- Returns `(success_count, error_count)` tuple
- **Deterministic IDs** prevent duplicate indexing

---

#### Connection Errors
```python
try:
    info = es.info()
    es_version = info["version"]["number"]
except Exception as exc:
    console.print(f"[red]Cannot reach Elasticsearch:[/red] {exc}")
    console.print("Start it with:  docker compose up -d")
    sys.exit(1)
```

**User Guidance:** Provides actionable fix on connection failure.

---

### 4.4 CRITICAL LIMITS AND CHOKE POINTS

#### 1. **Elasticsearch Memory (1GB Heap)**
**Location:** `docker-compose.yml`
```yaml
ES_JAVA_OPTS=-Xms1g -Xmx1g
```

**Impact:**
- Large bulk operations may trigger OOM (Out Of Memory)
- Symptom: `java.lang.OutOfMemoryError: Java heap space`

**Mitigation:**
- Batch size limited to 500 docs per request (`ES_BATCH_SIZE=500`)
- Streaming bulk indexing (constant memory footprint)

**Recommendation:** Increase heap for datasets >10GB:
```yaml
ES_JAVA_OPTS=-Xms4g -Xmx4g  # For production
```

---

#### 2. **Elasticsearch Timeout (30s)**
**Location:** `functions.py` line 830
```python
request_timeout=30
```

**Impact:**
- Large database queries may timeout
- Symptom: `elasticsearch.exceptions.ConnectionTimeout`

**Affected Operations:**
- PostgreSQL full table scans on million-row tables
- MongoDB large collection queries

**Mitigation:**
```python
Elasticsearch(host, request_timeout=300)  # 5 minutes
```

---

#### 3. **Archive Recursion Depth (Max 4 Levels)**
**Location:** `watcher.py` line 65
```python
MAX_ARCHIVE_DEPTH = 4
```

**Purpose:** Prevent zip-bomb attacks (e.g., 42.zip)

**Impact:**
- Archives nested >4 levels deep are not fully extracted
- No error logged - silently stops unpacking

---

#### 4. **Pandas CSV Encoding Fallback**
**Default:** `utf-8-sig`

**Issue:** Non-UTF-8 files may fail silently
- Asian language dumps (Shift-JIS, GBK)
- Windows-1252 encoded files

**Current Behavior:**
```python
encoding="utf-8-sig",  # Hardcoded
...
errors="replace"       # In fallback only
```

**Choke Point:** No auto-detection for non-UTF-8 files.

---

#### 5. **No Rate Limiting on Database Extraction**
**Affected:** PostgreSQL, MySQL, MongoDB

**Code:**
```python
cur.execute(f'SELECT * FROM "{schema}"."{table}"')
for row in cur:  # Streams all rows
    yield LeakerRecord(...)
```

**Impact:**
- Can overwhelm production databases
- No `LIMIT` clause - full table scans
- Blocks database for duration of scan

**Risk:** Production database performance degradation.

**Recommendation:** Add configurable row limits:
```python
cur.execute(f'SELECT * FROM table LIMIT {max_rows}')
```

---

#### 6. **No Resume/Checkpoint System**
**Impact:** If indexing fails mid-operation (crash, Ctrl-C):
- Must re-index entire dataset
- Duplicate prevention via `doc_id` SHA-256 (re-indexing is safe but wasteful)

**Example:** Indexing 100GB database → 50% done → crash → restart from 0%

**Recommendation:** Implement checkpointing:
```python
# Save last processed table/row to state file
state = {"last_table": "users", "last_row": 500000}
```

---

#### 7. **Single-Threaded Extraction**
**Current:** Sequential file processing

**Impact:**
- Indexing 1000 small files is slow (I/O bound)
- No parallel extraction

**Bottleneck:**
```python
for path in paths:
    yield from extract_file(path)  # One at a time
```

**Recommendation:** Parallel processing:
```python
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(extract_file, p) for p in paths]
```

---

#### 8. **No Duplicate Detection Across Sources**
**Current:** `doc_id` is based on `source + content[:64]`

**Issue:** Same email in 2 different CSVs = 2 separate records

**Example:**
```
File A: alice@example.com  → doc_id: abc123
File B: alice@example.com  → doc_id: def456  (different source)
```

**Impact:**
- Search returns duplicate results
- No cross-file deduplication

---

#### 9. **Hardcoded Field Length (content[:64] in doc_id)**
**Location:** `functions.py` line 112
```python
raw = f"{self.source}|{self.source_type}|{self.line_number}|{self.content[:64]}"
```

**Impact:**
- Two cells with same first 64 chars on same line = **collision**
- Rare but possible in generated data (e.g., UUIDs)

**Example:**
```
Col A: "aaaaa...aaa" (100 chars)
Col B: "aaaaa...bbb" (100 chars)
→ Same doc_id if first 64 chars identical
```

---

#### 10. **No Schema Validation**
**Current:** Elasticsearch accepts any field structure

**Risk:**
- Mapping explosion if too many unique `column_name` values
- No field type constraints

**Symptom:** Index becomes slow after millions of unique field names.

---

#### 11. **Watchdog Settle Timer (2s Default)**
**Location:** `cli.py` line 262
```python
settle_seconds=2.0
```

**Issue:**
- Large files still copying may be processed prematurely
- Symptom: Corrupted/incomplete file indexing

**Recommendation:** Increase for network shares:
```bash
python cli.py watch --settle 10
```

---

#### 12. **No Compression on Stored Fields**
**Impact:** Large content strings stored verbatim in Elasticsearch

**Example:**
- 1 million 500-char records = ~500MB just for content
- No field compression enabled

**Recommendation:**
```python
"_source": {"enabled": True, "compress": True}
```

---

### 4.5 Known Limitations Summary

| Limitation | Impact | Severity |
|------------|--------|----------|
| 1GB ES heap | OOM on large datasets | **HIGH** |
| 30s request timeout | DB extraction timeouts | **MEDIUM** |
| No rate limiting on DBs | Production DB overload | **HIGH** |
| No resume/checkpoint | Restart from 0% on crash | **MEDIUM** |
| Single-threaded extraction | Slow for many small files | **LOW** |
| No cross-source deduplication | Duplicate search results | **MEDIUM** |
| Hardcoded UTF-8 encoding | Non-UTF-8 files fail | **MEDIUM** |
| Archive depth limit (4) | Deep nested archives truncated | **LOW** |
| doc_id collision risk | Rare but possible duplicates | **LOW** |
| No field compression | Large index sizes | **LOW** |

---

## 5. RECOMMENDATIONS

### 5.1 Immediate Fixes
1. **Increase ES heap to 4GB** for production use
2. **Add database row limits** to protect production systems
3. **Increase request timeout to 300s** for large queries
4. **Add encoding auto-detection** (e.g., `chardet` library)

### 5.2 Future Enhancements
1. **Checkpoint/resume system** for long-running jobs
2. **Parallel file extraction** (ThreadPoolExecutor)
3. **Cross-source deduplication** (hash content globally)
4. **Prometheus metrics** (index rate, error rate, queue depth)
5. **Field compression** in Elasticsearch mapping
6. **API mode** (REST API for programmatic access)

---

## 6. CONCLUSION

**Strengths:**
- ✅ Excellent error handling (graceful degradation)
- ✅ Wide format support (15+ file types)
- ✅ Deterministic indexing (idempotent re-indexing)
- ✅ Clean architecture (separation of concerns)
- ✅ Terminal-native UX (no GUI overhead)

**Weaknesses:**
- ⚠️ No production-grade safeguards (rate limiting, timeouts)
- ⚠️ Single-threaded extraction (slow for many files)
- ⚠️ No resume capability (all-or-nothing indexing)
- ⚠️ Limited memory configuration (1GB heap insufficient for large datasets)

**Overall Assessment:** Production-ready for **<100GB datasets**, **low-risk environments**. Requires hardening for **production database extraction** and **multi-TB datasets**.

---

**End of Report**
