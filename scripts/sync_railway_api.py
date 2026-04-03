#!/usr/bin/env python3
"""
Railway API: Setze PUBLIC_IMAGE_BASE_URL via REST API (ohne CLI).

Nutzt den Token aus ~/.railway/config.json
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# Load token from Railway config
RAILWAY_CONFIG = Path.home() / ".railway" / "config.json"
with open(RAILWAY_CONFIG) as f:
    config = json.load(f)
    TOKEN = config["user"]["token"]

# Get env from gifhorn-events-bot project
PROJECT_ID = config["projects"]["/Users/chrischel/Documents/Events/gifhorn-events-bot"]["project"]
ENVIRONMENT_ID = config["projects"]["/Users/chrischel/Documents/Events/gifhorn-events-bot"]["environment"]

# Railway URL (hardcoded for this environment)
REPO = Path(__file__).resolve().parents[1]
PUBLIC_IMAGE_BASE_URL = "https://gifhorn-dashboard-production.up.railway.app"

print(f"🔧 Railway API Setup")
print(f"   Project ID: {PROJECT_ID}")
print(f"   Environment ID: {ENVIRONMENT_ID}")
print(f"   PUBLIC_IMAGE_BASE_URL: {PUBLIC_IMAGE_BASE_URL}\n")


def graphql_query(query: str, variables: dict[str, Any] | None = None) -> dict:
    """Execute GraphQL query to Railway API."""
    url = "https://api.railway.app/graphql"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    body = {"query": query}
    if variables:
        body["variables"] = variables

    response = requests.post(url, json=body, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()

    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")

    return data.get("data", {})


def get_services() -> list[dict]:
    """Fetch all services in the environment."""
    query = """
    query GetServices($projectId: String!, $environmentId: String!) {
      environment(id: $environmentId) {
        services(first: 100) {
          edges {
            node {
              id
              name
            }
          }
        }
      }
    }
    """
    result = graphql_query(query, {
        "projectId": PROJECT_ID,
        "environmentId": ENVIRONMENT_ID,
    })

    services = []
    for edge in result.get("environment", {}).get("services", {}).get("edges", []):
        services.append(edge["node"])
    return services


def set_variable(service_id: str, key: str, value: str) -> None:
    """Set environment variable on a service."""
    query = """
    mutation UpsertProjectEnvironmentVariable(
      $projectId: String!
      $environmentId: String!
      $serviceId: String!
      $name: String!
      $value: String!
    ) {
      projectEnvironmentVariableUpsert(
        input: {
          projectId: $projectId
          environmentId: $environmentId
          serviceId: $serviceId
          name: $name
          value: $value
        }
      ) {
        variable {
          id
          name
          value
        }
      }
    }
    """
    graphql_query(query, {
        "projectId": PROJECT_ID,
        "environmentId": ENVIRONMENT_ID,
        "serviceId": service_id,
        "name": key,
        "value": value,
    })


def main():
    """Set PUBLIC_IMAGE_BASE_URL on all services."""
    print("📡 Fetching services...\n")
    services = get_services()

    if not services:
        print("❌ No services found!")
        sys.exit(1)

    target_services = [s for s in services if s["name"] in ["gifhorn-dashboard", "gifhorn-worker"]]

    if not target_services:
        print(f"❌ Target services not found. Available: {[s['name'] for s in services]}")
        sys.exit(1)

    print(f"🎯 Found {len(target_services)} target services:\n")

    for service in target_services:
        try:
            print(f"   Setting {service['name']}...")
            set_variable(service["id"], "PUBLIC_IMAGE_BASE_URL", PUBLIC_IMAGE_BASE_URL)
            print(f"   ✅ {service['name']}: PUBLIC_IMAGE_BASE_URL set\n")
        except Exception as e:
            print(f"   ❌ {service['name']}: {e}\n")
            sys.exit(1)

    print("✅ All services updated!")
    print(f"\n🚀 Note: Services will auto-redeploy with new env vars.")
    print(f"   Check Railway Dashboard for deployment status.")


if __name__ == "__main__":
    main()
