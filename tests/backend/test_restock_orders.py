"""
Tests for restocking order API endpoints and the demand cost fields they rely on.
"""
from datetime import datetime, timedelta


def _forecasts(client):
    response = client.get("/api/demand")
    assert response.status_code == 200
    return {f["item_sku"]: f for f in response.json()}


class TestDemandCostFields:
    """Demand forecasts must carry the data restocking needs."""

    def test_demand_forecasts_have_cost_fields(self, client):
        """Test that every forecast has unit cost, lead time and supplier."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        for forecast in response.json():
            assert isinstance(forecast["unit_cost"], (int, float))
            assert forecast["unit_cost"] > 0
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["lead_time_days"] > 0
            assert isinstance(forecast["supplier_name"], str)
            assert forecast["supplier_name"]


class TestRestockOrderEndpoints:
    """Test suite for restocking order endpoints."""

    def test_create_restock_order(self, client):
        """Test submitting a valid order recomputes totals from server data."""
        forecasts = _forecasts(client)
        widget = forecasts["WDG-001"]
        filter_item = forecasts["FLT-405"]

        payload = {
            "items": [
                {"sku": "WDG-001", "quantity": 100},
                {"sku": "FLT-405", "quantity": 50},
            ],
            "budget": 10000,
        }
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        expected_total = round(
            100 * widget["unit_cost"] + 50 * filter_item["unit_cost"], 2
        )
        assert abs(order["total_value"] - expected_total) < 0.01
        assert order["status"] == "Submitted"
        assert order["budget"] == 10000
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == 2

        for line in order["items"]:
            assert abs(line["line_total"] - line["quantity"] * line["unit_cost"]) < 0.01

    def test_restock_order_lead_time_is_longest_line(self, client):
        """Test that order lead time is the max line lead time and sets delivery date."""
        forecasts = _forecasts(client)
        expected_lead = max(
            forecasts["WDG-001"]["lead_time_days"],
            forecasts["MTR-304"]["lead_time_days"],
        )

        response = client.post(
            "/api/restock-orders",
            json={
                "items": [
                    {"sku": "WDG-001", "quantity": 1},
                    {"sku": "MTR-304", "quantity": 1},
                ],
                "budget": 100000,
            },
        )
        assert response.status_code == 201

        order = response.json()
        assert order["lead_time_days"] == expected_lead

        submitted = datetime.fromisoformat(order["submitted_date"])
        delivery = datetime.fromisoformat(order["estimated_delivery"])
        assert delivery - submitted == timedelta(days=expected_lead)

    def test_restock_order_ignores_client_supplied_prices(self, client):
        """Test that extra price fields in the request cannot change the total."""
        forecasts = _forecasts(client)
        response = client.post(
            "/api/restock-orders",
            json={
                "items": [{"sku": "GSK-203", "quantity": 10, "unit_cost": 0.01}],
                "budget": 1000,
            },
        )
        assert response.status_code == 201
        expected = round(10 * forecasts["GSK-203"]["unit_cost"], 2)
        assert abs(response.json()["total_value"] - expected) < 0.01

    def test_restock_order_over_budget(self, client):
        """Test that an order exceeding the budget is rejected."""
        response = client.post(
            "/api/restock-orders",
            json={"items": [{"sku": "MTR-304", "quantity": 100}], "budget": 10},
        )
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()

    def test_restock_order_unknown_sku(self, client):
        """Test that an unknown SKU returns 404."""
        response = client.post(
            "/api/restock-orders",
            json={"items": [{"sku": "NOPE-999", "quantity": 1}], "budget": 1000},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_restock_order_empty_items(self, client):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restock-orders", json={"items": [], "budget": 1000})
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_restock_order_invalid_quantity(self, client):
        """Test that zero or negative quantities are rejected."""
        for quantity in (0, -5):
            response = client.post(
                "/api/restock-orders",
                json={"items": [{"sku": "WDG-001", "quantity": quantity}], "budget": 1000},
            )
            assert response.status_code == 400

    def test_restock_order_duplicate_sku(self, client):
        """Test that the same SKU twice in one order is rejected."""
        response = client.post(
            "/api/restock-orders",
            json={
                "items": [
                    {"sku": "WDG-001", "quantity": 1},
                    {"sku": "WDG-001", "quantity": 2},
                ],
                "budget": 1000,
            },
        )
        assert response.status_code == 400

    def test_restock_order_missing_fields(self, client):
        """Test that a malformed body fails validation."""
        response = client.post("/api/restock-orders", json={"items": []})
        assert response.status_code == 422

    def test_get_restock_orders_includes_submitted_order(self, client):
        """Test that a submitted order appears in the list, newest first."""
        first = client.post(
            "/api/restock-orders",
            json={"items": [{"sku": "WDG-001", "quantity": 1}], "budget": 1000},
        ).json()
        second = client.post(
            "/api/restock-orders",
            json={"items": [{"sku": "FLT-405", "quantity": 1}], "budget": 1000},
        ).json()

        response = client.get("/api/restock-orders")
        assert response.status_code == 200

        ids = [o["id"] for o in response.json()]
        assert first["id"] in ids
        assert second["id"] in ids
        assert ids.index(second["id"]) < ids.index(first["id"])
