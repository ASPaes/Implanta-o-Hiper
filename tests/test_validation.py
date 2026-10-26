from app.services.validation import FIXED_PRODUCT, validate_sections


def valid_data():
    return {
        "company": {"legal_name": "A", "trade_name": "B", "cnpj": "1" * 14, "postal_code": "1" * 8},
        "cliente_padrao": {"nome": "C", "cpf": "1" * 11, "cep": "1" * 8},
        "instituicao_financeira": {"bank_name": "Banco", "cnpj_banco": "1" * 14},
        "produto_ncm": FIXED_PRODUCT.copy(),
        "contador": {"cnpj_contabilidade": "1" * 14},
        "fiscal": {"tax_regime": "", "csosn": "", "icms_rate": ""},
        "bandeiras_cartao": {"credenciadora": "Credenciadora Teste"},
        "usuarios": {"nome": "Cliente", "usuario": "cliente", "perfil": "caixa"},
    }


def test_valid_payload_has_no_errors():
    assert validate_sections(valid_data()) == {}


def test_reports_required_and_format_errors():
    data = valid_data()
    data["company"]["legal_name"] = ""
    data["cliente_padrao"]["cpf"] = "123"
    data["produto_ncm"]["ncm"] = "12"
    errors = validate_sections(data)
    assert errors["company.legal_name"] == "Campo obrigatório"
    assert "11 dígitos" in errors["cliente_padrao.cpf"]
    assert "8 dígitos" in errors["produto_ncm.ncm"]


def test_bank_cnpj_is_required_and_user_profile_is_restricted():
    data = valid_data()
    data["instituicao_financeira"]["cnpj_banco"] = ""
    data["usuarios"]["perfil"] = "suporte"
    errors = validate_sections(data)
    assert errors["instituicao_financeira.cnpj_banco"] == "Campo obrigatório"
    assert errors["usuarios.perfil"] == "Perfil inválido"
