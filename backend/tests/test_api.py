import pytest
from fastapi.testclient import TestClient
from backend.app.main import app


client = TestClient(app)


class TestAPI:
    def test_health_endpoint(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "weights" in data
        assert "bayesian_threshold" in data

    def test_config_endpoint(self):
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "default_weights" in data
        assert data["bayesian_min_reviews"] == 50

    def test_search_validation_fails_on_empty_query(self):
        response = client.post("/api/search", json={"query": "a"})  # query too short (min length 2)
        assert response.status_code == 422

    def test_search_validation_fails_on_negative_budget(self):
        response = client.post("/api/search", json={"query": "phone", "max_price": -500})
        assert response.status_code == 422

    def test_search_endpoint_success(self):
        payload = {
            "query": "smartphone",
            "max_price": 20000,
            "min_rating": 4.0,
            "requirements": ["8GB RAM", "AMOLED", "5G"],
            "allow_over_budget": False,
        }
        response = client.post("/api/search", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["query"] == "smartphone"
        assert data["max_price"] == 20000.0
        assert data["analyzed_count"] > 0
        assert len(data["top_5"]) <= 5
        assert len(data["top_5"]) > 0

        # Check top 1 product
        top1 = data["top_5"][0]
        assert top1["rank"] == 1
        assert "name" in top1
        assert "best_price" in top1
        assert top1["best_price"] <= 20000.0
        assert "scoring" in top1
        assert "bayesian_rating" in top1["scoring"]
        assert "overall_score" in top1["scoring"]
        assert "review_confidence_score" in top1["scoring"]
