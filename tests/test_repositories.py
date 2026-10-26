from app.models import STEP_KEYS
from app.persistence.db import init_db
from app.persistence.repositories import DeploymentRepository, StepRepository


def test_create_deployment_and_seven_steps(app):
    deployments = DeploymentRepository(app.config["DATABASE"])
    steps = StepRepository(app.config["DATABASE"])
    deployment = deployments.create("1042", {"company": {"legal_name": "A"}})
    assert deployment.status == "rascunho"
    assert [step.step_key for step in steps.list_for_deployment(deployment.id)] == list(STEP_KEYS)


def test_secrets_are_redacted_before_persistence(app):
    deployments = DeploymentRepository(app.config["DATABASE"])
    deployment = deployments.create("1042", {
        "company": {"legal_name": "A"},
        "password": "never-store-this",
        "nested": {"api_token": "also-secret"},
    })
    stored = deployments.get(deployment.id).data
    assert stored["password"] == "[REDACTED]"
    assert stored["nested"]["api_token"] == "[REDACTED]"


def test_existing_completed_deployment_receives_pending_user_step(app):
    from app.persistence.db import connect

    deployments = DeploymentRepository(app.config["DATABASE"])
    steps = StepRepository(app.config["DATABASE"])
    deployment = deployments.create("1042", {"company": {"legal_name": "A"}})
    with connect(app.config["DATABASE"]) as connection:
        connection.execute(
            """UPDATE deployment_steps SET status = 'concluida'
               WHERE deployment_id = ? AND step_key != 'usuarios'""",
            (deployment.id,),
        )
        connection.execute(
            "DELETE FROM deployment_steps WHERE deployment_id = ? AND step_key = 'usuarios'",
            (deployment.id,),
        )
        connection.execute(
            "UPDATE deployments SET status = 'homologacao_concluida' WHERE id = ?",
            (deployment.id,),
        )
    init_db(app.config["DATABASE"])
    assert steps.get(deployment.id, "usuarios").status == "pendente"
    assert deployments.get(deployment.id).status == "aguardando_intervencao"
