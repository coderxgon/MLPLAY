/* MLPlay admin panel JS — modals for user actions, order approvals, bind, toasts */
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove('show'), 2600);
}

function openModal(html) {
  document.getElementById('modal-box').innerHTML = html;
  document.getElementById('modal').classList.remove('hidden');
}
function closeModal() {
  document.getElementById('modal').classList.add('hidden');
}
document.addEventListener('click', (e) => {
  if (e.target.id === 'modal') closeModal();
});

async function postJSON(url, data, confirmText) {
  if (confirmText && !confirm('Are you sure?')) return;
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    const j = await r.json().catch(() => ({}));
    if (j && j.ok === false) toast(j.error || 'Operation failed');
    else toast('✅ Done');
    setTimeout(() => location.reload(), 700);
  } catch (e) {
    toast('❌ Request failed');
  }
}

/* ------------ user actions (ban / suspend / freeze / add / remove) ------------ */
function userAction(tgId, action) {
  const labels = {
    ban: 'Ban user', unban: 'Unban user', suspend: 'Suspend user',
    unsuspend: 'Unsuspend user', freeze: 'Freeze balance', unfreeze: 'Unfreeze balance',
    add_balance: 'Add balance', remove_balance: 'Remove balance'
  };
  const needAmount = action === 'add_balance' || action === 'remove_balance';
  openModal(`
    <h3>${labels[action]} — TG ${tgId}</h3>
    <div class="stack">
      <input id="m-title" class="inp" placeholder="Notification title (shown to user)">
      ${needAmount ? `<input id="m-amount" class="inp" type="number" step="0.01" min="0" placeholder="Amount (₱)">` : ''}
      <textarea id="m-remark" class="inp" rows="3" placeholder="Remark / reason (shown to user)"></textarea>
      <div class="row">
        <button class="btn primary grow" onclick="doUserAction(${tgId},'${action}')">Confirm</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
      </div>
    </div>`);
}

async function doUserAction(tgId, action) {
  const payload = {
    tg_id: tgId, action,
    title: document.getElementById('m-title').value,
    remark: document.getElementById('m-remark').value
  };
  const amt = document.getElementById('m-amount');
  if (amt) payload.amount = parseFloat(amt.value) || 0;
  closeModal();
  await postJSON('/admin/users/action', payload);
}

/* ------------ wallet binding (admin override) ------------ */
function bindUser(tgId) {
  openModal(`
    <h3>🏦 Set wallet/bank binding — TG ${tgId}</h3>
    <p class="muted">This overwrites the user's binding (the only way to change it).</p>
    <div class="stack">
      <input id="b-name" class="inp" placeholder="Wallet / bank name (GCash, Maya, Bank…)">
      <input id="b-account" class="inp" placeholder="Account / wallet number">
      <input id="b-holder" class="inp" placeholder="Account holder name">
      <div class="row">
        <button class="btn primary grow" onclick="doBind(${tgId})">Save binding</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
      </div>
    </div>`);
}

async function doBind(tgId) {
  const payload = {
    tg_id: tgId,
    bind_name: document.getElementById('b-name').value,
    bind_account: document.getElementById('b-account').value,
    bind_holder: document.getElementById('b-holder').value
  };
  closeModal();
  await postJSON('/admin/users/bind', payload);
}

/* ------------ order approvals (deposit / withdrawal) ------------ */
function orderAction(orderId, action) {
  const labels = {approve: 'Approve request', reject: 'Reject request', reject_ban: 'Reject + Ban user'};
  const needRemark = action !== 'approve';
  openModal(`
    <h3>${labels[action]} — #${orderId}</h3>
    <div class="stack">
      ${needRemark ? `<textarea id="o-remark" class="inp" rows="3" placeholder="Remark (required — shown to user)"></textarea>` :
                      `<textarea id="o-remark" class="inp" rows="2" placeholder="Optional remark"></textarea>`}
      <div class="row">
        <button class="btn primary grow" onclick="doOrderAction(${orderId},'${action}')">Confirm</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
      </div>
    </div>`);
}

async function doOrderAction(orderId, action) {
  const remark = document.getElementById('o-remark').value || '';
  if ((action === 'reject' || action === 'reject_ban') && !remark.trim()) {
    toast('⚠️ Remark is required for rejection');
    return;
  }
  closeModal();
  await postJSON('/admin/order/action', {order_id: orderId, action, remark});
}