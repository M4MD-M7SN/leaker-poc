# Drop zone

While `leak watch` is running, drag any data files or archives into this folder.
Each one is parsed and indexed automatically, then moved to `../processed/`.

Supported: CSV, TSV, PSV, TXT, LOG, PDF, JSON, JSONL, XML, Excel (xlsx/xls/ods),
SQLite, SQL dumps, DOCX — plus `.zip`, `.tar`, `.gz`, `.7z` archives (unpacked recursively).

Your dropped data stays local; this folder's contents are gitignored.
