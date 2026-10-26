import json

from app.automation.hiper.resolver import HiperStore
from app.persistence.repositories import DeploymentRepository
from app.persistence.hiper import HiperRepository


def headers(client):
    token = client.get("/api/hiper/csrf").get_json()["csrf_token"]
    return {"X-CSRF-Token": token}


def create(client):
    response = client.post("/api/deployments", json={"contract_id": "1042"}, headers=headers(client))
    assert response.status_code == 201
    return response.get_json()["deployment_id"]


def test_api_import_status_panel_and_simulation(app, client):
    deployment_id = create(client)
    assert client.get(f"/deployments/{deployment_id}/hiper").status_code == 200
    assert "Conectar e implantar" in client.get(f"/deployments/{deployment_id}/hiper").get_data(as_text=True)
    response = client.post(f"/api/deployments/{deployment_id}/run", json={"mode": "simulation"}, headers=headers(client))
    assert response.status_code == 202
    extension = app.extensions["hiper"]
    async def finish():
        await extension["service"].tasks[deployment_id]
    extension["runtime"].call(finish())
    result = client.get(f"/api/deployments/{deployment_id}").get_json()
    assert result["status"] == "completed"
    completed = next(step for step in result["steps"] if step["step_key"] == "loja_config")
    assert completed["status"] == "success" and completed["execution_mode"] == "simulation"
    assert completed["evidence_reference"].startswith("simulation://")
    assert result["history"]
    extension["close"]()


def test_csrf_host_origin_and_invalid_json_are_rejected(client):
    assert client.post("/api/deployments", json={"contract_id": "1042"}).status_code == 403
    assert client.get("/api/hiper/csrf", headers={"Host": "attacker.test"}).status_code == 403
    token = headers(client)
    assert client.post("/api/deployments", json={"contract_id": "1042"}, headers={**token, "Origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/deployments", json=["invalid"], headers=token).status_code == 400


def test_missing_deployment_and_unknown_steps(client):
    assert client.get("/api/deployments/99999").status_code == 404
    deployment_id = create(client)
    response = client.post(f"/api/deployments/{deployment_id}/run", json={"steps": ["invented"]}, headers=headers(client))
    assert response.status_code == 422


def test_real_requires_server_flag_api_source_and_exact_boolean(app, client):
    deployment_id = create(client)
    repo = HiperRepository(app.config["DATABASE"])
    repo.context(deployment_id, "https://one.hiper.com.br", HiperStore("one", "Empresa", "12345678000195", "https://one.hiper.com.br/settings"))
    payload = {"mode": "real", "confirmed": True, "operator": "Operador"}
    response = client.post(f"/api/deployments/{deployment_id}/run", json=payload, headers=headers(client))
    assert response.status_code == 403
    service = app.extensions["hiper"]["service"]
    service.config["REAL_HIPER_AUTOMATION_ENABLED"] = True
    response = client.post(f"/api/deployments/{deployment_id}/run", json=payload, headers=headers(client))
    assert response.status_code == 403  # Fixture cannot be promoted to a real client.
    assert response.get_json()["error_code"] == "real_mode_disabled"
    app.extensions["hiper"]["close"]()


def test_secret_contract_data_never_returned(app, client):
    client.post("/deployments/import", data={"contract_id": "1042"})
    deployment_id = DeploymentRepository(app.config["DATABASE"]).list_all()[0].id
    result = client.get(f"/api/deployments/{deployment_id}")
    assert "CONTRATOS_API_TOKEN" not in result.get_data(as_text=True)
    assert client.get("/api/contracts/1042").status_code == 200
