import argparse
import subprocess
import sys
from pathlib import Path

def run_cmd(cmd):
    print(f"\n>> Running: {cmd}")
    res = subprocess.run(cmd, shell=True)
    if res.returncode != 0:
        print(f"ERROR: Command failed with code {res.returncode}")
        sys.exit(res.returncode)

def main():
    parser = argparse.ArgumentParser(description="Run the full VAYU index pipeline on an active dataset (e.g. 3,000 observations).")
    parser.add_argument("--count", type=int, default=3000, help="Number of synthetic observations to generate for training.")
    parser.add_argument("--skip-generation", action="store_true", help="Skip generating the 3,000-observation dataset and use the existing one.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    
    if not args.skip_generation:
        run_cmd(f"python scripts/generate_3000_dataset.py --count {args.count}")
        
    run_cmd("python scripts/run_validation.py --input data/synthetic/vayu_synthetic_3000_observations.csv --output outputs/validated_airfare_observations.csv --skip-audit")
    run_cmd("python scripts/run_deduplication.py")
    run_cmd("python scripts/run_consolidation.py")
    run_cmd("python scripts/run_normalization.py")
    run_cmd("python scripts/run_anomaly_detection.py")
    run_cmd("python scripts/run_route_aggregation.py")
    run_cmd("python scripts/run_index_engine.py")
    run_cmd("python scripts/run_backtesting.py")
    
    print("\nUpdating manifest hashes for active dataset...")
    run_cmd("python scripts/update_manifest.py")
    
    print("\nChecking server and dataset health...")
    run_cmd("python scripts/run_api.py --check")
    run_cmd("python scripts/verify_phase14.py")
    
    print("\nPipeline completed successfully! You can now run 'python scripts/run_api.py' to start the server.")

if __name__ == "__main__":
    main()
