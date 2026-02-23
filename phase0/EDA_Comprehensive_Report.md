# 📊 EDA Comprehensive Report — Performance Logs

_Generated: 2026-02-21 19:02:39_

## 1. General Overview

- **Total parsed records**: 3,005
- **Total lines read**: 3,005
- **Malformed / skipped**: 0
- **Earliest timestamp**: `2025-02-19 00:00:22+00:00`
- **Latest timestamp**: `2025-02-20 23:59:22+00:00`
- **Time span**: `1 day, 23:59:00`
- **Universal fields**: `event_type, level, metadata, service, timestamp`

### Per-File Breakdown

| File | Lines | Parsed | Malformed |
| --- | --- | --- | --- |
| payment_api.log | 1190 | 1190 | 0 |
| charging_controller.log | 1015 | 1015 | 0 |
| notification_service.log | 800 | 800 | 0 |


## 2. Service-Specific EDA

### 2.1. `payment_api` (1,190 records)

#### Level Distribution

| Level | Count | Pct |
| --- | --- | --- |
| INFO | 824 | 69.2% |
| WARN | 221 | 18.6% |
| ERROR | 145 | 12.2% |


#### Event Types

| Event Type | Count | Pct |
| --- | --- | --- |
| api_request_completed | 840 | 70.6% |
| api_request_failed | 260 | 21.8% |
| database_query_slow | 60 | 5.0% |
| external_api_timeout | 30 | 2.5% |


#### Root-Level Schema

| Key | Present In | Pct |
| --- | --- | --- |
| timestamp | 1190 | 100.0% |
| service | 1190 | 100.0% |
| level | 1190 | 100.0% |
| event_type | 1190 | 100.0% |
| endpoint | 1190 | 100.0% |
| method | 1190 | 100.0% |
| status_code | 1190 | 100.0% |
| response_time_ms | 1190 | 100.0% |
| metadata | 1190 | 100.0% |


#### Metadata Keys

| Key | Count | Pct | Types | Sample Values |
| --- | --- | --- | --- | --- |
| user_id | 1190 | 100.0% | str(1190) | ['user_7395', 'user_1551'] |
| external_api_time_ms | 930 | 78.2% | int(930) | [160, 195] |
| db_query_time_ms | 900 | 75.6% | int(900) | [5841, 51] |
| app_logic_time_ms | 900 | 75.6% | int(900) | [27, 20] |
| payment_gateway | 870 | 73.1% | str(870) | ['paypal', 'paypal'] |
| error | 290 | 24.4% | str(290) | ['service_unavailable', 'internal_server_error'] |
| query | 60 | 5.0% | str(60) | ['SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC', 'SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC'] |
| note | 60 | 5.0% | str(60) | ['missing_index_suspected', 'missing_index_suspected'] |
| stack_trace | 50 | 4.2% | str(50) | ['DatabaseConnectionError: Unable to acquire connection from pool', 'DatabaseConnectionError: Unable to acquire connection from pool'] |
| retry_count | 30 | 2.5% | int(30) | [3, 3] |


#### Response Time Stats (ms)

| Metric | Value |
| --- | --- |
| count | 1190 |
| min | 50 |
| max | 30000 |
| mean | 1279.41 |
| median | 243.0 |
| p95 | 5278 |
| p99 | 30000 |
| stdev | 4762.79 |


#### Status Code Distribution

| Status | Count |
| --- | --- |
| 200 | 900 |
| 500 | 72 |
| 401 | 34 |
| 400 | 31 |
| 504 | 30 |
| 422 | 29 |
| 403 | 28 |
| 404 | 23 |
| 502 | 22 |
| 503 | 21 |


#### Endpoint Distribution

| Endpoint | Count |
| --- | --- |
| /api/v1/payments/process | 404 |
| /api/v1/payments/history | 312 |
| /api/v1/payments/verify | 238 |
| /api/v1/payments/refund | 236 |


---

### 2.2. `charging_controller` (1,015 records)

#### Level Distribution

| Level | Count | Pct |
| --- | --- | --- |
| INFO | 850 | 83.7% |
| ERROR | 115 | 11.3% |
| WARN | 50 | 4.9% |


#### Event Types

| Event Type | Count | Pct |
| --- | --- | --- |
| charging_session_started | 350 | 34.5% |
| charging_session_completed | 300 | 29.6% |
| state_transition | 200 | 19.7% |
| hardware_communication_error | 115 | 11.3% |
| charging_session_timeout | 50 | 4.9% |


#### Root-Level Schema

| Key | Present In | Pct |
| --- | --- | --- |
| timestamp | 1015 | 100.0% |
| service | 1015 | 100.0% |
| level | 1015 | 100.0% |
| event_type | 1015 | 100.0% |
| metadata | 1015 | 100.0% |


