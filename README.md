<!-- mcp-name: io.github.industrial-aiops/iaiops -->

# Industrial-AIOps

**English** · [中文](README.zh-CN.md)

**Governed, vendor-neutral industrial data tap + intelligent troubleshooting for AI agents — read-first tools across 14 field protocols in this package (17 line-wide with the energy edition): OPC-UA (incl. Historical Access + tag auto-discovery), Modbus-TCP/RTU (byte-order auto-detect + vendor templates), S7comm, Mitsubishi MC, Omron FINS (stdlib-only client), MTConnect, MQTT/Sparkplug B (full decode), EtherNet/IP (Rockwell/Allen-Bradley Logix), EtherCAT (pysoem/SOEM), PROFINET (DCP), SECS/GEM (HSMS fab), HART-IP (process instrumentation), BACnet/IP (building), and IO-Link (master JSON integration), plus two vendor-REST **read-only** layers above the field bus — a **BAS supervisory-controller layer** (Johnson Controls Metasys / Tridium Niagara, sitting above the BACnet field connector, building edition) and an **Ignition Gateway MES/SCADA read layer** (Inductive Automation Ignition's HTTP/Gateway web API — module health, tag browse/read, alarms, tag-history — factory edition) — plus an AI downtime root-cause copilot (with a `downtime_triage` composer), conservative baseline learning, ISA-18.2 alarm-flood analysis, historian READ integration (RCA pre-incident evidence), a legacy PLC program explainer (ST/AWL/L5X), nine per-industry editions (fab / factory / process / building / water / warehouse / clinical / renewables / plcnext) each carrying its own read-only advisory checks (SPC, PID control-loop, AHU economizer, line bottleneck, medical-gas, disinfection-CT …), open-format export (`iaiops export` CSV/SQLite/Parquet) with a Prometheus/Grafana bridge, data-quality watchdog, UNS governance, OEE/downtime, asset-inventory, and 信创 (TDengine/IoTDB historian sinks + 防护指南/等保2.0/IEC 62443 compliance mapping, report & evidence bundle). The energy edition (变电/电力: IEC-104 / DNP3 / IEC-61850) ships separately as [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy).**

Industrial-AIOps is the OT member of the [industrial-aiops](https://github.com/industrial-aiops) org. It is a **factory-level, vendor-neutral, governed data tap** that lets an AI agent safely *read* industrial control systems across many field protocols, plus a **cross-protocol intelligence layer** that localizes "no data" breaks, analyzes alarm floods (ISA-18.2), scores data trustworthiness, ranks unhealthy tags, computes OEE / categorizes downtime, builds an active asset register, auto-discovers OPC-UA tags into a semantic asset model, and — the flagship — runs an **AI downtime root-cause copilot** that correlates the evidence into an **evidence-cited, advisory** verdict. Read-first by design; the few write/command paths are OT-dangerous and gated by MOC discipline. Every tool runs through a vendored governance harness (audit / budget / risk-tier / undo).

> **v0.13.0 — validation status (honest).** Pure analysis + the OPC-UA path are tested against a **real in-process asyncua server**. The 信创 bindings were run against **real libraries + containers**: **IoTDB** + **TDengine** (live container write→read round-trip) are **verified**; the HART command codec is verified vs `hart-protocol`. **Phoenix Contact PLCnext vPLC** (virtualized PLC) is **route-verified** over its OPC-UA server (an in-process `asyncua` server reproducing the `Arp.Plc.Eclr` GDS address space) and a Modbus-TCP process-data block (`tests/test_plcnext_route.py`); live PLCnext hardware reads stay `待核实`. **Modbus-RTU (live serial)** is **verified** (2026-07-02): the read ops round-trip over a real serial link built from a `socat` PTY pair + a `pymodbus` RTU server (`tests/test_modbus_rtu_live.py`), exercising the actual RTU framing — though not yet validated against a specific physical RS-485 device. The **BACnet/IP read path** is **verified** (2026-07-02): a genuine Who-Is discover + present-value read round-trip against a **real bacpypes3 virtual BACnet/IP device** on a two-IP subnet in a Linux container (`tests/test_bacnet_live.py`), through the actual async BAC0 (2024+) stack. The new **Omron FINS** connector is verified against an in-repo mock FINS UDP/TCP responder (`tests/test_fins.py`); the new **IO-Link** connector against an in-process mock master in both JSON dialects (`tests/test_iolink.py`). The two new vendor-REST read layers are **mock-verified**: the **BAS controller layer** against an in-repo mock supervisory controller in **both vendor dialects (Metasys OpenBlue REST + Niagara oBIX/REST)**, and the **Ignition Gateway** read layer against an in-repo mock Gateway in **both flavors (`webdev` / `gateway`)** — live Metasys/Niagara controllers (incl. native oBIX-XML encoding) and live Ignition gateways (exact API version/paths) stay `待核实`. **Still `待核实` (preview, not hardware-verified):** live Omron PLCs (incl. banked-EM access), live IO-Link master datapoint paths, BACnet write/COV/trend on live HVAC, HART-IP wire transport (live gateway), EtherCAT (no software simulator — Linux + root + a real bus only), physical Modbus-RTU RS-485 devices, live PLCnext. Mocked clients cover S7/MC/EtherNet-IP/SECS-GEM; MTConnect uses static XML fixtures; Sparkplug uses synthetic protobuf payloads. (The energy edition's IEC-104 / DNP3 / IEC-61850 validation lives in the [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy) repo.) See *Safety*.

## Why

OT is exactly where you want an agent on a tight leash: read first, never blind-write. Industrial-AIOps is the **safe, neutral read wedge** — one package, one MCP server, many protocols — with governance and an intelligence layer that turns raw reads into actionable diagnoses.

## 🧪 测试与共创 / Beta testing & co-creation

**我们在找现场测试伙伴。** 软件里能验证的我们都验证了（真实 in-process 服务器、真实协议库、Docker 容器 loopback）——剩下的 `待核实` 清单只有真设备能回答：物理 Modbus-RTU（RS-485）、EtherCAT 从站、HART 网关、在线 BACnet 楼宇设备、在线 Metasys/Niagara BAS 控制器、在线 Ignition 网关、国产 PLC（汇川/信捷）、真机 PLCnext、真实变电站 RTU/IED、欧姆龙 FINS 真机、IO-Link 主站。如果你是 OT 工程师、系统集成商或工厂团队，手上有任何这类设备：装上 `iaiops`，对你的设备跑一遍 `iaiops doctor`，把结果告诉我们。**经你验证的设备会署名写进支持矩阵**；现场反馈的问题我们优先分诊；功能可以通过 GitHub Issues/Discussions 直接共创。

**We're looking for field-testing partners.** Everything software-verifiable has been verified; what's left on the honest `待核实` list only real equipment can answer — physical Modbus-RTU (RS-485), EtherCAT slaves, HART gateways, live BACnet HVAC, live Metasys/Niagara BAS controllers, live Ignition gateway, domestic PLCs (Inovance/Xinje), live PLCnext, substation RTUs/IEDs, live Omron FINS PLCs, IO-Link masters. If you're an OT engineer, integrator, or factory team with access to any of these: install `iaiops`, run `iaiops doctor` against your gear, and tell us what happened. **Verified-equipment reports get credited in the support matrix**, field-reported issues get fast triage, and features are co-designed in the open via GitHub Issues/Discussions.

👉 **参与入口 | Start here: [#28 — 招募现场测试伙伴 | Call for field-testing partners (v0.10.0)](https://github.com/industrial-aiops/industrial-aiops/issues/28)** (pinned)

---

## Consolidated capability matrix

| Protocol | Tool | Operation | R/W | risk_tier | Returns (key fields) |
|----------|------|-----------|:---:|:---------:|----------------------|
| OPC-UA | `opcua_server_info` | server status | R | low | state, product_name, namespaces |
| OPC-UA | `opcua_browse` | browse node tree | R | low | [{node_id, browse_name, depth}] |
| OPC-UA | `opcua_read_node` | read one node | R | low | value, datatype, source_timestamp, good |
| OPC-UA | `opcua_read_many` | batch read | R | low | [{node_id, value, ...}] |
| OPC-UA | `opcua_subscribe_sample` | bounded sample | R | low | {collected, samples[]} |
| OPC-UA | `opcua_read_alarms` | alarm surfacing | R | low | {active_alarms[], active_count} |
| OPC-UA | `opcua_read_history` | Historical Access (HDA) | R | low | {supported, count, values[]} |
| OPC-UA | `opcua_diagnose_connection` | connection triage | R | low | {verdict, checks[]} |
| OPC-UA | `opcua_discover_tags` | tag auto-discovery → semantic asset model | R | low | {tag_count, assets[], naming_report} |
| OPC-UA | `opcua_health_summary` | threshold classify (was `health_summary`¹) | R | low | {overall, counts, offenders[]} |
| OPC-UA | `opcua_anomaly_scan` | stddev outliers (was `anomaly_scan`¹) | R | low | {mean, stddev, outliers[]} |
| Modbus | `modbus_read_holding` | FC03 | R | low | {raw_registers, decoded[]} |
| Modbus | `modbus_read_input` | FC04 | R | low | {raw_registers, decoded[]} |
| Modbus | `modbus_read_coils` | FC01 | R | low | {bits[]} |
| Modbus | `modbus_read_discrete` | FC02 | R | low | {bits[]} |
| Modbus | `modbus_detect_byte_order` | byte/word-order auto-detect | R | low | {best_order, candidates[]} |
| Modbus | `modbus_list_templates` | vendor register templates | R | low | {templates[]} |
| Modbus | `modbus_apply_template` | decode block via template | R | low | {values:{name: engineering_value}} |
| Modbus | `modbus_health_summary` | threshold classify | R | low | {overall, counts, offenders[]} |
| S7comm | `s7_cpu_info` | CPU id + run/stop | R | low | {cpu_status, cpu_info} |
| S7comm | `s7_read_area` | read DB/M/I/Q | R | low | {items:[{address, value}]} |
| S7comm | `s7_read_db` | read data block | R | low | {items:[{address, value}]} |
| S7comm | `s7_read_many` | batch addresses | R | low | {items:[{address, value}]} |
| S7comm | `s7_write_db` | write data block | **W** | **high/MOC** | {before, written, _undo_id} |
| Mitsubishi MC | `mc_cpu_status` | CPU type | R | low | {cpu_type, cpu_code} |
| Mitsubishi MC | `mc_read_words` | word devices | R | low | {words[]} |
| Mitsubishi MC | `mc_read_bits` | bit devices | R | low | {bits[]} |
| Mitsubishi MC | `mc_read_many` | random read | R | low | {words[], dwords[]} |
| Mitsubishi MC | `mc_write_words` | write words | **W** | **high/MOC** | {before, written, _undo_id} |
| Omron FINS | `fins_cpu_info` | controller data read (0501) | R | low | {controller_model, controller_version} |
| Omron FINS | `fins_cpu_status` | controller status (0601) | R | low | {run_mode, status} |
| Omron FINS | `fins_read_words` | memory-area word read (DM/CIO/W/H/A/EM) | R | low | {words[]} |
| Omron FINS | `fins_read_bits` | memory-area bit read | R | low | {bits[]} |
| Omron FINS | `fins_read_many` | batch reads | R | low | {items[]} |
| Omron FINS | `fins_write_words` | memory-area write | **W** | **high/MOC** | {before, written, _undo_id} |
| MTConnect | `mtconnect_probe` | device model | R | low | {devices:[{components:[{data_items}]}]} |
| MTConnect | `mtconnect_current` | latest values | R | low | {observations[]} |
| MTConnect | `mtconnect_sample` | bounded stream | R | low | {observations[]} |
| MTConnect | `mtconnect_assets` | assets | R | low | {assets[]} |
| MTConnect | `mtconnect_oee_snapshot` | OEE inputs | R | low | {availability, execution, verdict} |
| MQTT/Sparkplug | `mqtt_read_topic` | bounded read | R | low | {messages:[{topic, payload}]} |
| MQTT/Sparkplug | `sparkplug_subscribe_sample` | bounded SpB sample (full decode) | R | low | {samples:[{sparkplug, payload:{metrics[]}}], seq_gap_count} |
| MQTT/Sparkplug | `sparkplug_decode_payload` | decode raw SpB payload | R | low | {metrics:[{name, alias, datatype, value, is_historical}]} |
| MQTT/Sparkplug | `sparkplug_node_list` | node discovery + state | R | low | {nodes:[{group_id, edge_node_id, online, devices}], primary_hosts[]} |
| MQTT/Sparkplug | `uns_browse` | topic-tree browse | R | low | {topics[], tree{}} |
| MQTT/Sparkplug | `uns_topic_audit` | UNS naming + sprawl governance | R | low | {verdict, sprawl_findings, findings{casing_collisions[], scattered_leaves[], …}} |
| MQTT/Sparkplug | `uns_schema_drift` | Sparkplug schema-drift (baseline vs current) | R | low | {verdict (none/additive/breaking), node_changes[]} |
| MQTT/Sparkplug | `uns_live_audit` | live UNS audit (bounded broker sample) | R | low | {verdict, findings{}} |
| MQTT/Sparkplug | `sparkplug_live_schema` | live NBIRTH schema snapshot | R | low | {nodes[], metrics[]} |
| MQTT/Sparkplug | `uns_live_drift` | live drift vs stored baseline | R | low | {verdict, node_changes[]} |
| MQTT/Sparkplug | `mqtt_publish` | publish/command | **W** | **high/MOC** | {published_bytes, applied} |
| EtherNet/IP | `eip_controller_info` | Logix controller id | R | low | {controller:{vendor, product_name, revision, serial}} |
| EtherNet/IP | `eip_list_tags` | tag discovery | R | low | {tag_count, tags:[{name, data_type, structure}]} |
| EtherNet/IP | `eip_read_tag` | read one tag/array | R | low | {tag, value, type, good} |
| EtherNet/IP | `eip_read_many` | batch read | R | low | {items:[{tag, value, type}]} |
| EtherNet/IP | `eip_write_tag` | write tag | **W** | **high/MOC** | {before, written, _undo_id} |
| Diagnostics | `diagnose_dataflow` | localize no-data | R | low | {verdict, diagnosis, hops[]} |
| Diagnostics | `alarm_bad_actors` | ISA-18.2 flood | R | low | {flood_verdict, top_offenders[]} |
| Diagnostics | `tag_health` | offender ranking | R | low | {overall, offenders[]} |
| Diagnostics | `historian_health` | gap/flatline | R | low | {verdict, gaps[]} |
| Diagnostics | `subscription_health` | sequenced-feed loss/reorder/overload | R | low | {verdict, missed_count, overloaded_channels[]} |
| Diagnostics | `downtime_root_cause` | AI downtime RCA copilot (cited, advisory) | R | low | {verdict, primary_cause, hypotheses:[{cause, confidence, evidence[]}]} |
| Diagnostics | `downtime_root_cause_live` | RCA copilot that gathers its own live evidence | R | low | {…downtime_root_cause…, collected_evidence} |
| Diagnostics | `learn_cause_weights` | learn per-site RCA cause weights from labeled incidents | R | low | {cause_weights{}, rationale} |
| Diagnostics | `data_quality_scorecard` | fleet data-trust rollup | R | low | {fleet_score, fleet_status, issue_breakdown, worst_tags[], endpoints[]} |
| Diagnostics | `data_quality_fleet_rollup` | cross-endpoint fleet view | R | low | {fleet_score, endpoints[]} |
| Diagnostics | `heartbeat_health` | heartbeat/watchdog liveness | R | low | {alive, distinct_transitions, longest_stall_s, reason} |
| Alarm (ISA-18.2) | `alarm_flood_analysis` | flood episodes / chattering / stale / summary | R | low | {episodes[], chattering[], stale[], summary{}} |
| Alarm (ISA-18.2) | `alarm_rationalization_worksheet` | CSV-exportable rationalization rows | R | low | {rows[], csv_path?} |
| Baseline | `baseline_learn` | conservative change-log baseline (refuses thin history) | R | low | {band{p1,p99,median,mad} \| insufficient_data} |
| Baseline | `baseline_check` | silent-by-default violation check | R | low | {status, violations[] (cited)} |
| Baseline | `baseline_record_change` | record operator change (restarts learning) | R | low | {recorded, change_point} |
| Baseline | `baseline_status` | no_baseline / learning / ok / violation | R | low | {status, window} |
| Historian | `historian_query` | read history back out of sqlite/TDengine/IoTDB | R | low | {rows[], truncated} |
| Historian | `historian_coverage` | per-tag row counts + first/last ts | R | low | {tags:[{tag, rows, first, last}]} |
| PLC program | `plc_program_outline` | structure of exported ST/AWL/L5X program | R | low | {blocks[], call_graph, timers[]} |
| PLC program | `plc_program_xref` | symbol/address cross-reference (cited lines) | R | low | {sites:[{kind, source_file, line, quote}]} |
| PLC program | `plc_program_section` | one named block's source (≤200 lines) | R | low | {text, source_file} |
| Export | `export_data` | export local store → CSV/SQLite/Parquet | R | low | {path, row_count, preview[]} |
| Analytics | `oee_compute` | OEE = A×P×Q | R | low | {availability, performance, quality, oee, oee_pct} |
| Analytics | `downtime_events` | stoppage detect + categorize | R | low | {event_count, total_downtime_s, by_category, events[]} |
| Analytics | `oee_multidim` | OEE machine×part×shift | R | low | {matrix[], worst_performers[], mean_oee} |
| Analytics | `asset_inventory` | active fingerprint | R | low | {assets:[{protocol, vendor, model, firmware, reachable}]} |
| Analytics | `cross_protocol_asset_model` | merge discovered tags into one asset model | R | low | {assets[], tag_count} |
| Analytics | `adopt_alias_map` / `diff_alias_map` | tag alias-map adopt/diff | R | low | {aliases{}, changes[]} |
| Analytics | `monitor_changes` | bounded change-of-value | R | low | {change_count, changes:[{value, previous, wall_clock}]} |
| EtherCAT | `ethercat_master_state` | master/WKC + slave count | R | low | {master_state, expected_working_counter, slaves_found, slaves_expected} |
| EtherCAT | `ethercat_slaves` | bus scan | R | low | {slave_count, slaves:[{index, name, vendor_id, product_code, state}]} |
| EtherCAT | `ethercat_slave_info` | slave detail | R | low | {sync_managers[], fmmus[], object_dictionary[], input_bytes} |
| EtherCAT | `ethercat_read_sdo` | CoE SDO upload | R | low | {index, byte_length, hex, as_uint} |
| EtherCAT | `ethercat_read_pdo` | input PDO snapshot | R | low | {working_counter, input_hex, input_byte_length} |
| EtherCAT | `ethercat_write_sdo` | CoE SDO download | **W** | **high/MOC** | {before, written, applied} |
| EtherCAT | `ethercat_set_state` | AL-state transition | **W** | **high/MOC** | {before, requested, reached, applied} |
| PROFINET | `profinet_discover` | DCP IdentifyAll (segment-wide) | R | low | {station_count, stations:[{name_of_station, mac, ip, vendor_id, device_roles[]}]} |
| PROFINET | `profinet_identify_station` | identify by name-of-station | R | low | {found, name_of_station, mac, ip, device_family} |
| PROFINET | `profinet_station_params` | targeted DCP Get (by MAC) | R | low | {found, name_of_station, ip, netmask, gateway} |
| PROFINET | `profinet_asset_inventory` | DCP asset register | R | low | {asset_count, io_controller_count, assets[]} |
| PROFINET | `profinet_dcp_set` | DCP Set (station name / IP suite) | **W** | **high/MOC** | {before, applied, _undo_id} |
| SECS/GEM | `secsgem_equipment_status` | GEM link + identity (S1F1/F2) | R | low | {communication_state, are_you_there} |
| SECS/GEM | `secsgem_list_status_variables` | SVID namelist (S1F11/F12) | R | low | {count, status_variables[]} |
| SECS/GEM | `secsgem_read_status_variables` | SVID values (S1F3/F4) | R | low | {svids, values[]} |
| SECS/GEM | `secsgem_list_equipment_constants` | ECID namelist (S2F29/F30) | R | low | {count, equipment_constants[]} |
| SECS/GEM | `secsgem_read_equipment_constants` | ECID values (S2F13/F14) | R | low | {ecids, values[]} |
| SECS/GEM | `secsgem_list_alarms` | alarm list (S5F5/F6) | R | low | {count, alarms[]} |
| SECS/GEM | `secsgem_list_process_programs` | PPID directory (S7F19/F20) | R | low | {count, process_programs[]} |
| BACnet (building) | `bacnet_discover` | Who-Is device discovery | R | low | {device_count, devices:[{device_id, address}]} |
| BACnet (building) | `bacnet_object_list` | a device's objects | R | low | {object_count, objects:[{object_type, instance}]} |
| BACnet (building) | `bacnet_read_property` | one object property | R | low | {object_type, instance, property, value} |
| BACnet (building) | `bacnet_read_points` | all present-values (HVAC snapshot) | R | low | {point_count, points:[{object_type, instance, present_value}]} |
| BACnet (building) | `bacnet_cov_subscribe` | bounded COV capture (always unsubscribes) | R | low | {notifications[], terminated_reason} |
| BACnet (building) | `bacnet_read_trend_log` | TrendLog readRange (bounded) | R | low | {records:[{timestamp, value}]} |
| BACnet (building) | `bacnet_write_property` | present-value write (priority) | **W** | **high/MOC** | {before, written, _undo_id} |
| HART-IP (process) | `hart_device_identity` | cmd 0 identity | R | low | {manufacturer, device_type, revision} |
| HART-IP (process) | `hart_primary_variable` | cmd 1 PV | R | low | {value, unit} |
| HART-IP (process) | `hart_dynamic_variables` | cmd 3 PV/SV/TV/QV + loop current | R | low | {variables[], loop_current} |
| HART-IP (process) | `hart_burst_sample` | bounded burst-variable sampling | R | low | {samples[]} |
| IO-Link | `iolink_master_info` | master identity | R | low | {vendor, product, serial} |
| IO-Link | `iolink_ports` | ≤32-port sweep (mode/status/device id) | R | low | {ports[]} |
| IO-Link | `iolink_device_info` | per-port device identity | R | low | {vendor_id, device_id, product_name} |
| IO-Link | `iolink_read_pdin` | process-data-in (raw hex + bytes) | R | low | {hex, bytes[]} |
| IO-Link | `iolink_read_isdu` | ISDU acyclic parameter read | R | low | {index, subindex, value} |
| IO-Link | `iolink_scan` | master + all connected devices | R | low | {master{}, devices[]} |
| BAS (Metasys/Niagara) | `bas_point_list` | supervisory point directory | R | low | {point_count, points:[{id, name, type}]} |
| BAS (Metasys/Niagara) | `bas_point_read` | read one supervisory point | R | low | {point, value, unit, status} |
| BAS (Metasys/Niagara) | `bas_alarm_list` | active controller alarms | R | low | {alarm_count, alarms:[{id, priority, state}]} |
| BAS (Metasys/Niagara) | `bas_trend_read` | trend/history samples (bounded) | R | low | {records:[{timestamp, value}]} |
| BAS (Metasys/Niagara) | `bas_command` | supervisory command (default-OFF; **life-safety object denylist** refuses fire/smoke/egress/pressurization before any I/O) | **W** | **high/MOC** | {before, written, _undo_id} |
| Ignition | `ignition_gateway_status` | Gateway + module health | R | low | {state, version, modules:[{name, state}]} |
| Ignition | `ignition_tag_browse` | tag-tree browse | R | low | {tags[], tree{}} |
| Ignition | `ignition_tag_read` | current tag values | R | low | {values:[{path, value, quality, timestamp}]} |
| Ignition | `ignition_alarm_status` | active alarms | R | low | {alarm_count, alarms:[{path, priority, state}]} |
| Ignition | `ignition_tag_history` | tag-history query (bounded) | R | low | {rows:[{path, timestamp, value}]} |
| 信创 / compliance | `compliance_mapping` | 《工控网络安全防护指南》↔ iaiops | R | low | {pillars[], status_summary, controls:[{pillar, status, gap}]} |
| 信创 / compliance | `compliance_frameworks` | 等保 2.0 + IEC 62443 FR1–6 crosswalk | R | low | {controls:[{crosswalk}]} |
| 信创 / compliance | `compliance_dengbao_levels` | 等保 二级 baseline vs 三级 增量 | R | low | {pillars:[{l2, l3_delta, status}]} |
| 信创 / compliance | `compliance_report` | deliverable compliance report (md/html) | R | low | {markdown \| out_path} |
| 信创 / compliance | `compliance_evidence_bundle` | audit-evidence zip (hash-chain verified) | R | low | {bundle_path, manifest} |
| 信创 / historian | `historian_push` | push telemetry to sqlite/TDengine/IoTDB | R(→historian) | low | {sink, received, written, skipped_non_numeric} |
| Self | `protocols_supported` | capability map | R | low | {protocols[], diagnostics[], analytics[]} |

*(The energy protocols — IEC-104 / DNP3 / IEC-61850 — moved to [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy) in 0.8.0; their tool matrix lives in that repo.)*

**166 governed tools** = 156 read + 10 MOC-gated writes (`s7_write_db`, `mc_write_words`, `fins_write_words`, `mqtt_publish`, `eip_write_tag`, `ethercat_write_sdo`, `ethercat_set_state`, `profinet_dcp_set`, `bacnet_write_property`, `bas_command`). The read side now includes two vendor-REST **read-only** layers above the field protocols — a **BAS controller layer** (Metasys/Niagara, building edition) and an **Ignition Gateway MES/SCADA** layer (factory edition). ¹ The 156 reads include the two deprecated brain aliases `health_summary` / `anomaly_scan`, renamed to `opcua_health_summary` / `opcua_anomaly_scan` in 0.10.0 — **the old names are removed in 0.12.0**. Read-only per-edition tools load ONLY under their edition (see *per-edition tool modules* below), so a bare protocol / single-edition surface is smaller than this line-wide total. The table above is representative, not exhaustive; run `protocols_supported()` (or `iaiops protocols`) for the live map.

---

## Per-protocol reference

### OPC-UA
- **Versions/variants**: binary `opc.tcp://` via `asyncua` (sync facade). Security: **anonymous + username/password**. Certificate message security (Sign / SignAndEncrypt) = **roadmap, not validated**.
- **Connection params**: `endpoint_url`, `username` (password encrypted), `security_mode`, `security_policy`.
- **Not supported / planned**: cert security; real Alarms & Conditions event subscriptions (alarms are surfaced best-effort by browsing alarm-like boolean nodes).

### Modbus-TCP / Modbus-RTU
- **Versions/variants**: Modbus-TCP and **Modbus-RTU (serial RS-485/232)** via `pymodbus` (+ `pyserial`). Read function codes **FC01 (coils), FC02 (discrete), FC03 (holding), FC04 (input)**. Write FCs (**FC05/06/15/16**) = **not implemented** (read-only).
- **Connection params**: TCP — `host`, `port` (502), `unit_id`. RTU — `transport: rtu`, `serial_port` (e.g. `/dev/ttyUSB0`), `baudrate`, `unit_id`. Registers are untyped 16-bit words → `decode` hint (uint16/int16/uint32/int32/float32/raw); `modbus_detect_byte_order` auto-detects the byte/word order (AB/BA · ABCD/DCBA/BADC/CDAB) from hint values — pure logic, no extra device load.
- **Vendor register templates** (`modbus_list_templates` / `modbus_apply_template`): named register maps decoding a block into engineering values — energy meters (Eastron SDM630, Schneider PM5xxx, Carlo Gavazzi EM24), PV inverters (Huawei SUN2000, Growatt), Phoenix PLCnext process data, and water-industry templates (E+H Promag, Hach SC controller, generic dosing pump). Each template carries an explicit `待核实` caveat — no invented "verified" addresses.
- **Coverage**: many domestic 国产 PLCs (汇川 Inovance / 信捷 Xinje / 和利时 Hollysys / 台达 Delta) and any Modbus vendor. RTU framing is live-verified over a real serial link (socat PTY + pymodbus RTU server); specific physical RS-485 devices stay `待核实`.

### S7comm (Siemens + 仿西门子 国产)
- **Versions/variants**: `pyS7` (**pure-Python**, ISO-on-TCP / RFC1006 — no native `libsnap7`). **S7-300/400/1200/1500** and compatible clones. Memory areas **DB / M (merker) / I / Q**. No protocol auth (CPU gates via "Permit access with PUT/GET").
- **Connection params**: `host`, `port` (102), `rack`, `slot` (0/1 for 1200/1500; 0/2 common for 300/400).
- **Write**: `s7_write_db` = **high risk_tier, MOC, dry-run default**, captures BEFORE value + undo.
- **Not supported / planned**: optimized/symbolic DB access on 1500 with "optimized block access" can require absolute-addressing config on the CPU.

### Mitsubishi MC
- **Versions/variants**: `pymcprotocol` — **MC 3E frame (binary)** only. **1E / 4E frames = not supported.** PLC types **Q / L / QnA / iQ-R / iQ-L**. Devices: D/W/R (word), M/X/Y/B (bit).
- **Connection params**: `host`, `port` (5007 default; set to the module's open MC port), `plctype`.
- **Write**: `mc_write_words` = **high/MOC/dry-run default**, captures BEFORE + undo.

### Omron FINS (CS/CJ/CP/NX-via-FINS)
- **Versions/variants**: in-repo, **stdlib-only** FINS client (no third-party dependency — the `iaiops[fins]` extra pins nothing): 10-byte FINS header framing, **FINS/UDP** (default port 9600) and **FINS/TCP** (node-address handshake per Omron W342), SID matching, bounded response parsing, end-code table per W227/W342. Commands: 0101 memory-area read (words/bits over **DM/CIO/W/H/A/EM**), 0102 write, 0501 controller data read, 0601 controller status.
- **Connection params**: `host`, `port` (9600), `transport` (`udp` default / `tcp`), FINS network/node/unit addressing.
- **Write**: `fins_write_words` = **high/MOC/dry-run default**, captures BEFORE + undo; CLI double-confirm on `--apply`.
- **Validation**: verified against an in-repo mock FINS UDP/TCP responder (`tests/test_fins.py`); **live Omron PLC behaviour and banked-EM access stay `待核实`**.

### IO-Link (master JSON integration — read-only)
- **Versions/variants**: sensor-level visibility via the IO-Link **master's HTTP/JSON interface** (IO-Link consortium "JSON Integration"), both dialects selectable per endpoint via `flavor:` — `iotcore` (ifm IoT-Core POST envelope, default) and `rest` (plain-REST GET, Balluff/Turck-style). Reads: master identity, bounded ≤32-port sweep, per-port device identity, process-data-in (raw hex + bytes), ISDU acyclic parameter read. **NO write tools.** Bounded/size-capped HTTP (256 KiB response cap), schema-checked JSON with teaching errors. Reuses the MTConnect HTTP pin (`iaiops[iolink]` → `requests`).
- **Connection params**: master `host`/URL, `flavor`, `timeout_s`. `protocol: iolink`.
- **Validation**: in-process mock master in both flavors (`tests/test_iolink.py`); **live master datapoint paths stay `待核实`**.

### HART-IP (process instrumentation — read-only)
- **Versions/variants**: HART universal commands over **HART-IP UDP** (default, port 5094) or **TCP** (`transport: tcp`, length-delimited framing) via an in-tree transport; the HART command codec is verified vs `hart-protocol`. Tools: `hart_device_identity` (cmd 0), `hart_primary_variable` (cmd 1), `hart_dynamic_variables` (cmd 3, PV/SV/TV/QV + loop current), `hart_burst_sample` (bounded sampling of burst-published variables). **No write / device-specific commands exposed** (OT-dangerous on live instruments).
- **Connection params**: `host` (HART-IP server/gateway), `port` (5094), `transport` (udp default / tcp).
- **Validation**: TCP transport loopback-verified (in-process HART-IP server, real long-frame ACK through the real codec path); **live gateway behaviour and a true unsolicited burst subscription stay `待核实`**.

### MTConnect (ALL CNC machine tools)
- **Versions/variants**: agent **REST + XML** (`requests` + `xml.etree`), namespace-agnostic (parses MTConnect 1.x Devices/Streams/Assets schemas). Endpoints: `/probe`, `/current`, `/sample`, `/assets`. **Read-only by specification.** XML parsing is hardened (DTD/entity declarations rejected — XXE/billion-laughs defense).
- **Connection params**: `agent_url` (e.g. `http://host:5000`).
- **Not supported / planned**: MTConnect streaming (long-poll `interval=`); only bounded `count=` samples.

### MQTT / Sparkplug B / UNS
- **Versions/variants**: `paho-mqtt` — **MQTT 3.1.1 & 5**. Sparkplug B topic convention `spBv1.0/{group}/{type}/{edge}/[device]` (NBIRTH/DBIRTH/NDATA/DDATA/NDEATH/DDEATH/STATE). TLS + username/password supported.
- **Full Sparkplug B decode** (no optional extra): payloads are protobuf-decoded with a *vendored, byte-for-byte* copy of the official **Eclipse Tahu** `sparkplug_b.proto` generated module (depends only on `protobuf`). Per metric you get **name, alias** (resolved to its name via the BIRTH model), **datatype** (Int8…Int64/UInt…/Float/Double/Boolean/String/DateTime/Text/UUID/**DataSet**/Bytes/File/**Template**/PropertySet…), **value**, **timestamp**, and the **`is_historical` / `is_null`** flags. A **birth/death + seq model** tracks node/device **online** state (NBIRTH/DBIRTH ↔ NDEATH/DDEATH), builds the alias→name map from BIRTH, applies NDATA/DDATA by alias, and flags **`seq` gaps / out-of-order**. **Primary-host** awareness: `STATE/<host_id>` topics surface in `sparkplug_node_list`. `sparkplug_decode_payload` decodes a single raw payload (base64/hex) offline.
- **Connection params**: `host`/`broker`, `port` (1883 / 8883 TLS), `topic`, `use_tls`, `username` (password encrypted).
- **Command**: `mqtt_publish` = **high/MOC/dry-run default**; a published command has **no automatic inverse**.

### EtherNet/IP (Rockwell / Allen-Bradley)
- **Supported**: **ControlLogix / CompactLogix** (and GuardLogix) via **CIP / EtherNet-IP** using **`pycomm3`** (pure-Python — no native deps). **Tag-based**, symbolic access: read/write tags by name (`Conveyor.Speed`, `Array[3]`, `Program:Main.X`) and **discover the controller's tag list** at runtime (`eip_list_tags`, the headline feature). `eip_controller_info` reads the controller identity.
- **Connection params**: `host`, `slot` (0 for CompactLogix; the CPU slot for a ControlLogix chassis), `port` (44818). `protocol: ethernetip` (alias `eip`).
- **Write**: `eip_write_tag` = **high risk_tier, MOC, dry-run default**, captures BEFORE value + undo.
- **Not supported / planned**: **PLC-5 / SLC-500 (PCCC)** and **Micro800** are **not supported = roadmap** (Logix tag model only).

### EtherCAT (pysoem / SOEM fieldbus master)
- **Supported**: a **real EtherCAT master** via **`pysoem`** (the Python binding for the SOEM C stack). **CoE SDO read** (`ethercat_read_sdo`, acyclic mailbox upload) + **SDO write** (`ethercat_write_sdo`, download), **input PDO read** (`ethercat_read_pdo`, one bounded cyclic snapshot), **bus scan / slave enumeration** (`ethercat_slaves`, `ethercat_slave_info` — identity, SM/FMMU mapping, object-dictionary summary), **master/working-counter state** (`ethercat_master_state`), and **AL-state transitions** INIT↔PREOP↔SAFEOP↔OP (`ethercat_set_state`).
- **HARD REQUIREMENTS** (no way around them): **Linux**, **root or `CAP_NET_RAW`**, a **dedicated NIC** cabled to the bus, and **real EtherCAT slave hardware**. `pysoem` is an **OPTIONAL extra**: `pip install iaiops[ethercat]` — the base package installs and imports **without** it, and every EtherCAT tool then **degrades to a teaching error** (never crashes, never imports pysoem at module load).
- **NOT supported**: **no software simulator** exists (unlike OPC-UA / Modbus) — EtherCAT is **hardware-only** and **not testable in mock-only CI**; **macOS is unsupported**. **EoE / FoE / SoE** mailbox protocols and full PDO-mapping decode/expansion = **roadmap**.
- **Connection params**: `nic` (the dedicated interface name, e.g. `eth1`; alias `interface`), optional `expected_slaves` (a sanity check vs the bus scan). `protocol: ethercat`.
- **Operations matrix**:

  | Tool | Op | R/W | risk | Capture/notes |
  |------|----|:---:|:----:|---------------|
  | `ethercat_master_state` | master + WKC state, slave count | R | low | expected vs found |
  | `ethercat_slaves` | bus scan / enumerate | R | low | index/vendor/product/rev/addr/AL-state |
  | `ethercat_slave_info` | one-slave detail | R | low | SM/FMMU + OD summary |
  | `ethercat_read_sdo` | CoE SDO upload | R | low | hex + uint interpretation |
  | `ethercat_read_pdo` | input PDO snapshot | R | low | single cycle, never loops |
  | `ethercat_write_sdo` | CoE SDO download | **W** | **high/MOC** | before-value (SDO read-back) + undo |
  | `ethercat_set_state` | AL-state transition | **W** | **high/MOC** | before-state + undo; **can start/stop motion** |

- **Write/state safety**: `ethercat_write_sdo` (hex little-endian bytes) and `ethercat_set_state` are **high risk_tier, MOC, dry-run by default**, capture the BEFORE value/state for undo, and need a CLI double-confirm. **Changing EtherCAT state can START or STOP machine motion** — treat with extreme care. 未经授权勿对生产控制系统写入.

### PROFINET (DCP discovery / identify + gated DCP Set)
- **Supported**: layer-2 **PROFINET-DCP** via **`pnio-dcp`** — **`profinet_discover`** (DCP IdentifyAll: one broadcast surfaces *every* station on the segment — name-of-station, MAC, IP, vendor/device id, role — closer to passive discovery than a per-device fingerprint), **`profinet_identify_station`** (by name-of-station), **`profinet_station_params`** (targeted DCP Get by MAC → name + IP suite), and **`profinet_asset_inventory`** (a register with IO-controller vs IO-device role decoding).
- **Write**: **`profinet_dcp_set`** re-addresses one station (name-of-station and/or IP suite, by MAC) — **high risk_tier, MOC, dry-run default**, captures the BEFORE addressing + undo descriptor. Re-addressing a live station **can disrupt its IO connection**.
- **Scope (deliberate)**: **no RT cyclic process data** (that needs an IO-controller/IO-device stack and hard real-time — out of scope and unsafe to tap); the **blink / factory-reset** DCP services stay unexposed.
- **HARD REQUIREMENTS**: **raw-socket access** (root / admin / `CAP_NET_RAW`) on the **NIC on the PROFINET subnet**. `pnio-dcp` is an **OPTIONAL extra**: `pip install iaiops[profinet]` — the base package installs/imports **without** it, and every tool then **degrades to a teaching error**.
- **Connection params**: `host` — **THIS machine's IP** on the PROFINET subnet (the DCP broadcast goes out on it). `protocol: profinet`.
- **Preview caveat**: validated against a **mocked `pnio-dcp` DCP** — **not** verified against live PROFINET devices yet.

### Energy edition (electrical substation / utility telecontrol) → `iaiops-energy`
The energy vertical — **IEC 60870-5-104 / DNP3 / IEC 61850 MMS** read-only monitoring for substation RTUs/IEDs — **moved to its own package in 0.8.0**: [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy) (`pip install iaiops-energy`), built on `iaiops.core` (shared governance / brain / runtime). Its protocol reference, support matrix, and validation status live in that repo.

### Building edition (facility / HVAC / 厂务)
The **building** vertical adds **BACnet/IP** (ASHRAE 135) — the dominant building-automation protocol for HVAC, lighting, metering, and facility plant. Install with `pip install iaiops[building]` and expose with `IAIOPS_MCP=building` (bundle: bacnet + modbus + opcua + iolink).
- **BACnet/IP** (`BAC0` over bacpypes3): `bacnet_discover` (Who-Is device discovery), `bacnet_object_list` (a device's objects), `bacnet_read_property` (one object property), `bacnet_read_points` (present-value of all analog/binary/multistate points — the HVAC snapshot), `bacnet_cov_subscribe` (bounded change-of-value capture — capped by count AND wall-clock, always unsubscribes), `bacnet_read_trend_log` (TrendLog buffered records via one bounded readRange). Config: `host` = THIS machine's BACnet/IP interface (`ip` or `ip/mask`) / `port` (47808).
- **Write**: `bacnet_write_property` (present-value at a BACnet priority 1..16, or relinquish) = **high risk_tier, MOC, dry-run default**, BEFORE-value read-back + undo. Overriding a live building-control point **can move real HVAC/plant**.
- **Validation**: the **read path is verified** against a real bacpypes3 virtual BACnet/IP device through the actual async BAC0 stack (`tests/test_bacnet_live.py`); **COV / trend-log / writes on live HVAC gear stay `待核实`**.

### Water treatment edition (水处理)
`IAIOPS_MCP=water` (or `iaiops-mcp-water`, `pip install iaiops[water]`) exposes **modbus + opcua + hart** + the brain — the protocol set waterworks / wastewater plants actually run. Adds water-domain tag semantics (溶解氧 DO / ORP / 余氯 chlorine / 氨氮 ammonia / TSS/MLSS / 跨膜压差 TMP / UV / 加药 dosing / 曝气 aeration) and water-industry Modbus templates (E+H Promag, Hach SC controller, generic dosing pump — all with explicit `待核实` caveats).

### Warehouse / intralogistics edition (仓储 / 物料搬运)
`IAIOPS_MCP=warehouse` (or `iaiops-mcp-warehouse`, `pip install iaiops[warehouse]`) exposes **eip + profinet + modbus + opcua + sparkplug** + the brain — conveyor & sorter drives over EtherNet/IP (Rockwell) and Profinet (Siemens), VFD / energy meters over Modbus (`conveyor_vfd` / `agv_battery` templates), WMS/WCS gateways over OPC-UA, and AMR/IoT telemetry over MQTT-Sparkplug. Edition tools (read-only, advisory): `line_bottleneck` (Theory-of-Constraints throughput bottleneck across stations) + `sortation_health`. PdM (`pdm_forecast`), `downtime_triage` and OEE are reused as-is.

### Clinical-facility edition (医疗设施)
`IAIOPS_MCP=clinical` (or `iaiops-mcp-clinical`, `pip install iaiops[clinical]`) exposes **bacnet + modbus + opcua** + the brain — hospital facilities as a distinct patient-safety vertical over the building brain. Edition tools (read-only, advisory): `isolation_room_check` (负压/正压 isolation-room pressurization), `medical_gas_check` (medical-gas alarm-panel safety), `or_environment_check` (OR temperature / humidity / pressure envelope). BACnet BMS + Modbus gas-alarm panels + OPC-UA plant SCADA.

### Renewables edition (光伏 / 风电)
`IAIOPS_MCP=renewables` (or `iaiops-mcp-renewables`, `pip install iaiops[renewables]`) exposes **modbus + opcua + sparkplug** + the brain — PV inverters (SUN2000 / Growatt templates) + wind-turbine controllers over Modbus, OPC-UA plant SCADA, and MQTT-Sparkplug telemetry. Edition tool (read-only, advisory): `pv_performance` (PV string performance vs expectation). Device-level monitoring + PdM via baseline / RCA.

### PLCnext packaging edition (Phoenix Contact vPLC)
`IAIOPS_MCP=plcnext` (or `iaiops-mcp-plcnext`, `pip install iaiops[plcnext]`) exposes **opcua + modbus** + the brain — the Phoenix Contact PLCnext virtualized PLC reached over its built-in OPC-UA server (`opc.tcp` 4840, `Arp.Plc.Eclr` address space) + Modbus-TCP process-data server; **no new connector**. Route-verified in-process; live PLCnext hardware reads stay `待核实` (see validation status above).

### 信创 / China entry (offline · 国产 TSDB · compliance)
For 自主可控 / 信创 deployments — see **[docs/CHINA.md](docs/CHINA.md)** for the full guide.
- **Air-gapped install**: pure-Python core + per-protocol optional extras → install from a local wheelhouse with `pip install --no-index --find-links ./wheelhouse "iaiops[...]"`; secrets stay local (encrypted store), no cloud KMS.
- **National TSDB historian sink** (`historian_push`, CLI `iaiops historian push`): write collected telemetry to **TDengine** (`iaiops[tdengine]`) or **Apache IoTDB** (`iaiops[iotdb]`) — domestic, controllable; we don't build our own store or bind InfluxDB. *Data egress to the operator's own historian, not a control write.*
- **Compliance mapping** (`compliance_mapping`, CLI `iaiops compliance`): an honest 《工控系统网络安全防护指南》 ↔ iaiops self-assessment across 分区隔离 / 可审计 / 双向认证 / 最小权限 / 数据保护 / 自主可控, with per-control status (addressed / partial / 待核实) and the named gap.
- **国产 PLC**: 汇川 / 台达 / 信捷 over the existing **Modbus-TCP / S7** connectors.
- **⚠️ 待核实**: 国产 OS (麒麟/统信) · 芯 (鲲鹏/海光) · PLC validation and the TSDB write paths are documented but **not yet hardware-verified** — see the validation matrix in docs/CHINA.md.

### OEE / downtime analytics (cross-protocol, read-only)
- `oee_compute` — **OEE = Availability × Performance × Quality** from production inputs (planned time, run time, ideal cycle, total/good counts). Each factor is reported **raw + clamped to [0,1]**; a `capped` performance >1.0 flags an optimistic ideal cycle.
- `downtime_events` — auto-detects **running→stopped transitions** in a `{timestamp, state}` series and produces stoppage events with durations, **categorized** (changeover / material / mechanical / quality / break / unknown, by keyword heuristics or a `{state: category}` override).
- `oee_multidim` — aggregates OEE across **machine × part × shift** (or any dimensions) from labelled records → the matrix + worst performers.
- Operate over **provided/collected inputs** (fully testable without a plant). `mtconnect_oee_snapshot` surfaces the live MTConnect availability/execution inputs that feed these.

### Active asset inventory / fingerprint (read-only)
- `asset_inventory` — for each configured (or named) endpoint, **actively connects** with our own protocol client and reads its **identity** call (S7 `s7_cpu_info`, EtherNet/IP `eip_controller_info`, OPC-UA server build info, Modbus **Device Identification FC43/0x2B**, Mitsubishi CPU type, MTConnect device model), aggregating **vendor / model / firmware / serial / reachable / last_seen** into an asset register.
- **Honest scope (IEC 62443-flavored)**: this is **ACTIVE fingerprinting via our client connections**, **NOT** passive SPAN/tap discovery — it only finds devices we are configured to reach and adds light load to each. **Passive, traffic-mirroring discovery is roadmap.**

### OPC-UA Historical Access (HDA)
- `opcua_read_history` — reads stored historical values for a node over a `[start,end]` ISO-8601 window via the server's **HistoryRead** service (`asyncua` `read_raw_history`), **bounded** by `max_points` (≤2000). Returns `{supported:false, note}` **gracefully** when the server does not historize the node (no crash). Read-only.

### Change-of-value (CoV) monitor
- `monitor_changes` — bounded **deadband report**: polls a point and returns **only the value CHANGES** (with timestamps), not every sample. Works over **OPC-UA / Modbus / S7 / Mitsubishi MC / EtherNet-IP**. **Never an infinite loop** — hard-capped by both `duration_s` (≤120) and `max_changes` (≤500). Read-only.

### Cross-protocol brain — 0.9/0.10 additions (all read-only)
- **Conservative baseline learning** (`baseline_learn/check/record_change/status`, CLI `iaiops baseline …`) — a **change-log baseline, explicitly NOT black-box anomaly detection**: robust p1/p99 + median/MAD band over the local history, **refuses thin history** (<100 samples or <24h) with an explicit `insufficient_data` verdict, restarts at recorded operator changes, and is **silent by default** — a violation needs >3×MAD beyond the band AND ≥3 consecutive samples, and every violation cites its baseline window and offending samples.
- **Historian READ integration** (`historian_query` / `historian_coverage`, CLI `iaiops historian query|coverage`) — query history back out of the sqlite/TDengine/IoTDB sinks; an optional per-site `historian:` config block lets the RCA copilot pull the **2h pre-incident window** as one more cited evidence class (strictly additive — without the config, RCA output is byte-identical, test-proven).
- **Legacy PLC program explainer** (`plc_program_outline/xref/section`, CLI `iaiops program …`) — structural extraction over **exported** program files (Siemens SCL/ST `.scl`/`.st`, AWL/STL `.awl`, Rockwell Studio 5000 `.L5X` — never a live PLC upload); every element carries `source_file` + line (rung for L5X) so the explaining agent must cite real locations. XXE-hardened, ≤5 MB, extension allowlist.
- **ISA-18.2 alarm flood deep-dive** (`alarm_flood_analysis` / `alarm_rationalization_worksheet`, CLI `iaiops diag alarm-flood|alarm-worksheet`) — flood *episodes* (≥10 alarms/10 min), chattering, stale/standing (>24h), percent-time-in-flood vs target, and a CSV-exportable rationalization worksheet; over injected events or a live OPC-UA active-condition scan.
- **Open-format export + metrics bridge** — `iaiops export csv|sqlite|parquet` (from the local SQLite sink; Parquet via `iaiops[export]`) / MCP `export_data`; `iaiops metrics serve --port 9184` exposes Prometheus **`/metrics`** (latest tag values + counters, binds 127.0.0.1 by default) — Grafana recipe in `docs/GRAFANA.md`.
- **Compliance deliverables** — `iaiops compliance report` (等保 2.0 L2/L3 status + IEC 62443 FR1–6 crosswalk + honest gap list, md/html) and `iaiops compliance evidence` (audit-evidence zip with hash-chain verification + manifest); MCP `compliance_report` / `compliance_evidence_bundle`. Onboarding aids, 非认证.

### Cross-protocol brain & editions — 0.11/0.12 additions (all read-only)
- **Downtime triage copilot** (`downtime_triage`) — composes **alarm cascade + RCA verdict + PdM precursors** into one triage and cross-checks whether the first-out alarm agrees with the diagnosed cause; advisory, cite-first (builds on the earlier `alarm_cascade` first-out reconstruction and `pdm_forecast` time-to-threshold early-warning).
- **Legacy-PLC maintainability** (`plc_program_visibility`) — a risk/maintainability read over an **exported** ST/AWL/L5X program (size, block count, xref density, undocumented sections), never a live upload — pairs with the `plc_program_outline/xref/section` explainer.
- **Per-edition tool modules** (`EDITION_MODULES` in `mcp_server/profiles.py`) — a named edition can carry its own `@mcp.tool` group that loads **only when that edition is selected** — never for a bare protocol key and never in the always-on brain, so edition-specific tools stay off other surfaces and don't inflate the base. Every edition tool is **read-only, cite-first, advisory**:
  - **warehouse** — `line_bottleneck` (Theory-of-Constraints throughput bottleneck) + `sortation_health`
  - **clinical** — `isolation_room_check` (负压隔离病房 pressurization) + `medical_gas_check` + `or_environment_check`
  - **building** — `economizer_check` (AHU economizer FDD) + `zone_comfort`
  - **process** — `control_loop_health` (PID oscillation/offset/saturation) + `heat_exchanger_fouling`
  - **fab** — `spc_check` (SPC control-chart rules) + `defect_pareto`
  - **factory** — `changeover_analysis` (SMED)
  - **water** — `disinfection_ct` + `water_quality_compliance`
  - **renewables** — `pv_performance` (PV string performance)
- **Agent skills** — the repo ships a router skill (`skills/iaiops`) plus **nine** per-edition skills (`iaiops-fab` / `iaiops-factory` / `iaiops-process` / `iaiops-building` / `iaiops-water` / `iaiops-warehouse` / `iaiops-clinical` / `iaiops-renewables` / `iaiops-plcnext`) that route an agent to the right MCP server and document the tool surface.

### Deployment & ecosystem fit (edge-native / Margo)
iaiops is designed to ride on a hardened, centrally-managed **edge host** as a portable, governed
**edge application** — not to own the host or the fleet manager. It maps naturally onto the
[Margo](https://margo.org/) edge-interoperability roles: the *host/device* is the immutable edge OS,
a *compliant orchestrator* places workloads by desired-state, and **iaiops is the OT-domain
application** — read-first tap + cross-protocol RCA, exposed as governed MCP tools, with an optional
**on-box LLM brain** for a fully air-gapped diagnostic path (data never leaves the plant).
> **Honest status:** iaiops is a natural Margo edge application but is **NOT Margo-compliant yet** —
> a container image + application description + a published conformance-toolkit result are roadmap
> `⏳` (see **[docs/MARGO-ALIGNMENT.md](docs/MARGO-ALIGNMENT.md)** and `docs/ROADMAP.md`). No material
> claims *Margo-compliant* until that test result exists.

A container + application-description **skeleton** lives in **[`deploy/margo/`](deploy/margo/)**
(hardened Dockerfile · compose · `待核实`-marked app descriptor); per-host distribution overlays
that reuse it live under **[`deploy/`](deploy/)** (one folder per candidate edge host).

---

## Install

Protocol client libraries are **optional extras** — install only the 1–2 protocols a site
actually runs (every protocol library is imported lazily; the base package installs and
imports without any of them, and a call to a not-installed protocol returns a teaching
error pointing at the right extra):

```bash
uv tool install "iaiops[opcua,modbus]"   # just the protocols you need
# or one per site:  pip install "iaiops[s7]"   ·   everything:  pip install "iaiops[all]"
# or a per-industry edition bundle:        pip install "iaiops[fab]"

iaiops init                 # interactive: add endpoints, store passwords encrypted
iaiops doctor               # config + per-protocol connectivity probe (point at simulators)
iaiops protocols            # the capability map
```

Protocol extras: `opcua` · `modbus` · `s7` · `mc` · `fins` (stdlib — pins nothing) · `eip` · `mtconnect` · `sparkplug` · `secsgem` · `ethercat` · `profinet` · `bacnet` · `hart` · `iolink` · plus `tdengine` · `iotdb` · `influxdb` (historian sinks) · `nats` (stream egress) · `ollama` (on-box LLM narration) · `export` (Parquet) · `all` (every pip-installable connector).

> **Adapter belt** (`docs/ADAPTERS.md`): iaiops is a small neutral core (`ingress → normalize/govern/RCA → egress`) with pluggable, lazily-imported adapters — bind no store/bus/host/model, install only what a site runs. The RCA core is deterministic + cited, **not a black box** (`docs/RCA.md`); footprint is small by design (`docs/FOOTPRINT.md`).

**Edition bundles** (match the same-named `IAIOPS_MCP` profiles — install the protocols a vertical runs):
`fab` (secsgem + opcua + s7 + modbus) · `factory` (the discrete-manufacturing set: opcua + modbus + s7 + mc + fins + eip + mtconnect + sparkplug + ethercat + profinet + iolink) · `process` (opcua + modbus + hart) · `building` (bacnet + modbus + opcua + iolink) · `water` (modbus + opcua + hart) · `renewables` (光伏/风电: modbus + opcua + sparkplug — PV inverters (SUN2000/Growatt) + wind turbines + plant SCADA; device-level monitoring + PdM via baseline/RCA) · `plcnext` (opcua + modbus). The grid/substation energy bundle (IEC-104/DNP3/61850) ships in [`iaiops-energy`](https://github.com/industrial-aiops/industrial-aiops-energy).

### Master password
Secrets (per-endpoint passwords, MQTT credentials) are **never** stored in plaintext — they live in `~/.iaiops/secrets.enc` (Fernet + scrypt). Export `IAIOPS_MASTER_PASSWORD` so the MCP server/CLI can unlock non-interactively:
```bash
export IAIOPS_MASTER_PASSWORD='…'
```

### Example `~/.iaiops/config.yaml` (one block per protocol)
```yaml
endpoints:
  - name: line1
    protocol: opcua
    endpoint_url: opc.tcp://plc.lan:4840
    # username: operator           # password stored encrypted via init/secret set
    tags:
      - { ref: "ns=2;i=5", label: temp, warn_high: 70, alarm_high: 90 }
  - name: plc2
    protocol: modbus
    host: 10.0.0.5
    port: 502
    unit_id: 1
  - name: press1
    protocol: s7
    host: 10.0.0.6
    rack: 0
    slot: 1                        # S7-1200/1500
  - name: cell3
    protocol: mc
    host: 10.0.0.7
    port: 5007
    plctype: iQ-R
  - name: meter1
    protocol: modbus                 # Modbus-RTU (serial): set transport + serial_port
    transport: rtu
    serial_port: /dev/ttyUSB0
    baudrate: 9600
    unit_id: 1
  - name: omron1
    protocol: fins                   # Omron FINS (UDP default; transport: tcp for FINS/TCP)
    host: 10.0.0.11
    port: 9600
  - name: xmtr1
    protocol: hart                   # HART-IP gateway (read-only; udp default / transport: tcp)
    host: 10.0.0.20
  - name: iolm1
    protocol: iolink                 # IO-Link master JSON integration (read-only)
    host: 10.0.0.21
    flavor: iotcore                  # ifm IoT-Core (default) | rest (Balluff/Turck-style)
  - name: vmc1
    protocol: mtconnect
    agent_url: http://10.0.0.8:5000
  - name: uns
    protocol: mqtt
    host: broker.lan
    use_tls: true                  # → port 8883
    topic: spBv1.0/#
    # username: edge1              # password stored encrypted
  - name: cell5
    protocol: ethernetip           # alias: eip
    host: 10.0.0.9
    slot: 0                        # 0 for CompactLogix; CPU slot for ControlLogix
  - name: bus1
    protocol: ethercat             # Linux + root/CAP_NET_RAW + pip install iaiops[ethercat]
    nic: eth1                      # dedicated NIC cabled to the EtherCAT bus
    expected_slaves: 8             # optional sanity check vs the bus scan
```

### `iaiops init` walkthrough (per protocol)
```
$ iaiops init
Step 1 — master password: ********
Step 2 — add an endpoint
  Endpoint name (e.g. line1): press1
  Protocol ('opcua','modbus','s7','mc','mtconnect','mqtt') [opcua]: s7
  S7 PLC host (IP/FQDN): 10.0.0.6
  Port [102]: 102
  Rack (0 for S7-1200/1500) [0]: 0
  Slot (1 for S7-1200/1500, 2 for S7-300/400) [1]: 1
✓ Saved endpoint 'press1'.
```
(MQTT prompts add TLS/topic/username; MTConnect prompts for `agent_url`; EtherCAT prompts for the `nic` + `expected_slaves` and warns about the Linux/root/NIC/optional-extra requirement; OPC-UA/MQTT prompt for a hidden password stored encrypted.)

### Test against a simulator (per protocol)
- **OPC-UA** — an `asyncua` demo server (the test suite runs a real in-process one).
- **Modbus** — ModbusPal or a `pymodbus` server simulator.
- **S7** — a pyS7/snap7 S7 server sim (Snap7 server) on `:102`.
- **MTConnect** — the public MTConnect demo agent, or a local agent.
- **MQTT** — a local `mosquitto` broker (+ a Sparkplug edge for SpB topics).
- **Mitsubishi MC** — GX Simulator / an MC 3E server sim.
- **EtherNet/IP** — a pycomm3-compatible CIP/Logix simulator (or a spare CompactLogix).
- **Omron FINS** — the in-repo mock FINS UDP/TCP responder (`tests/test_fins.py`) or a spare CP/CJ PLC.
- **IO-Link** — the in-process mock master (`tests/test_iolink.py`, both JSON dialects) or any ifm/Balluff/Turck master on the bench.
- **EtherCAT** — **no simulator exists** (hard-real-time, raw-Ethernet). Validate only on **Linux**, as **root / with `CAP_NET_RAW`**, on a **dedicated NIC** wired to **real slaves** (e.g. a Beckhoff EK1100 coupler + EL terminals). `iaiops doctor` reports a clear "needs Linux/root/NIC/pysoem" status off the bus rather than failing.

---

## Usage

### CLI (read)
```bash
iaiops opcua read "ns=2;i=5" -e line1
iaiops modbus holding 0 -e plc2 --count 4 --decode float32
iaiops s7 read-db 1 REAL 4 -e press1 --count 2
iaiops mc words D100 -e cell3 --count 8
iaiops fins words 100 --area DM -e omron1 --count 8   # Omron FINS memory-area read
iaiops hart pv -e xmtr1                            # HART primary variable
iaiops iolink scan -e iolm1                        # IO-Link master + connected devices
iaiops mtconnect oee -e vmc1
iaiops mqtt nodes -e uns --timeout-s 15
iaiops eip tags -e cell5                           # Logix tag discovery
iaiops eip read "Conveyor.Speed" -e cell5
iaiops ethercat slaves -e bus1                     # EtherCAT bus scan (Linux+root)
iaiops ethercat read-sdo 0 4120 --subindex 1 -e bus1   # CoE SDO 0x1018:1
iaiops opcua history "ns=2;i=5" -e line1 --start 2026-06-28T08:00:00Z   # HDA
iaiops opcua monitor "ns=2;i=5" -e line1 --duration-s 20 --deadband 0.5 # CoV
iaiops diag dataflow -e line1 --ref "ns=2;i=5" --freshness-s 30
iaiops analytics oee 28800 25200 2.0 12000 11800   # OEE = A×P×Q
iaiops analytics asset -e press1 -e cell5           # active asset register
```

### CLI (write — dry-run by default, double-confirm on `--apply`)
```bash
iaiops s7 write-db 1 INT 0 42 -e press1            # dry-run preview
iaiops s7 write-db 1 INT 0 42 -e press1 --apply    # double-confirm prompt
iaiops mqtt publish factory/line1/cmd '{"setpoint":50}' -e uns --apply
iaiops eip write-tag Setpoint 42 -e cell5 --apply  # Logix tag write (double-confirm)
iaiops fins write-words 100 42 --area DM -e omron1 --apply  # Omron FINS write (double-confirm)
iaiops ethercat write-sdo 0 24698 e8030000 -e bus1 --apply   # CoE SDO 0x607A download
iaiops ethercat set-state PREOP --slave 0 -e bus1 --apply     # AL-state (can stop motion!)
```

### MCP tool calls (JSON args → sample structured return)

`s7_read_db`:
```json
{ "db": 1, "dtype": "REAL", "start": 4, "endpoint": "press1", "count": 2 }
```
```json
{ "endpoint": "press1", "area": "DB", "db": 1, "dtype": "REAL", "start": 4,
  "count": 2, "items": [ {"address": "DB1,REAL4", "value": 20.5},
                         {"address": "DB1,REAL8", "value": 4.2} ] }
```

`s7_write_db` (dry-run):
```json
{ "db": 1, "dtype": "INT", "start": 0, "value": 42, "endpoint": "press1" }
```
```json
{ "address": "DB1,INT0", "dry_run": true, "before": 7, "would_write": 42,
  "note": "Dry run — nothing written. Re-run with dry_run=false AND a recorded approver…" }
```

`mtconnect_oee_snapshot`:
```json
{ "availability": "AVAILABLE", "execution": "ACTIVE", "controller_mode": "AUTOMATIC",
  "program": "O1234", "available": true, "running": true, "verdict": "running" }
```

`eip_read_tag`:
```json
{ "tag": "Conveyor.Speed", "endpoint": "cell5" }
```
```json
{ "endpoint": "cell5", "tag": "Conveyor.Speed", "value": 1500.0, "type": "REAL",
  "error": "", "good": true }
```

`eip_write_tag` (dry-run):
```json
{ "tag": "Setpoint", "value": 42, "endpoint": "cell5" }
```
```json
{ "endpoint": "cell5", "tag": "Setpoint", "dry_run": true, "before": 7,
  "would_write": 42, "note": "Dry run — nothing written. Re-run with dry_run=false AND a recorded approver…" }
```

`ethercat_read_sdo` (CoE SDO upload):
```json
{ "slave": 0, "index": 4120, "subindex": 1, "endpoint": "bus1" }
```
```json
{ "endpoint": "bus1", "slave": 0, "index": "0x1018", "subindex": 1,
  "byte_length": 4, "hex": "9a020000", "as_uint": 666 }
```

`ethercat_set_state` (dry-run; can start/stop motion):
```json
{ "state": "OP", "slave": 0, "endpoint": "bus1" }
```
```json
{ "endpoint": "bus1", "scope": "slave[0]", "dry_run": true, "before": "SAFEOP",
  "would_request": "OP", "note": "Dry run — no state change. … Changing EtherCAT state can start/stop machine motion." }
```

`sparkplug_decode_payload` (full SpB metric decode):
```json
{ "payload": "CAESBwoDYWJjEAE=", "encoding": "base64" }
```
```json
{ "encoding": "sparkplug_b", "seq": 0, "metric_count": 2, "historical_count": 0,
  "metrics": [ {"name": "Temperature", "alias": 1, "datatype": "Double", "value": 21.5,
                "is_historical": false, "is_null": false} ] }
```

`oee_compute`:
```json
{ "planned_time_s": 28800, "run_time_s": 25200, "ideal_cycle_time_s": 2.0,
  "total_count": 12000, "good_count": 11800 }
```
```json
{ "availability": {"raw": 0.875, "value": 0.875, "capped": false},
  "performance": {"value": 0.952381}, "quality": {"value": 0.983333},
  "oee": 0.819444, "oee_pct": 81.94 }
```

`asset_inventory` (active fingerprint):
```json
{ "endpoints": ["press1", "cell5"] }
```
```json
{ "asset_count": 2, "reachable_count": 2, "method": "active_fingerprint",
  "assets": [ {"endpoint": "press1", "protocol": "s7", "vendor": "Siemens/compatible",
               "model": "CPU 1511-1 PN", "firmware": "2.8", "reachable": true,
               "last_seen": "2026-06-28T10:00:00+00:00"} ] }
```

### Diagnostics (multi-dimensional JSON for an agent to visualize)

`diagnose_dataflow(endpoint="line1", ref="ns=2;i=5", freshness_threshold_s=30)`:
```json
{ "verdict": "comms_ok_value_stale",
  "diagnosis": "Connected with good status, but the value is STALE (age 412s > 30s) — the source/field upstream has stopped updating this point.",
  "recommended_action": "Trace upstream: the device serves the last value fine, so suspect the source/scanner/field signal that should refresh it.",
  "hops": [ {"hop":"connect","protocol":"opcua","ok":true,"detail":"OPC-UA state=0"},
            {"hop":"read_tag","ref":"ns=2;i=5","ok":true,"detail":"5.0"},
            {"hop":"freshness","evaluated":true,"stale":true,"age_seconds":412.0} ] }
```

`alarm_bad_actors(events=[…])`:
```json
{ "event_count": 55, "window_minutes": 0.82, "alarms_per_hour": 4024.4,
  "isa_18_2": {"ok_max":6,"manageable_max":12,"flood_min":30},
  "flood_verdict": "flood",
  "priority_distribution": {"high":50,"low":5},
  "pareto_sources_for_80pct": ["FIC101"],
  "top_offenders": [ {"source":"FIC101","count":50,"share_pct":90.9,"chattering":true,"standing":false} ],
  "chattering": ["FIC101"], "standing": [] }
```

`tag_health(tags=[…])`:
```json
{ "evaluated": 4, "overall": "alarm", "offender_count": 3,
  "offenders": [ {"ref":"hot","latest":99,"flags":["out_of_range_alarm"],"severity":3},
                 {"ref":"flat","latest":5,"flags":["flatline"],"severity":2},
                 {"ref":"bad","latest":null,"flags":["bad_quality"],"severity":3} ] }
```

#### AI downtime root-cause copilot (flagship)

`downtime_root_cause` correlates whatever evidence you can hand over — alarm
events, tag samples, a `diagnose_dataflow` verdict, a machine-state series —
around an incident window and returns an **evidence-cited, advisory** verdict.
Read-first: it proposes a human-approved, MOC-gated, undoable action and executes
nothing. Anti-hallucination by design — it cites only signals actually present in
the input, weights them by temporal proximity to onset (a cause precedes its
effect), and downgrades to `insufficient_evidence` (with a `recommended_next_data`
list) rather than guessing when evidence is thin.

`downtime_root_cause(window={"start":"2026-06-28T10:00:00Z","asset":"line1"},
alarms=[{"source":"M1_DRIVE","timestamp":"2026-06-28T09:59:52Z","message":"motor overload trip"}],
tags=[{"ref":"DRV1.Torque","samples":[10,11,99,99],"alarm_high":80}], dataflow={"verdict":"healthy"})`:
```json
{ "window": {"start":"2026-06-28 10:00:00+00:00","asset":"line1","duration_s":300.0},
  "verdict": "root_cause_identified",
  "primary_cause": {
    "cause": "mechanical_fault", "confidence": 0.722, "confidence_band": "high",
    "evidence": [
      {"signal":"alarm","ref":"M1_DRIVE","at":"2026-06-28 09:59:52+00:00","lead_time_s":8.0,
       "detail":"motor overload trip","weight":0.4959},
      {"signal":"tag","ref":"DRV1.Torque","detail":"flags=out_of_range_alarm severity=3","weight":0.45} ],
    "recommended_action": "Dispatch maintenance to inspect the faulting unit; if a latch/interlock is set, the reversible step is to clear the fault and reset the latch (MOC-approved, undo captures the prior latch state)." },
  "evidence_summary": {"alarms_supplied":1,"tags_supplied":1,"dataflow_verdict":"healthy","total_evidence_items":2},
  "anti_hallucination": "Advisory only — nothing is executed. Every cited signal is present in the supplied evidence …" }
```

The same copilot is on the CLI: `iaiops diag rca --input bundle.json` where the
bundle is `{window, alarms?, tags?, dataflow?, state_series?}`.

**Let it gather its own evidence.** `downtime_root_cause_live` (CLI `iaiops diag
rca-live`) takes just an endpoint + window + the refs to look at, then pulls the
evidence itself — a cross-protocol `diagnose_dataflow` probe, a short sampled
series per ref (so flatline / bad-quality / anomaly surface via `tag_health`),
and active OPC-UA conditions — before running the same advisory, read-only copilot.
The gathered bundle is echoed back under `collected_evidence` (no hidden inputs):

```bash
iaiops diag rca-live -e line1 --start 2026-06-28T10:00:00Z \
  --asset line1 --ref "ns=2;i=5" --ref "ns=2;i=6"
```

### Data-quality watchdog & UNS governance (read-only intelligence)
Two more pure-analysis layers — fully testable without live gear, and they feed the RCA copilot.
- **`data_quality_scorecard`** (CLI `iaiops diag dataquality`) — a fleet **data-TRUST** rollup: scores each tag 0-100 on whether its data can be *believed* — staleness, **dead heartbeat** (first-class), bad-quality, flatline, gaps, anomaly — then rolls up per endpoint and across the fleet with an issue breakdown and ranked worst offenders. Distinct from process health: it asks "can I trust this number," not "is this number alarming." `heartbeat_health` (CLI `iaiops diag heartbeat`) is the standalone watchdog-liveness check (a flatlined heartbeat = dead upstream even when comms look fine).
- **`uns_topic_audit`** (CLI `iaiops mqtt uns-audit`) — governs a UNS topic tree: naming conformance (allowed roots / min depth) + **topic sprawl** (casing collisions of the same logical name, leaf metrics scattered under many parents, depth outliers, duplicates) → a `clean`/`minor`/`sprawling` verdict. **`uns_schema_drift`** (CLI `iaiops mqtt uns-drift`) — compares two Sparkplug NBIRTH-style snapshots and classifies the change `none` / `additive` / `breaking` (a metric removed or its datatype changed). Positions the UNS as a *governable* neutral data source, not just a broker.

### MCP server
```bash
IAIOPS_MCP=opcua iaiops-mcp   # stdio transport (`iaiops mcp` is equivalent)
```

**Menu — expose only the protocols a site runs.** A fab usually runs 1–2 protocols;
exposing all 14 floods the model with tools it can't use. Set `IAIOPS_MCP` to a
comma-list of protocols and/or a named profile. **There is no default** (since
0.10.0): a bare `iaiops-mcp` prints the selection menu (profiles, protocol keys,
tool counts) to stderr and exits 2 instead of silently exposing 100+ tools. The
cross-protocol brain (OEE / downtime / diagnostics / asset / analysis) is included
by default with every selection.

```bash
IAIOPS_MCP=menu         iaiops-mcp   # print the menu (selections + tool counts)
IAIOPS_MCP=opcua,modbus iaiops-mcp   # two protocols + brain
IAIOPS_MCP=fab          iaiops-mcp   # named profile (secsgem+opcua+s7+modbus)
IAIOPS_MCP=opcua        iaiops-mcp   # effectively a single-protocol MCP
IAIOPS_MCP=all          iaiops-mcp   # everything — explicit opt-in only
                                     # (logs a tool-flood warning above 60 tools)
```

**Named entry-point sugar.** For the common single-protocol / single-edition case
there is a pre-scoped console script per protocol and per named profile — no env
var to set. Each is a thin shim over the same server:

```bash
iaiops-mcp-opcua     # == IAIOPS_MCP=opcua    iaiops-mcp
iaiops-mcp-modbus    # == IAIOPS_MCP=modbus   iaiops-mcp
iaiops-mcp-fab       # == IAIOPS_MCP=fab      iaiops-mcp  (per-edition)
iaiops-mcp-building  # == IAIOPS_MCP=building iaiops-mcp
iaiops-mcp-brain     # == IAIOPS_MCP=brain    iaiops-mcp  (brain only, 0 protocols)
```

**Multi-process sites — 1 brain MCP + N protocol MCPs.** Running several protocol
servers side by side (e.g. `iaiops-mcp-opcua` + `iaiops-mcp-modbus`) would duplicate
the ~30 brain tools in every server. Instead run one dedicated `iaiops-mcp-brain`
and set `IAIOPS_MCP_NO_BRAIN=1` on the protocol servers to strip the brain from
them — the `protocols_supported` discovery tool stays exposed everywhere:

```bash
iaiops-mcp-brain                          # the one cross-protocol brain server
IAIOPS_MCP_NO_BRAIN=1 iaiops-mcp-opcua    # lean protocol server, no brain
IAIOPS_MCP_NO_BRAIN=1 iaiops-mcp-modbus
```

Named profiles: `all` · `brain` · `fab` · `factory` · `process` · `building` ·
`water` · `plcnext`. In an MCP client (e.g. Claude Desktop) set `IAIOPS_MCP` per
server entry — or point the entry straight at the matching `iaiops-mcp-<name>`
script — one entry per site/line, each a lean single- or dual-protocol server.

---

## Safety & governance

- **Read-first.** 156 of 166 tools are read-only. The 10 write/command tools (`s7_write_db`, `mc_write_words`, `fins_write_words`, `mqtt_publish`, `eip_write_tag`, `ethercat_write_sdo`, `ethercat_set_state`, `profinet_dcp_set`, `bacnet_write_property`, `bas_command`) are **OT-dangerous**: governed at **high risk_tier**, **off by default (dry-run)**, capture the **BEFORE value/state for undo**, require a **double-confirm in the CLI**, and a recorded approver (one-shot `iaiops approve` tokens; with no `risk_tiers` configured, high/critical operations default to the `dual` tier) — **MOC discipline**. **`ethercat_set_state` can START or STOP machine motion.** 未经授权勿对生产控制系统写入.
- **Do not point this at a production control system without authorization.** OT networks are safety-critical; even reads add load. Test against a simulator first.
- All endpoint-returned text is sanitized (prompt-injection defense); secrets are never returned by any tool; MTConnect XML is parsed with DTD/entity declarations refused.
- Every tool runs through the vendored governance harness: SQLite **audit** (`~/.iaiops/audit.db`, SHA-256 **hash-chained** rows + `iaiops audit verify`; audit **fails closed** for high/critical writes), token/call **budget** + runaway breaker, **risk-tier** gate (policy engine fails closed on a broken `rules.yaml`), **undo** recording. The MCP server **refuses to start** if any registered tool lacks the governance marker.

## Roadmap

- EtherNet/IP **PLC-5 / SLC-500 (PCCC)** and **Micro800** support (Logix tags are done in 0.2.0).
- **Passive** asset discovery (SPAN/tap, no connections) alongside today's active fingerprint.
- EtherCAT **EoE / FoE / SoE** mailbox protocols and full PDO-mapping decode (CoE SDO/PDO read+write and AL-state landed in 0.3.0 via the optional `pysoem` extra).
- OPC-UA certificate security + real Alarms & Conditions subscriptions.
- MTConnect streaming long-poll; Sparkplug B DataSet/Template deep expansion.

**Missing a protocol, device, or feature? 缺功能提 issue/PR 欢迎留言** — open a [GitHub issue or PR](https://github.com/industrial-aiops/industrial-aiops/issues).

## License

MIT © wei