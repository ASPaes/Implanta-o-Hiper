(() => {
  const panel = document.querySelector('#hiper-panel');
  if (!panel) return;
  const id = Number(panel.dataset.deployment);
  const byId = name => document.getElementById(name);
  let lastDeployment = null;
  let polling = false;
  let busy = false;
  const labels = {success: '✅ Conferido', skipped: '⏭ Já configurado', running: '⏳ Executando',
    completed: 'Etapas selecionadas concluídas', paused: 'Execução pausada',
    executando: '⏳ Executando', waiting_user: '⚠ Aguardando operador', awaiting_auth: '🔐 Aguardando login',
    failed: '❌ Falha', blocked: '⚠ Bloqueado', pendente: 'Pendente', concluida: 'Concluída em simulação'};
  function feedback(message, error = false) {
    byId('hiper-feedback').textContent = message;
    byId('hiper-feedback').className = error ? 'alert error' : 'notice';
  }
  async function request(url, data) {
    const options = {headers: {'X-CSRF-Token': panel.dataset.csrf}, cache: 'no-store'};
    if (data !== undefined) Object.assign(options, {method: 'POST',
      body: JSON.stringify(data), headers: {...options.headers, 'Content-Type': 'application/json'}});
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok) {
      if (result.candidates?.length) {
        const select = byId('store-choice');
        select.replaceChildren(new Option('Selecione uma filial', ''));
        result.candidates.forEach(store => select.add(new Option(`${store.name} · ${store.cnpj} · ${store.id}`, store.id)));
        byId('store-choice-label').hidden = false;
      }
      throw new Error([result.error_code, result.error, result.action].filter(Boolean).join(' · '));
    }
    return result;
  }
  async function action(fn) {
    if (busy) return;
    busy = true;
    const controls = [...panel.querySelectorAll('button')];
    controls.forEach(button => { button.disabled = true; });
    try { await fn(); } catch (error) { feedback(error.message || 'Falha de conexão com o integrador.', true); }
    finally { busy = false; controls.forEach(button => { button.disabled = false; }); }
  }
  function render(deployment) {
    if (!lastDeployment) {
      byId('hiper-mode').value = deployment.execution_mode;
      panel.querySelectorAll('[name="step"]').forEach(el => {el.checked = deployment.selected_steps.includes(el.value);});
    }
    lastDeployment = deployment;
    byId('deployment-status').textContent = labels[deployment.status] || deployment.status;
    byId('store-name').textContent = deployment.hiper_store_name || 'Não localizada';
    byId('store-cnpj').textContent = deployment.hiper_store_cnpj || '—';
    byId('store-id').textContent = deployment.hiper_store_id || '—';
    byId('store-domain').textContent = deployment.hiper_base_url || '—';
    const list = byId('hiper-steps');
    list.replaceChildren();
    deployment.steps.forEach(step => {
      const item = document.createElement('li');
      const name = document.createElement('span');
      const status = document.createElement('span');
      name.textContent = step.step_key.replaceAll('_', ' ');
      status.textContent = `${labels[step.status] || step.status} · ${step.execution_mode} · ${step.attempts} tentativa(s)`;
      item.append(name, status); list.append(item);
      if (step.error_code) {
        const error = document.createElement('li');
        error.className = 'error-text';
        error.textContent = `${step.error_code}: ${step.error_message_sanitized || ''} ${step.recommended_action || ''}`;
        list.append(error);
      }
    });
    byId('hiper-history').replaceChildren();
    deployment.history.slice(-20).reverse().forEach(event => {
      const item = document.createElement('li');
      item.textContent = `${event.occurred_at} · ${event.actor} · ${event.action}`;
      byId('hiper-history').append(item);
    });
  }
  async function refresh() {
    if (polling) return;
    polling = true;
    try { render(await request(`/api/deployments/${id}`)); }
    catch (error) { feedback(error.message, true); }
    finally { polling = false; }
  }
  const sessionData = () => ({deployment_id: id, domain: byId('hiper-domain').value.trim()});
  byId('session-open').addEventListener('click', () => action(async () => {
    const result = await request('/api/hiper/session/open', sessionData());
    byId('session-message').textContent = result.message;
    feedback(result.message);
  }));
  byId('session-status').addEventListener('click', () => action(async () => {
    const params = new URLSearchParams(sessionData());
    const result = await request(`/api/hiper/session/status?${params}`);
    byId('session-message').textContent = `Sessão autenticada: ${result.hiper_base_url}`;
    feedback('Sessão verificada e salva para este domínio.');
  }));
  byId('resolve-store').addEventListener('click', () => action(async () => {
    await request('/api/hiper/resolve-store', {...sessionData(), selected_store_id: byId('store-choice').value});
    byId('store-choice-label').hidden = true;
    byId('store-choice').value = '';
    byId('real-confirmed').checked = false;
    feedback('Filial identificada e CNPJ conferido. Revise os dados antes de executar.');
    await refresh();
  }));
  const runData = () => ({mode: byId('hiper-mode').value,
    steps: [...panel.querySelectorAll('[name="step"]:checked')].map(el => el.value),
    operator: byId('hiper-operator').value, confirmed: byId('real-confirmed').checked,
    accountant_approved: byId('accountant-approved').checked});
  async function run(resume) {
    const data = runData();
    if (!data.steps.length) throw new Error('Selecione pelo menos uma etapa.');
    if (data.mode === 'real' && (!data.confirmed || !data.operator.trim()))
      throw new Error('Informe o operador e confirme explicitamente a escrita na filial.');
    await request(`/api/deployments/${id}/${resume ? 'resume' : 'run'}`, data);
    feedback('Execução iniciada. Acompanhe o progresso por etapa.');
    await refresh();
  }
  byId('hiper-run-form').addEventListener('submit', event => {event.preventDefault(); action(() => run(false));});
  byId('resume-button').addEventListener('click', () => action(() => run(true)));
  byId('pause-button').addEventListener('click', () => action(async () => {
    const result = await request(`/api/deployments/${id}/pause`, {});
    feedback(result.message);
  }));
  byId('hiper-mode').addEventListener('change', () => {byId('real-confirmed').checked = false;});
  refresh();
  const timer = setInterval(() => {
    if (!document.hidden && !busy && (!lastDeployment || lastDeployment.status === 'running')) refresh();
  }, 1500);
  window.addEventListener('pagehide', () => clearInterval(timer));
})();
