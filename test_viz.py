"""
test_viz.py -- Quick verification of visualization tools
Run this to generate sample charts in the charts/ directory.
"""
from pathlib import Path
from utils.log_parser import LogStore
from tools.visualization import generate_latency_chart, generate_error_heatmap

def main():
    print("--- Starting Visualization Test ---")
    
    # 1. Load Store
    store = LogStore(Path("logs"))
    print(f"Total entries: {len(store.entries)}")
    
    # 2. Test Latency Chart (All Services)
    print("\n[1/3] Generating All-Services Latency Chart (48h)...")
    res1 = generate_latency_chart(store, service=None, time_window="48h")
    if "error" in res1:
        print(f"  FAILED: {res1['error']} - {res1.get('details', '')}")
    else:
        print(f"  SUCCESS: {res1['filepath']}")
        print(f"  Stats: {res1['entry_count']} entries, {res1['spike_windows_marked']} spikes")

    # 3. Test Latency Chart (Payment API)
    print("\n[2/3] Generating Payment API Latency Chart (24h)...")
    res2 = generate_latency_chart(store, service="payment_api", time_window="24h")
    if "error" in res2:
        print(f"  FAILED: {res2['error']}")
    else:
        print(f"  SUCCESS: {res2['filepath']}")

    # 4. Test Error Heatmap
    print("\n[3/3] Generating Error Heatmap (48h)...")
    res3 = generate_error_heatmap(store, time_window="48h")
    if "error" in res3:
        print(f"  FAILED: {res3['error']}")
    else:
        print(f"  SUCCESS: {res3['filepath']}")
        print(f"  Stats: {res3['total_errors']} errors, peak hour: {res3['peak_hour']}")

    print("\n--- Visualization Verification Complete ---")
    print("Check the 'charts/' folder for the generated PNG files.")

if __name__ == "__main__":
    main()
