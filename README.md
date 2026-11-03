# Leaker

**Index your data once. Search all of it, instantly, from the terminal.**

## The problem it solves

This started with **stealer logs**. Infostealer malware (RedLine, Raccoon, Lumma and the like) infects a machine and quietly exfiltrates everything useful: saved browser passwords, cookies, autofill, crypto wallets and system details. The output is a "log", and these logs circulate in huge, messy dumps, usually plain text lines like `URL:username:password`, mixed in with combolists and leaked database exports. If you do threat intelligence or check your own exposure, the practical question is simple: *does this email, domain or credential appear anywhere in millions of these lines?* Answering it is painful, because the data arrives in dozens of inconsistent formats and no two dumps look alike.

You cannot just point a language model at this. A model hallucinates, costs money on every query, has to be fed the data (a serious problem when the data is stolen credentials), and still cannot tell you the exact file, line and column a match came from. The job needs the opposite of a best guess: results that are **exact, fast, offline and fully traceable**.

So Leaker does it with plain parsing. Each format has a small parser, and **regex** pulls the useful pieces out of each line (emails, `user:pass` pairs, phone numbers, hashes). Every value is then **normalized** into one flat record that carries its own provenance (source, line, column, table, page), and the records are bulk-indexed into Elasticsearch and de-duplicated by content hash. After that you can search any value across everything instantly, and every hit tells you exactly where it came from. No model, no API keys, no guessing.

![How Leaker works](assets/flow.png)

### Live search

A real `leak` session against a live index of 810,010 records. Searching `gmail` returns **563,462 matches**, each shown as a card with its source file, line and type, and the matched term highlighted. The record fields are redacted in this screenshot because the indexed data is real.

![Leaker live search](assets/demo.png)

## Where it fits

Commercial platforms like **Intelligence X (intelx.io)**, DeHashed and Snusbase do a version of this at scale: they index breach dumps, stealer logs and leaked databases and let you search them for an email, a domain or a credential. They are genuinely valuable for threat intelligence, incident response and checking whether your own accounts are exposed.

The catch is that they are all **cloud services**. To use them you send your selectors (and sometimes your own data) to a third party, you pay per query or per seat, and you never actually hold the index. For a lot of real work that is a dealbreaker. During an incident you cannot upload a client's leaked data to someone else's server, and you routinely need to search a private corpus that no public service has ever indexed.

Leaker is the **self-hosted version of that capability**. You point it at your own collection of stealer logs and breach dumps, it builds the index on your own machine, and you search it from the terminal with full provenance on every hit. Nothing leaves your network, there is no per-query cost, and it runs completely offline. That is why it matters: the same "search every leak at once" power those platforms sell, but private, free, and on data you control.

---

## Quickstart

After cloning, the only real dependency is **Docker** (for Elasticsearch). Then you drop your data in and search:

```bash
git clone <your-repo-url> leaker && cd leaker
docker compose up -d                         # 1. start Elasticsearch
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt              # 2. install deps
alias leak="python $PWD/main.py"             # (or symlink ./leak onto your PATH)

leak watch                                   # 3. start the drop zone
#   → drag ANY files or archives into ./dropzone/ — parsed + indexed automatically
#   → or link a live DB:  leak index-db postgres --host localhost --db mydb --user postgres

leak                                         # 4. search everything from the terminal
```

---

## Setup

### 1. Install

```bash
git clone https://github.com/yourorg/Leaker.git
cd Leaker
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Start Elasticsearch

Elasticsearch ships with this repo as the included [`docker-compose.yml`](docker-compose.yml). You don't install it yourself — Docker pulls and runs it in a container, so the **only prerequisite is Docker Desktop**.

```bash
docker compose up -d
```

This pulls and starts Elasticsearch 8.15 (and Kibana) and stores its data in a Docker volume (`es_data`), so your index survives restarts.

Elasticsearch → `http://localhost:9200`
Kibana (optional UI) → `http://localhost:5601`

Default credentials: `elastic` / `changeme`
Change them in `.env` (copy from `.env.example`).

### 3. Make `leak` a system command

```bash
# Make the script executable (already done in repo)
chmod +x /path/to/Leaker/leak

# Option A — symlink into /usr/local/bin (recommended)
sudo ln -sf /path/to/Leaker/leak /usr/local/bin/leak

# Option B — add Leaker dir to your PATH
echo 'export PATH="$PATH:/path/to/Leaker"' >> ~/.bashrc
source ~/.bashrc

# Option C — alias
echo 'alias leak="python /path/to/Leaker/main.py"' >> ~/.bashrc
source ~/.bashrc
```

Now just type `leak` anywhere.

### 4. Add your data

**Drag-and-drop (recommended).** Start the drop-zone watcher, then drop files or archives into `dropzone/`:

```bash
leak watch                              # watches ./dropzone/
# now drag any mix of files (or .zip/.tar/.gz/.7z) into dropzone/
# each one is unpacked, parsed and indexed automatically, then moved to processed/
```

**Or index explicitly:**

```bash
# Files and directories
leak index data/breach.csv
leak index data/breach.csv data/users.db data/dump.sql
leak index /path/to/data/              # entire directory (recursive)
leak index "exports/**/*.csv"          # glob pattern

# Live PostgreSQL
leak index-db postgres --host localhost --db mydb --user postgres

# Live MySQL
leak index-db mysql --host localhost --db mydb --user root

# MongoDB
leak index-db mongo --uri mongodb://localhost:27017 --db mydb

# Redis
leak index-db redis --host localhost
```

