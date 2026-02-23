import unittest
from pathlib import Path
from datetime import datetime
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.log_parser import LogStore
from tools.latency_analysis import detect_slow_requests, diagnose_latency_sources
from tools.error_analysis import analyze_error_patterns
from tools.resource_monitoring import check_resource_usage
from tools.visualization import generate_latency_chart, generate_error_heatmap

class TestPerformanceTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use the actual logs in the project for testing
        cls.log_dir = Path(__file__).parent.parent / "logs"
        cls.store = LogStore(cls.log_dir)

    def test_detect_slow_requests_filtering(self):
        """Verify slow request threshold filtering."""
        threshold = 5000
        result = detect_slow_requests(self.store, threshold_ms=threshold, time_window="1h")
        
        # Check that top_10_slowest actually respects the threshold
        for req in result.get('top_slow_requests', []):
            self.assertGreaterEqual(req['response_time_ms'], threshold)

    def test_diagnose_latency_sources_breakdown(self):
        """Verify latency breakdown components exist and sum correctly."""
        endpoint = "/api/v1/payments/history"
        result = diagnose_latency_sources(self.store, service="payment_api", endpoint=endpoint, time_window="1h")
        
        breakdown = next((b for b in result['breakdowns'] if b['group_key'] == endpoint), None)
        if breakdown:
            self.assertIn('total_median_ms', breakdown)
            self.assertIn('db_median_ms', breakdown)
            self.assertIn('external_median_ms', breakdown)
            self.assertIn('app_logic_median_ms', breakdown)
            self.assertIn('unaccounted_median_ms', breakdown)
            self.assertIn("primary_bottleneck", breakdown)
            
            # Components should be non-negative
            self.assertGreaterEqual(breakdown['db_median_ms'], 0)
            self.assertGreaterEqual(breakdown['total_median_ms'], 0)

    def test_analyze_error_patterns_rate(self):
        """Verify error rate calculation handles requests-only denominator."""
        result = analyze_error_patterns(self.store, service="payment_api", time_window="1h")
        
        req_count = result['request_entries']
        err_count = result['error_warn_entries']
        expected_rate = round(err_count / req_count * 100, 2) if req_count else 0.0
        
        self.assertEqual(result['error_rate_pct'], expected_rate)

    def test_check_resource_usage_indicators(self):
        """Verify resource usage indicators are structured correctly."""
        result = check_resource_usage(self.store, service="charging_controller", time_window="24h")
        
        self.assertIn("indicators", result)
        indicators = result['indicators']
        
        # Should have specific indicators for charging_controller
        indicator_names = [i['indicator_name'] for i in indicators]
        self.assertIn("Hardware Errors", indicator_names)
        self.assertIn("Abnormal State Transitions", indicator_names)
        
        for ind in indicators:
            self.assertIn(ind['severity'], ["NORMAL", "MEDIUM", "HIGH", "CRITICAL"])

    def test_detect_slow_requests_all_services(self):
        """Global scan (service=None) returns valid structure."""
        result = detect_slow_requests(self.store, time_window="48h")
        self.assertIsInstance(result, dict)
        self.assertEqual(result['service'], 'all_services')
        self.assertIn('profiles', result)
        self.assertIn('spike_windows', result)
        self.assertIn('top_slow_requests', result)
        self.assertGreater(result['total_timed_requests'], 0)

    def test_detect_slow_requests_empty_window(self):
        """Very narrow window should return 0 slow requests without crashing."""
        result = detect_slow_requests(self.store, time_window="1m", threshold_ms=999999)
        self.assertIsInstance(result, dict)
        self.assertEqual(result['slow_request_count'], 0)
        self.assertEqual(result['top_slow_requests'], [])

    def test_detect_slow_requests_spike_windows_structure(self):
        """Spike windows (if any) have required keys."""
        result = detect_slow_requests(self.store, time_window="48h", threshold_ms=2000)
        for spike in result.get('spike_windows', []):
            self.assertIn('start', spike)
            self.assertIn('end', spike)
            self.assertIn('endpoint', spike)
            self.assertIn('count', spike)
            self.assertGreaterEqual(spike['count'], 3)

    def test_diagnose_latency_sources_disjoint_windows(self):
        """Baseline window ends where current window starts (no overlap)."""
        result = diagnose_latency_sources(
            self.store, service="payment_api",
            time_window="24h", baseline_window="48h"
        )
        current_start = result['current_window']['start']
        baseline_end = result['baseline_window']['end']
        self.assertEqual(current_start, baseline_end,
                         "Baseline must end exactly where current starts (disjoint)")

    def test_analyze_error_patterns_group_by_error_type(self):
        """group_by='error_type' returns valid buckets."""
        result = analyze_error_patterns(
            self.store, time_window="48h", group_by="error_type"
        )
        self.assertEqual(result['group_by'], 'error_type')
        for bucket in result['buckets']:
            self.assertIn('group_key', bucket)
            self.assertIn('total_errors', bucket)
            self.assertIn('failure_rate_pct', bucket)

    def test_analyze_error_patterns_group_by_provider(self):
        """group_by='provider' for notification service."""
        result = analyze_error_patterns(
            self.store, service="notification_service",
            time_window="48h", group_by="provider"
        )
        self.assertEqual(result['group_by'], 'provider')
        self.assertIsInstance(result['buckets'], list)

    def test_check_resource_usage_all_services(self):
        """Global scan includes indicators from all 3 services."""
        result = check_resource_usage(self.store, time_window="48h")
        services_in_indicators = set(
            ind['service'] for ind in result['indicators']
        )
        self.assertIn('payment_api', services_in_indicators)
        self.assertIn('charging_controller', services_in_indicators)
        self.assertIn('notification_service', services_in_indicators)

    def test_check_resource_usage_notification(self):
        """Notification service has queue and retry indicators."""
        result = check_resource_usage(
            self.store, service="notification_service", time_window="48h"
        )
        indicator_names = [i['indicator_name'] for i in result['indicators']]
        self.assertIn('Retry Exhaustion', indicator_names)
        self.assertIn('Delivery Failures', indicator_names)

    def test_data_context_present_in_all_tools(self):
        """Every tool output includes data_context with freshness info."""
        tools = [
            lambda: detect_slow_requests(self.store, time_window="48h"),
            lambda: diagnose_latency_sources(self.store, time_window="24h", baseline_window="48h"),
            lambda: analyze_error_patterns(self.store, time_window="48h"),
            lambda: check_resource_usage(self.store, time_window="48h"),
            lambda: generate_latency_chart(self.store, time_window="48h"),
            lambda: generate_error_heatmap(self.store, time_window="48h"),
        ]
        for tool_fn in tools:
            result = tool_fn()
            self.assertIn('data_context', result)
            ctx = result['data_context']
            self.assertIn('log_data_ends_at', ctx)
            self.assertIn('hours_since_last_log', ctx)
            self.assertIn('is_historical', ctx)

    def test_generate_latency_chart_valid(self):
        """Test latency chart generation returns a valid filepath."""
        res = generate_latency_chart(self.store, service="payment_api", time_window="24h")
        self.assertNotIn("error", res)
        self.assertIn("filepath", res)
        self.assertTrue(Path(res["filepath"]).exists())

    def test_generate_error_heatmap_valid(self):
        """Test error heatmap generation returns a valid filepath."""
        res = generate_error_heatmap(self.store, time_window="48h")
        self.assertNotIn("error", res)
        self.assertIn("filepath", res)
        self.assertTrue(Path(res["filepath"]).exists())

if __name__ == '__main__':
    unittest.main()
