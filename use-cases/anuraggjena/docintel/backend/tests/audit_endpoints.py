"""Test to audit all API endpoints and count them."""
import pytest
from backend.main import app


def test_audit_all_endpoints():
    """Audit all registered API endpoints."""

    routes_by_prefix = {}
    total_endpoints = 0

    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            path = route.path

            # Skip docs/openapi/root
            if path in ['/', '/openapi.json', '/docs', '/redoc']:
                continue

            methods = [m for m in route.methods if m not in ['HEAD', 'OPTIONS']]
            if not methods:
                continue

            # Extract router prefix
            parts = path.split('/')
            if len(parts) >= 4 and parts[1] == 'api' and parts[2] == 'v1':
                prefix = parts[3]
            else:
                prefix = 'other'

            if prefix not in routes_by_prefix:
                routes_by_prefix[prefix] = []

            for method in methods:
                routes_by_prefix[prefix].append(f"{method:6} {path}")
                total_endpoints += 1

    # Print audit report
    print("\n" + "="*80)
    print("API ENDPOINT AUDIT REPORT")
    print("="*80)
    print(f"\nTotal API Endpoints: {total_endpoints}\n")

    for prefix in sorted(routes_by_prefix.keys()):
        routes = routes_by_prefix[prefix]
        print(f"\n{prefix.upper()} Router: {len(routes)} endpoints")
        for route in sorted(routes):
            print(f"  {route}")

    print(f"\n{'='*80}")
    print(f"TOTAL ENDPOINTS: {total_endpoints}")
    print("="*80)

    # Assert we have the expected number of endpoints
    assert total_endpoints > 0, "No API endpoints found!"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