#### Metadata Keys

| Key | Count | Pct | Types | Sample Values |
| --- | --- | --- | --- | --- |
| station_id | 1015 | 100.0% | str(1015) | ['STATION_039', 'STATION_045'] |
| connector_id | 1015 | 100.0% | str(1015) | ['CON_3', 'CON_1'] |
| user_id | 400 | 39.4% | str(400) | ['user_9083', 'user_6614'] |
| estimated_duration_min | 350 | 34.5% | int(350) | [57, 82] |
| duration_min | 300 | 29.6% | int(300) | [57, 75] |
| energy_delivered_kwh | 300 | 29.6% | float(300) | [40.84, 40.85] |
| from_state | 200 | 19.7% | str(200) | ['finishing', 'available'] |
| to_state | 200 | 19.7% | str(200) | ['idle', 'charging'] |
| trigger | 200 | 19.7% | str(200) | ['system_command', 'system_command'] |
| error | 115 | 11.3% | str(115) | ['timeout_waiting_for_heartbeat', 'firmware_mismatch'] |
| retry_count | 115 | 11.3% | int(115) | [1, 3] |
| response_time_ms | 115 | 11.3% | int(115) | [9950, 7700] |
| timeout_reason | 50 | 4.9% | str(50) | ['max_duration_exceeded', 'max_duration_exceeded'] |
| duration_before_timeout_min | 50 | 4.9% | int(50) | [30, 5] |
| note | 15 | 1.5% | str(15) | ['recurring_issue', 'recurring_issue'] |


---

### 2.3. `notification_service` (800 records)

#### Level Distribution

| Level | Count | Pct |
| --- | --- | --- |
| INFO | 520 | 65.0% |
| WARN | 200 | 25.0% |
| ERROR | 80 | 10.0% |


#### Event Types

| Event Type | Count | Pct |
| --- | --- | --- |
| message_sent | 520 | 65.0% |
| message_retry | 180 | 22.5% |
| message_failed | 60 | 7.5% |
| queue_processing_delayed | 40 | 5.0% |


#### Root-Level Schema

| Key | Present In | Pct |
| --- | --- | --- |
| timestamp | 800 | 100.0% |
| service | 800 | 100.0% |
| level | 800 | 100.0% |
| event_type | 800 | 100.0% |
| metadata | 800 | 100.0% |


#### Metadata Keys

| Key | Count | Pct | Types | Sample Values |
| --- | --- | --- | --- | --- |
| notification_type | 760 | 95.0% | str(760) | ['sms', 'sms'] |
| recipient | 760 | 95.0% | str(760) | ['user_5863', 'user_7534'] |
| provider | 760 | 95.0% | str(760) | ['twilio', 'twilio'] |
| subject | 520 | 65.0% | null(388), str(132) | [None, None] |
| processing_time_ms | 520 | 65.0% | int(520) | [293, 157] |
| queue_wait_time_ms | 520 | 65.0% | int(520) | [184, 177] |
| error | 240 | 30.0% | str(240) | ['network_timeout', 'invalid_recipient'] |
| retry_count | 240 | 30.0% | int(240) | [3, 3] |
| max_retries | 180 | 22.5% | int(180) | [3, 3] |
| final_status | 60 | 7.5% | str(60) | ['failed', 'failed'] |
| queue_depth | 40 | 5.0% | int(40) | [500, 525] |
| avg_wait_time_ms | 40 | 5.0% | int(40) | [1000, 1100] |
| processing_rate_per_sec | 40 | 5.0% | int(40) | [6, 14] |
| note | 40 | 5.0% | str(40) | ['queue_normal', 'queue_normal'] |


---

## 3. Nuance & Edge-Case Detection

### 3.1 Fast Failures (75 found)

> Requests with HTTP status ≥ 400 **and** response_time < 100ms.
> These indicate the server rejected the request before doing meaningful work.

