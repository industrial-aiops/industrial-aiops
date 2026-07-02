# Grafana recipe — see collected OT data in minutes

The queryability layer (MARKET-INSIGHTS R5): samples collected with
`historian_push(sink="sqlite")` / `iaiops historian push --sink sqlite` land in
`~/.iaiops/data.db`. Two ways into Grafana:

## 1. Prometheus bridge (live values)

Start the exporter (loopback by default; `--host` widens it — a warning is
printed for `0.0.0.0`):

```bash
iaiops metrics serve --port 9184
```

`GET http://127.0.0.1:9184/metrics` exposes:

- `iaiops_tag_value{endpoint,protocol,tag,unit}` — latest numeric value per tag (gauge)
- `iaiops_samples_written_total` — rows in the local store (counter)
- `iaiops_audit_events_total` / `iaiops_tool_errors_total` — governance counters

Prometheus scrape config (`prometheus.yml`):

```yaml
scrape_configs:
  - job_name: iaiops
    scrape_interval: 15s
    static_configs:
      - targets: ["127.0.0.1:9184"]
```

Example Grafana panel (timeseries, one series per tag):

```json
{
  "type": "timeseries",
  "title": "OT tag values",
  "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
  "targets": [
    {
      "expr": "iaiops_tag_value",
      "legendFormat": "{{endpoint}}/{{tag}} ({{unit}})"
    }
  ]
}
```

## 2. SQLite datasource (full history)

Install the community `frser-sqlite-datasource` plugin and point it at
`~/.iaiops/data.db` (or at a snapshot made with
`iaiops export sqlite --out /tmp/ot.db` to keep Grafana off the live WAL file).
Table `samples(ts, endpoint, protocol, tag, value, quality, unit)`; `ts` is
ISO-8601 text:

```sql
SELECT ts, value FROM samples
WHERE tag = 'line1.temp' AND ts >= '2026-07-01T00:00:00'
ORDER BY ts
```

## No Grafana? Export instead

`iaiops export csv|sqlite|parquet [--since --until --endpoint --tag --limit]`
writes an open-format file for Excel / Power BI / pandas (`parquet` needs
`pip install 'iaiops[export]'`).
