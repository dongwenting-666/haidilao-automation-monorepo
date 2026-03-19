# Documentation

Architecture and reference documentation for the Haidilao Automation Monorepo.

## Contents

- [Architecture Overview](./architecture.md) — Monorepo structure, package relationships, data flow
- [SAP GUI Library](./sap-gui.md) — Cross-platform SAP GUI automation (COM on Windows, Scripting Console on macOS)
- [QBI Crawler](./qbi-crawler.md) — Quick BI web crawler (Playwright, LDAP login, XLSX export)
- [Excel Utils](./excel-utils.md) — Shared Excel generation utilities (openpyxl readers, writers, styling)
- [KSB1 Accounting Check](./ksb1-accounting-check.md) — Report pipeline, analysis rules, LLM enhancement, output format
- [KSB1 GUI & EXE](./ksb1-accounting-check-gui.md) — Desktop GUI application and PyInstaller packaging
- [Daily Store Operation Report](./daily-store-operation-report.md) — QBI data pipeline, 4-sheet Excel report generation
- [VPN Library](./vpn.md) — SealSuite/CorpLink VPN automation (macOS, cliclick, log-based status)
- [Lark Client](./lark-client.md) — Feishu/Lark bot client (messaging, Drive, OAuth)
- [DB Client](./db-client.md) — PostgreSQL client (psycopg3 pool, migrations)
- [Server](./server.md) — FastAPI server, admin UI, Lark OAuth, run queue, scheduler
- [Treasury Loan Watch](./treasury-loan-watch.md) — Daily TREASURY inter-company loan maturity checker
- [Edit History](./edit-history/) — Session-level change logs