### 5. Search

```bash
leak        # opens the interactive shell
```

---

## Interactive shell

Once inside `leak>`:

| Input | What happens |
|---|---|
| `alice@gmail.com` | Full-text search, all indexed sources |
| `@hotmail.com` | Partial match — finds every email at that domain |
| `555-867-5309` | Finds this phone number everywhere |
| `John Smith` | Multi-word search |
| `5f4dcc3b5aa765d61d8327` | Hash lookup |

### Session commands

| Command | Effect |
|---|---|
| `:exact` | Toggle exact-match mode on/off (default: fuzzy full-text) |
| `:type csv sqlite …` | Filter results to these source types |
| `:type` | Clear the type filter |
| `:size 50` | Set results per page (default: 20) |
| `:sources` | List all indexed sources and document counts |
| `:index <path> …` | Index new files without leaving the shell |
| `:help` | Show help |
| `:exit` / `q` / Ctrl-C | Quit |

The prompt reflects active filters:

```
EXACT type:csv,sqlite leak> alice@gmail.com
```

---

## Files

```
main.py        — entry point + interactive REPL
                 No args → opens the shell
                 Subcommands: watch, index, index-db, sources, delete

functions.py   — all logic, eight sections:
                   1. Config          reads .env
                   2. LeakerRecord    dataclass: content + provenance
                   3. File extractors csv, txt, pdf, json/jsonl, xml,
                                      excel, sqlite, sql dump, docx
                   4. DB extractors   postgres, mysql, mongodb, redis
                   5. Auto-loader     dispatch by extension/dir/glob
                   6. Elasticsearch   client, index setup, bulk indexer
                   7. Search          full-text, exact, aggregations
                   8. Display         rich table, plain-text

leak           — shell script wrapper (chmod +x, then symlink to PATH)

docker-compose.yml — Elasticsearch + Kibana (single-node, local)
requirements.txt   — Python dependencies
.env.example       — environment variable template
examples/          — sample CSV / JSON / SQL files
tests/             — unit tests (no Elasticsearch required)
```

---

## Non-interactive commands

```bash
# Drop zone: watch a folder and auto-index anything dropped in
leak watch                                  # watches ./dropzone/
leak watch --dropzone /mnt/dumps --no-move  # custom folder, keep files in place

# Index files
leak index data/breach.csv data/users.db
leak index /data/ --no-progress

# Index a database
leak index-db postgres --host localhost --port 5432 --db mydb --user postgres
leak index-db mysql    --host localhost --db mydb --user root
leak index-db mongo    --uri mongodb://localhost:27017 --db mydb
leak index-db redis    --host localhost

# List indexed sources
leak sources

# Wipe the index
leak delete
leak delete --yes   # skip confirmation
```

---

## How the flow works

```
  leak  (no args)
    │
    ▼
  run_interactive()               ← main.py
    │
    ├─ connect: get_es_client()   ← functions.py §6
    ├─ show banner + doc count
    │
    └─ loop:
         read input
           │
           ├─ :cmd  →  mutate session state  (exact, type filter, size)
           │            OR  list_sources()   ← functions.py §7
           │            OR  index_records()  ← functions.py §6
           │
           └─ query →  count_hits()          ← functions.py §7
                    →  search()              ← functions.py §7
                    →  display_results()     ← functions.py §8
```

---

## Supported sources

### Files (auto-detected by extension)

| Extension(s) | What is indexed |
|---|---|
| `.csv` `.tsv` `.psv` | Per-cell + full-row; column name on every record |
| `.txt` `.log` | One record per non-empty line |
| `.pdf` | Text lines + table cells; page number on every hit |
| `.json` `.jsonl` `.ndjson` | Nested objects flattened to dotpath field names |
| `.xml` | Text nodes + attributes; XPath field names |
| `.xlsx` `.xls` `.ods` | All sheets; sheet name + row + column on every record |
| `.db` `.sqlite` `.sqlite3` | All tables, all rows, per-cell |
| `.sql` | Parses `INSERT` statements; falls back to line-by-line |
| `.docx` | Paragraphs + table cells |

### Live databases

| DB | Command |
|---|---|
| PostgreSQL | `leak index-db postgres` |
| MySQL / MariaDB | `leak index-db mysql` |
| MongoDB | `leak index-db mongo` |
| Redis | `leak index-db redis` |

---

## Elasticsearch index schema

Every indexed value is stored with its full provenance:

```
content      text   — the value (email_analyzer: emails stay as one token)
source       str    — file path or DB connection label
source_type  str    — csv | pdf | sqlite | postgres | …
line_number  int    — row / line (1-based)
column_name  str    — column or field name
table_name   str    — DB table, collection, or Excel sheet name
page_number  int    — PDF page number
doc_id       str    — SHA-256 (re-indexing same data = no duplicates)
```

---

## Adding a new format

1. Write an extractor in `functions.py` section 3:

```python
def extract_myformat(path: str) -> Generator[LeakerRecord, None, None]:
    for row_num, value in enumerate(your_parser(path), start=1):
        yield LeakerRecord(
            content=str(value),
            source=path,
            source_type="myformat",
            line_number=row_num,
        )
```

2. Register the extension in `EXTENSION_MAP` (section 5):

```python
".myfmt": extract_myformat,
```

Done — it works in the shell immediately.

---

## Running tests

```bash
pytest tests/ -v
```

No Elasticsearch or live database needed.

---

## License

MIT
