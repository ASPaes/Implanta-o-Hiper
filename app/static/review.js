function setupRepeatableBlocks(addId, listId, templateId, blockSelector, removeSelector) {
  const addButton = document.querySelector(addId);
  const list = document.querySelector(listId);
  const template = document.querySelector(templateId);
  if (!addButton || !list || !template) return;

  function updateRemoveButtons() {
    const blocks = list.querySelectorAll(blockSelector);
    blocks.forEach((block) => {
      block.querySelector(removeSelector).disabled = blocks.length <= 1;
    });
  }

  addButton.addEventListener('click', () => {
    const newBlock = template.content.cloneNode(true);
    const firstInput = newBlock.querySelector('input');
    list.append(newBlock);
    updateRemoveButtons();
    firstInput?.focus();
  });

  list.addEventListener('click', (event) => {
    const removeButton = event.target.closest(removeSelector);
    if (!removeButton || removeButton.disabled) return;
    const block = removeButton.closest(blockSelector);
    const blocks = [...list.querySelectorAll(blockSelector)];
    if (!block || blocks.length <= 1) return;
    const nextBlock = block.nextElementSibling || block.previousElementSibling;
    // Keep the add control available when the first user is removed.
    if (block.contains(addButton)) {
      const nextLegend = nextBlock.querySelector('legend');
      nextLegend.insertBefore(addButton, nextLegend.querySelector(removeSelector));
    }
    block.remove();
    updateRemoveButtons();
    nextBlock.querySelector('input')?.focus();
  });

  updateRemoveButtons();
}
setupRepeatableBlocks('#add-user', '#users-list', '#user-block-template', '[data-user-block]', '[data-remove-user]');
setupRepeatableBlocks('#add-caixa', '#caixas-list', '#caixa-block-template', '[data-caixa-block]', '[data-remove-caixa]');

const bankName = document.querySelector('[name="instituicao_financeira.bank_name"]');
const clientSuppliers = document.querySelectorAll('[name="fiscal.cliente_fornecedor"], [name="bandeiras_cartao.cliente_fornecedor"]');
if (bankName && clientSuppliers.length) {
  bankName.addEventListener('input', () => {
    clientSuppliers.forEach((field) => { field.value = bankName.value; });
  });
}

const ieExempt = document.querySelector('[name="company.isenta_ie"]');
const ieNumber = document.querySelector('[name="company.inscricao_estadual"]');
if (ieExempt && ieNumber) {
  ieExempt.addEventListener('change', () => {
    ieNumber.disabled = ieExempt.checked;
  });
}

const cnpjInput = document.querySelector('[name="company.cnpj"]');
const cnpjStatus = document.querySelector('#cnpj-lookup-status');
const cnpjButton = document.querySelector('.cnpj-lookup-button');
if (cnpjInput && cnpjStatus && cnpjButton) {
  const companyFields = {
    razao_social: 'company.legal_name',
    nome_fantasia: 'company.trade_name',
    logradouro: 'company.logradouro',
    bairro: 'company.bairro',
    municipio: 'company.municipio',
    uf: 'company.uf',
  };
  const onlyDigits = (value) => value.replace(/\D/g, '');
  let observedCnpj = onlyDigits(cnpjInput.value);
  let activeRequest = null;

  function setStatus(message, state = '') {
    cnpjStatus.textContent = message;
    cnpjStatus.className = `lookup-status${state ? ` is-${state}` : ''}`;
    cnpjStatus.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
  }

  function stopRequest() {
    if (activeRequest) activeRequest.abort();
    activeRequest = null;
    cnpjButton.disabled = false;
  }

  function clearCompanyFields() {
    Object.values(companyFields).forEach((name) => {
      const field = document.querySelector(`[name="${name}"]`);
      if (field) field.value = '';
    });
  }

  async function lookupCnpj() {
    const cnpj = onlyDigits(cnpjInput.value);
    if (cnpj.length !== 14) {
      setStatus('Informe um CNPJ com 14 dígitos.', 'error');
      return;
    }
    stopRequest();
    const controller = new AbortController();
    activeRequest = controller;
    cnpjButton.disabled = true;
    setStatus('Consultando CNPJ...', 'loading');
    try {
      const response = await fetch(
        `${cnpjInput.dataset.lookupUrl}?cnpj=${encodeURIComponent(cnpj)}`,
        { signal: controller.signal }
      );
      const result = await response.json().catch(() => ({}));
      if (controller.signal.aborted || onlyDigits(cnpjInput.value) !== cnpj) return;
      if (!response.ok) throw new Error(result.error || 'Falha ao consultar o CNPJ.');
      Object.entries(companyFields).forEach(([source, name]) => {
        const field = document.querySelector(`[name="${name}"]`);
        if (field) field.value = result[source] || '';
      });
      setStatus('Dados da empresa preenchidos.', 'success');
    } catch (error) {
      if (controller.signal.aborted || onlyDigits(cnpjInput.value) !== cnpj) return;
      setStatus(
        error instanceof TypeError
          ? 'Não foi possível consultar o CNPJ agora. Tente novamente.'
          : error.message || 'Falha ao consultar o CNPJ.',
        'error'
      );
    } finally {
      if (activeRequest === controller) {
        activeRequest = null;
        cnpjButton.disabled = false;
      }
    }
  }

  cnpjInput.addEventListener('input', () => {
    const cnpj = onlyDigits(cnpjInput.value);
    if (cnpj !== observedCnpj) {
      if (observedCnpj.length === 14) clearCompanyFields();
      observedCnpj = cnpj;
    }
    stopRequest();
    if (cnpj.length > 14) setStatus('O CNPJ deve ter 14 dígitos.', 'error');
    else setStatus('');
  });

  cnpjButton.addEventListener('click', lookupCnpj);
}

