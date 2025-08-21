#!/usr/bin/env python3
"""
Test client for the Jest Lua Test Server.
Sends tests.rbxm to the /test endpoint.
"""

import json
import sys
from pathlib import Path

import requests

SERVER_URL = "http://127.0.0.1:8325"
rbxm_path = Path(__file__).parent / "tests.rbxm"


def main():
    if not rbxm_path.exists():
        print(f"Error: {rbxm_path} not found in current directory")
        sys.exit(1)

    print(f"Reading {rbxm_path}...")
    with open(rbxm_path, "rb") as f:
        rbxm_data = f.read()

    print(f"File size: {len(rbxm_data)} bytes")

    print(f"\nSending test to {SERVER_URL}/test...")
    try:
        response = requests.post(
            f"{SERVER_URL}/test",
            data=rbxm_data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=35,  # Slightly longer than server's 30s timeout
        )

        if response.status_code == 200:
            result = response.json()
            print("\nTest completed successfully!")
            print(f"Test ID: {result['test_id']}")
            print(f"Status: {result['status']}")

            if result.get("results"):
                print("\nResults:")
                print(json.dumps(result["results"], indent=2))

            if result.get("error"):
                print(f"\nError: {result['error']}")
        else:
            print(f"\nRequest failed with status {response.status_code}")
            print(response.text)

    except requests.exceptions.Timeout:
        print("\nRequest timed out (exceeded 35 seconds)")
    except requests.exceptions.ConnectionError:
        print(f"\nFailed to connect to server at {SERVER_URL}")
        print("Make sure the server is running (python server/run.py)")
    except Exception as e:
        print(f"\nUnexpected error: {e}")


if __name__ == "__main__":
    main()