| File | Timestamp | Endpoint | Status | RT(ms) |
| --- | --- | --- | --- | --- |
| payment_api.log | 2025-02-19T00:04:55Z | /api/v1/payments/history | 422 | 86 |
| payment_api.log | 2025-02-19T00:06:30Z | /api/v1/payments/history | 500 | 50 |
| payment_api.log | 2025-02-19T00:42:07Z | /api/v1/payments/refund | 404 | 97 |
| payment_api.log | 2025-02-19T01:05:43Z | /api/v1/payments/process | 500 | 77 |
| payment_api.log | 2025-02-19T02:43:43Z | /api/v1/payments/history | 401 | 84 |
| payment_api.log | 2025-02-19T04:07:16Z | /api/v1/payments/verify | 400 | 75 |
| payment_api.log | 2025-02-19T04:50:48Z | /api/v1/payments/process | 503 | 63 |
| payment_api.log | 2025-02-19T06:45:38Z | /api/v1/payments/verify | 403 | 86 |
| payment_api.log | 2025-02-19T06:51:58Z | /api/v1/payments/history | 422 | 53 |
| payment_api.log | 2025-02-19T06:59:57Z | /api/v1/payments/process | 401 | 73 |
| payment_api.log | 2025-02-19T07:15:30Z | /api/v1/payments/process | 502 | 59 |
| payment_api.log | 2025-02-19T07:24:01Z | /api/v1/payments/history | 404 | 50 |
| payment_api.log | 2025-02-19T09:12:50Z | /api/v1/payments/verify | 404 | 81 |
| payment_api.log | 2025-02-19T09:42:08Z | /api/v1/payments/refund | 502 | 92 |
| payment_api.log | 2025-02-19T09:58:14Z | /api/v1/payments/refund | 503 | 95 |
| payment_api.log | 2025-02-19T12:07:26Z | /api/v1/payments/history | 401 | 87 |
| payment_api.log | 2025-02-19T12:21:30Z | /api/v1/payments/refund | 400 | 99 |
| payment_api.log | 2025-02-19T13:20:43Z | /api/v1/payments/verify | 503 | 50 |
| payment_api.log | 2025-02-19T13:20:59Z | /api/v1/payments/history | 404 | 70 |
| payment_api.log | 2025-02-19T13:34:46Z | /api/v1/payments/history | 401 | 80 |

_…and 55 more._

### 3.2 ERROR Logs Missing Error Description (0 found)

_All ERROR-level logs have an 'error' key in metadata._

### 3.3 Field Location Inconsistencies

| Field | Root Only | Meta Only | Both | Neither | Total |
| --- | --- | --- | --- | --- | --- |
| user_id | 0 | 1590 | 0 | 1415 | 3005 |
| station_id | 0 | 1015 | 0 | 1990 | 3005 |
| error | 0 | 645 | 0 | 2360 | 3005 |


### 3.4 WARN-Level Breakdown

| Event Type | Count |
| --- | --- |
| message_retry | 160 |
| api_request_failed | 145 |
| database_query_slow | 60 |
| charging_session_timeout | 50 |
| queue_processing_delayed | 40 |
| api_request_completed | 16 |


### 3.5 Timestamp Gap Analysis

| File | Max Gap (s) | Avg Gap (s) | Median Gap (s) |
| --- | --- | --- | --- |
| payment_api.log | 1044.0 | 145.0 | 100.0 |
| charging_controller.log | 1151.0 | 170.4 | 122.0 |
| notification_service.log | 1797.0 | 215.8 | 138.0 |


## 4. Future-Proofing — Predictive Schema Analysis

**Fields already present that match production patterns:** `(none)`

### Missing Fields Expected in Production (15 identified)

| Field | Rationale | Impact if Missing |
| --- | --- | --- |
| trace_id | Distributed tracing is essential for correlating requests across microservices (OpenTelemetry / Jaeger). | Without it, root-cause analysis across service boundaries is manual guesswork. |
| span_id | Companion to trace_id; identifies individual spans within a distributed trace. | Needed for latency waterfall visualisation. |
| request_id | Unique ID per request for deduplication and correlating retry attempts. | Helps track a single user action end-to-end. |
| correlation_id | Links asynchronous events (e.g., a payment triggers a notification) across services. | Critical for debugging message-queue-based flows. |
| ip_address | Client or server IP for geo-based analysis, abuse detection, and CDN routing diagnostics. | Enables regional performance analysis. |
| region | Cloud region / availability zone for multi-region deployments. | Allows region-specific latency dashboards. |
| container_id | K8s pod name or Docker container ID; essential for isolating issues to a specific replica. | Without it, noisy-neighbour issues are invisible. |
| host | Server hostname for bare-metal or VM-based deployments. | Pinpoints which host is misbehaving. |
| environment | prod / staging / dev tag; prevents dev logs leaking into prod dashboards. | Operational hygiene. |
| version | Application version or git SHA; correlates performance changes with deployments. | Enables deployment-aware regression detection. |
| memory_usage_mb | Process-level memory usage for leak detection. | Proactive OOM prevention. |
| cpu_usage_pct | Process-level CPU usage for thread-starvation detection. | Explains latency spikes caused by compute saturation. |
| thread_count | Active threads for concurrency monitoring. | Detects thread pool exhaustion. |
| db_connection_pool_active | Active DB connections for pool-exhaustion detection. | Explains sudden query latency increases. |
| cache_hit_ratio | Cache effectiveness metric, crucial for performance. | Detects cache invalidation storms. |