const bankCnpjInput = document.querySelector('[name="instituicao_financeira.cnpj_banco"]');
const bankCnpjStatus = document.querySelector('#bank-cnpj-lookup-status');
const bankCnpjButton = document.querySelector('[data-cnpj-target="bank"]');
if (bankCnpjInput && bankCnpjStatus && bankCnpjButton) {
  const bankFields = {
    razao_social: 'instituicao_financeira.bank_name',
    nome_fantasia: 'instituicao_financeira.nome_fantasia',
    cep: 'instituicao_financeira.cep',
    numero: 'instituicao_financeira.numero',
  };
  const onlyDigits = (value) => value.replace(/\D/g, '');
  let populatedCnpj = null;
  let activeRequest = null;

  function setStatus(message, state = '') {
    bankCnpjStatus.textContent = message;
    bankCnpjStatus.className = `lookup-status${state ? ` is-${state}` : ''}`;
    bankCnpjStatus.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
  }

  function stopRequest() {
    if (activeRequest) activeRequest.abort();
    activeRequest = null;
    bankCnpjButton.disabled = false;
  }

  function setBankFields(result) {
    Object.entries(bankFields).forEach(([source, name]) => {
      const field = document.querySelector(`[name="${name}"]`);
      if (field) field.value = result[source] || '';
    });
    bankName?.dispatchEvent(new Event('input', { bubbles: true }));
  }

  async function lookupBankCnpj() {
    const cnpj = onlyDigits(bankCnpjInput.value);
    if (cnpj.length !== 14) {
      setStatus('Informe um CNPJ com 14 dígitos.', 'error');
      return;
    }
    stopRequest();
    const controller = new AbortController();
    activeRequest = controller;
    bankCnpjButton.disabled = true;
    setStatus('Consultando CNPJ...', 'loading');
    try {
      const response = await fetch(
        `${bankCnpjInput.dataset.lookupUrl}?cnpj=${encodeURIComponent(cnpj)}`,
        { signal: controller.signal }
      );
      const result = await response.json().catch(() => ({}));
      if (controller.signal.aborted || onlyDigits(bankCnpjInput.value) !== cnpj) return;
      if (!response.ok) throw new Error(result.error || 'Falha ao consultar o CNPJ.');
      setBankFields(result);
      populatedCnpj = cnpj;
      setStatus('Dados do banco preenchidos.', 'success');
    } catch (error) {
      if (controller.signal.aborted || onlyDigits(bankCnpjInput.value) !== cnpj) return;
      setStatus(
        error instanceof TypeError
          ? 'Não foi possível consultar o CNPJ agora. Tente novamente.'
          : error.message || 'Falha ao consultar o CNPJ.',
        'error'
      );
    } finally {
      if (activeRequest === controller) stopRequest();
    }
  }

  bankCnpjInput.addEventListener('input', () => {
    const cnpj = onlyDigits(bankCnpjInput.value);
    stopRequest();
    if (populatedCnpj && cnpj !== populatedCnpj) {
      setBankFields({});
      populatedCnpj = null;
    }
    if (cnpj.length > 14) setStatus('O CNPJ deve ter 14 dígitos.', 'error');
    else setStatus('');
  });

  bankCnpjButton.addEventListener('click', lookupBankCnpj);
}
