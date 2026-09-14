/* MLPlay Mini App — single-page app logic */
(function () {
  'use strict';

  var tg = null;
  try { tg = window.Telegram && window.Telegram.WebApp; } catch (e) { tg = null; }
  if (tg) { tg.ready(); tg.expand(); }
  else { try { document.body.classList.add('browser'); } catch (e) {} }

  var initData = (tg && tg.initData) || '';
  var devUid = localStorage.getItem('mlplay_dev_uid') || '';

  var app = document.getElementById('app');
  var view = (location.hash || '#home').replace('#', '') || 'home';
  var cache = {};

  function fmt(n) { return '\u20B1' + Number(n || 0).toLocaleString('en-PH', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }

  function toast(msg) {
    var t = document.createElement('div');
    t.className = 'toast show';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.classList.remove('show'); setTimeout(function () { t.remove(); }, 300); }, 2400);
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }

  function api(path, opts) {
    opts = opts || {};
    var headers = {'X-Init-Data': initData};
    if (opts.headers) Object.assign(headers, opts.headers);
    if (devUid) headers['X-Dev-Uid'] = devUid;
    return fetch('/miniapp' + path, {
      method: opts.method || 'GET',
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined
    }).then(function (r) {
      return r.json().then(function (j) {
        if (j && j.error === 'AUTH_FAILED' && !devUid) {
          var uid = prompt('Dev mode: enter your Telegram user ID');
          if (uid) { localStorage.setItem('mlplay_dev_uid', uid); devUid = uid; location.reload(); }
          throw new Error('auth');
        }
        if (j && j.error === 'DEV_UID_REQUIRED' && !devUid) {
          var u2 = prompt('Dev mode: enter your Telegram user ID');
          if (u2) { localStorage.setItem('mlplay_dev_uid', u2); devUid = u2; location.reload(); }
          throw new Error('auth');
        }
        return j;
      });
    });
  }

  function me() {
    if (!cache.me) cache.me = api('/me');
    return cache.me;
  }

  function go(v) {
    view = v;
    location.hash = '#' + v;
    render();
    document.getElementById('tabbar').querySelectorAll('button').forEach(function (b) {
      b.classList.toggle('on', b.dataset.view === v);
    });
    if (tg) tg.HapticFeedback && tg.HapticFeedback.impactOccurred('light');
    window.scrollTo(0, 0);
  }

  function el(html) { app.innerHTML = html; }
  function lazy(fn) { el('<div class="center muted"><span class="spin">⚙️</span> Loading…</div>'); fn(); }

  /* ---------------- views ---------------- */
  function render() {
    if (view === 'home') return renderHome();
    if (view === 'deposit') return renderDeposit();
    if (view === 'withdraw') return renderWithdraw();
    if (view === 'promo') return renderPromo();
    if (view === 'history') return renderHistory();
    if (view === 'promotions') return renderPromotions();
    if (view === 'leaderboard') return renderLeaderboard();
    renderHome();
  }

  function renderHome() {
    lazy(function () {
      me().then(function (m) {
        if (!m || !m.ok) return el('<div class="center">Login expired — restart the app 🫠</div>');
        var u = m.user, r = m.rank;
        var badge = u.is_banned ? '<span class="badge rejected">BANNED</span>' :
                    u.is_suspended ? '<span class="badge pending">SUSPENDED</span>' : '';
        el(
          '<div class="view">' +
          '<div class="balance-card">' +
          '<div class="lbl">💰 MAIN BALANCE ' + badge + '</div>' +
          '<div class="amt">' + fmt(u.balance) + '</div>' +
          '<div class="row"><span class="rank-pill">' + (r.emoji || '★') + ' ' + esc(r.name) + '</span>' +
          '<span>🎯 Bets: ' + u.valid_bets + '</span><span>🎁 Rewards: ' + fmt(u.total_rewards) + '</span></div>' +
          '</div>' +
          '<div class="grid2">' +
          '<button class="action-btn gold" onclick="mlp.go(\'deposit\')">💰<span>Deposit</span></button>' +
          '<button class="action-btn cyan" onclick="mlp.go(\'withdraw\')">💸<span>Withdraw</span></button>' +
          '<button class="action-btn" onclick="mlp.go(\'promo\')">🎁<span>Promo Code</span></button>' +
          '<button class="action-btn" onclick="mlp.go(\'history\')">🧾<span>History</span></button>' +
          '</div>' +
          '<div class="card" style="margin-top:12px">' +
          '<h3>👤 Player snapshot</h3>' +
          '<div class="tx-row"><div class="tx-ic">🏅</div><div><b>Rank</b><small>' + esc(r.tier) + ' ' + esc(r.name) + ' • max bet ' + fmt(r.max_bet) + '</small></div></div>' +
          '<div class="tx-row"><div class="tx-ic">💳</div><div><b>Deposits</b><small>lifetime</small></div><div class="amt in">' + fmt(u.total_deposit) + '</div></div>' +
          '<div class="tx-row"><div class="tx-ic">💸</div><div><b>Withdrawn</b><small>lifetime</small></div><div class="amt out">' + fmt(u.total_withdraw) + '</div></div>' +
          '<div class="tx-row"><div class="tx-ic">🔄</div><div><b>Turnover</b><small>total wagered</small></div><div class="amt">' + fmt(u.turnover) + '</div></div>' +
          '<div class="tx-row"><div class="tx-ic">🤝</div><div><b>Referral rewards</b><small>convert in bot</small></div><div class="amt in">' + fmt(u.referral_balance) + '</div></div>' +
          '</div>' +
          '<button class="menu-item" onclick="mlp.go(\'promotions\')"><span class="ic">🎉</span><span><b>Promotions & Events</b><small>Bonuses, giveaways, promo codes</small></span><span class="arrow">›</span></button>' +
          '<button class="menu-item" onclick="mlp.go(\'leaderboard\')"><span class="ic">🏆</span><span><b>Leaderboard</b><small>Top players this era</small></span><span class="arrow">›</span></button>' +
          '</div>');
      }).catch(function () { el('<div class="center">Cannot reach MLPlay — try again later ⚡</div>'); });
    });
  }

  /* ---------------- deposit ---------------- */
  var depositState = {methods: [], chosen: null};

  function renderDeposit() {
    lazy(function () {
      api('/deposit-methods').then(function (j) {
        if (!j.ok) return el('<div class="center">' + esc(j.error || 'Error') + '</div>');
        depositState.methods = j.methods;
        if (!j.methods.length) return el('<div class="view"><div class="card"><h3>No payment methods yet</h3><p class="muted">Check back soon ⚡</p></div><button class="menu-item" onclick="mlp.go(\'home\')"><span class="arrow">‹ Home</span></button></div>');
        var rows = j.methods.map(function (m) {
          return '<button class="menu-item" onclick="mlp.selectDeposit(' + m.id + ')"><span class="ic">💳</span>' +
            '<span><b>' + esc(m.name) + '</b><small>min ' + fmt(m.min) + ' • max ' + fmt(m.max) + '</small></span><span class="arrow">›</span></button>';
        }).join('');
        el('<div class="view"><h3 style="margin-bottom:10px">💰 Select payment method</h3>' + rows +
          '<button class="menu-item" onclick="mlp.go(\'home\')"><span class="arrow">‹ Back</span></button></div>');
      });
    });
  }

  window.mlp = window.mlp || {};
  window.mlp.go = go;
  window.mlp.selectDeposit = function (id) {
    depositState.chosen = depositState.methods.find(function (m) { return m.id === id; });
    var output = [
      '<div class="view"><h3>💳 ' + esc(depositState.chosen.name) + '</h3>',
      '<div class="card">',
      '<div class="qr"><img src="' + depositState.chosen.qr + '" alt="QR"></div>',
      '<p class="center muted">Scan the QR or use the account details</p>',
      '<p class="center muted" style="margin-top:6px">' + esc(depositState.chosen.detail || '') + '</p>',
      '</div>',
      '<label class="inp-lbl">💵 Amount (₱)</label>',
      '<input id="dep-amt" class="inp" type="number" min="' + depositState.chosen.min + '" max="' + depositState.chosen.max + '" step="0.01" placeholder="' + depositState.chosen.min + ' – ' + depositState.chosen.max + '" style="font-size:18px;font-weight:800">',
      '<label class="inp-lbl">📎 Upload receipt / transaction screenshot</label>',
      '<input id="dep-file" type="file" accept="image/*" style="padding:8px">',
      '<div style="height:12px"></div>',
      '<button class="btn" id="dep-submit" onclick="mlp.submitDeposit()">🚀 Submit Deposit</button>',
      '<div style="height:8px"></div>',
      '<button class="menu-item" onclick="mlp.go(\'deposit\')"><span class="arrow">‹ Change method</span></button>',
      '</div>'
    ].join('');
    el(output);
  };

  window.mlp.submitDeposit = function () {
    var amt = parseFloat(document.getElementById('dep-amt').value);
    if (!amt || amt < depositState.chosen.min || amt > depositState.chosen.max) {
      return toast('⚠️ Amount must be between ' + fmt(depositState.chosen.min) + ' and ' + fmt(depositState.chosen.max));
    }
    var btn = document.getElementById('dep-submit');
    btn.disabled = true; btn.textContent = 'Sending… ⏳';
    var file = document.getElementById('dep-file').files[0];
    var receipt = '';
    var proceed = function () {
      api('/deposit', {method: 'POST', body: {method_id: depositState.chosen.id, amount: amt, receipt: receipt}}).then(function (j) {
        if (!j.ok) { btn.disabled = false; btn.textContent = '🚀 Submit Deposit'; return toast('❌ ' + esc(j.error || 'Failed')); }
        el('<div class="view"><div class="ok-big">✅</div><div class="card"><h3 style="text-align:center">Deposit request submitted!</h3>' +
          '<p class="center">Order: <b class="mono">' + esc(j.order_no) + '</b></p>' +
          '<p class="center muted">Your deposit is pending admin approval.\nYou will be notified once approved or rejected. 🔔</p></div>' +
          '<button class="btn gold" onclick="mlp.go(\'history\')">🧾 Track status</button>' +
          '<div style="height:8px"></div>' +
          '<button class="menu-item" onclick="mlp.go(\'home\')"><span class="arrow">‹ Back to home</span></button></div>');
      });
    };
    if (file) {
      var rd = new FileReader();
      rd.onload = function () { receipt = rd.result; proceed(); };
      rd.onerror = function () { toast('❌ Cannot read file'); btn.disabled = false; btn.textContent = '🚀 Submit Deposit'; };
      rd.readAsDataURL(file);
    } else { proceed(); }
  };

  /* ---------------- withdraw ---------------- */
  function renderWithdraw() {
    lazy(function () {
      api('/withdraw-channels').then(function (j) {
        if (!j.ok) return el('<div class="center">' + esc(j.error || 'Error') + '</div>');
        if (!j.bound) {
          el('<div class="view"><div class="ok-big">🔒</div>' +
            '<div class="card"><h3>Bind your wallet first</h3>' +
            '<p style="font-size:13px;color:#d8ccff">Withdrawals are sent <b>only</b> to your permanently bound wallet/bank.</p>' +
            '<p class="muted" style="margin-top:8px">' + esc(j.hint || '') + '</p></div>' +
            '<button class="menu-item" onclick="mlp.go(\'home\')"><span class="arrow">‹ Back</span></button></div>');
          return;
        }
        wdState.binding = j.binding;
        el(
          '<div class="view"><h3>💸 Withdraw</h3>' +
          '<div class="card">' +
          '<div class="tx-row"><div class="tx-ic">🏦</div>' +
          '<div><b>' + esc(j.binding.wallet) + ' <span class="badge approved">BOUND</span></b>' +
          '<small>Account: <span class="mono">' + esc(j.binding.account_masked) + '</span><br>Holder: ' + esc(j.binding.holder) + '</small></div>' +
          '</div>' +
          '<p class="muted" style="margin-top:8px">🔒 This bound wallet is used for every withdrawal — it cannot be changed by the player.</p>' +
          '<label class="inp-lbl">💵 Amount (₱)</label>' +
          '<input id="wd-amt" class="inp" type="number" min="1" max="50000" step="0.01" style="font-size:18px;font-weight:800">' +
          '</div>' +
          '<button class="btn gold" id="wd-submit" onclick="mlp.submitWithdraw()">💸 Submit Withdrawal</button>' +
          '<div style="height:8px"></div>' +
          '<button class="menu-item" onclick="mlp.go(\'home\')"><span class="arrow">‹ Back</span></button>' +
          '</div>');
      });
    });
  }

  window.mlp.submitWithdraw = function () {
    var amt = parseFloat(document.getElementById('wd-amt').value);
    if (!amt || amt < 1 || amt > 50000) {
      return toast('⚠️ Amount must be between ₱1 and ₱50,000');
    }
    var btn = document.getElementById('wd-submit');
    btn.disabled = true; btn.textContent = 'Sending… ⏳';
    api('/withdraw', {method: 'POST', body: {amount: amt, channel_id: 0}}).then(function (j) {
      if (!j.ok) { btn.disabled = false; btn.textContent = '💸 Submit Withdrawal'; return toast('❌ ' + esc(j.error || 'Failed')); }
      el('<div class="view"><div class="ok-big">💸</div><div class="card"><h3 style="text-align:center">Withdrawal request submitted!</h3>' +
        '<p class="center">Order: <b class="mono">' + esc(j.order_no) + '</b></p>' +
        '<p class="center muted">Sent to your bound wallet (<span class="mono">' + esc(wdState.binding.account_masked) + '</span>).\nPending admin approval — you will be notified. 🔔</p></div>' +
        '<button class="btn gold" onclick="mlp.go(\'history\')">🧾 Track status</button>' +
        '<div style="height:8px"></div>' +
        '<button class="menu-item" onclick="mlp.go(\'home\')"><span class="arrow">‹ Back to home</span></button></div>');
    });
  };

  /* ---------------- promo code ---------------- */
  function renderPromo() {
    me().then(function (m) {
      el(
        '<div class="view"><div class="ok-big">🎁</div>' +
        '<div class="card"><h3>Enter promo code</h3>' +
        '<input id="promo-code" class="inp" placeholder="e.g. ML2026" style="text-transform:uppercase;font-weight:800;letter-spacing:2px">' +
        '<div style="height:12px"></div>' +
        '<button class="btn gold" id="promo-btn" onclick="mlp.submitPromo()">🔥 Redeem</button>' +
        '<p class="center muted" style="margin-top:10px">Codes are given by admins & events. Rewards credit instantly!</p>' +
        '</div>' +
        '<button class="menu-item" onclick="mlp.go(\'home\')"><span class="arrow">‹ Back</span></button></div>');
    });
  }

  window.mlp.submitPromo = function () {
    var code = document.getElementById('promo-code').value.trim();
    if (!code) return toast('⚠️ Type a promo code first');
    var btn = document.getElementById('promo-btn');
    btn.disabled = true; btn.textContent = 'Checking… ⏳';
    api('/promo', {method: 'POST', body: {code: code}}).then(function (j) {
      if (!j.ok) { btn.disabled = false; btn.textContent = '🔥 Redeem'; return toast('❌ ' + esc(j.error || 'Invalid')); }
      el('<div class="view"><div class="ok-big">🎉</div><div class="card"><h3 style="text-align:center">PROMO REDEEMED!</h3>' +
        '<p class="center" style="font-size:26px;font-weight:800;color:var(--gold)">+' + fmt(j.amount) + '</p>' +
        '<p class="center muted">Credited to your balance instantly 💰</p></div>' +
        '<button class="btn" onclick="mlp.go(\'home\')">🏠 Back to home</button></div>');
    });
  }

  /* ---------------- history ---------------- */
  var histKind = 'all';
  var KIND_ICON = {deposit: '💰', withdraw: '💸', promo: '🎁', daily: '🎁', referral: '🤝', convert: '🔄', win: '🏆', bet: '🎯', rank: '🎖️', bind: '🏦', reward: '🎁'};

  function renderHistory() {
    lazy(function () {
      api('/history?kind=' + histKind).then(function (j) {
        if (!j.ok) return el('<div class="center">Error</div>');
        var chips = [['all', 'All'], ['deposit', 'Deposits'], ['withdraw', 'Withdrawals'], ['bet', 'Bets'], ['reward', 'Rewards']]
          .map(function (c) { return '<button class="chip ' + (histKind === c[0] ? 'on' : '') + '" onclick="mlp.hist(\'' + c[0] + '\')">' + c[1] + '</button>'; }).join('');
        var rows = j.rows.length ? j.rows.map(function (r) {
          var icon = KIND_ICON[r.kind] || '🧾';
          var amtCls = r.direction === 'out' ? 'out' : 'in';
          var sign = r.direction === 'out' ? '-' : '+';
          return '<div class="tx-row"><div class="tx-ic">' + icon + '</div><div><b>' + esc(r.title || r.kind) + '</b>' +
            '<small>' + esc(r.time) + ' • <span class="mono">' + esc(r.id) + '</span><br>' + esc(r.remark || '') + '</small></div>' +
            '<div class="amt"><span class="amt ' + amtCls + '">' + sign + fmt(r.amount) + '</span><br><span class="badge ' + r.status + '">' + r.status + '</span></div></div>';
        }).join('') : '<div class="center muted" style="padding:24px">No transactions yet — go play! ⚡</div>';
        el('<div class="view"><h3>🧾 Transaction history</h3><div class="chip-row">' + chips + '</div>' +
          '<div class="card">' + rows + '</div>' +
          '<button class="menu-item" onclick="mlp.go(\'home\')"><span class="arrow">‹ Back</span></button></div>');
      });
    });
  }

  window.mlp.hist = function (k) { histKind = k; renderHistory(); };

  /* ---------------- promotions ---------------- */
  function renderPromotions() {
    lazy(function () {
      api('/promotions').then(function (j) {
        if (!j.ok) return el('<div class="center">Error</div>');
        var cards = j.promotions.length ? j.promotions.map(function (p) {
          return '<div class="card">' +
            (p.image ? '<img class="promo-img" src="' + esc(p.image) + '">' : '') +
            '<h3>🎉 ' + esc(p.title) + '</h3>' +
            '<p style="white-space:pre-wrap;font-size:13px;color:#d8ccff">' + esc(p.text) + '</p>' +
            (p.url ? '<div style="height:8px"></div>' + '<a class="btn gold" style="text-align:center;display:block" href="' + esc(p.url) + '" target="_blank">Claim Now</a>' : '') +
            '</div>';
        }).join('') : '<div class="card"><h3>Nothing yet 🎁</h3><p class="muted">Promotions are coming soon — follow the channel!</p></div>';
        el('<div class="view"><h3>🎁 Promotions & Events</h3>' + cards +
          '<button class="menu-item" onclick="mlp.go(\'promo\')"><span class="ic">🔑</span><span><b>Enter Promo Code</b><small>Redeem codes here</small></span><span class="arrow">›</span></button>' +
          '<button class="menu-item" onclick="mlp.go(\'home\')"><span class="arrow">‹ Back</span></button></div>');
      });
    });
  }

  /* ---------------- leaderboard ---------------- */
  var lbBy = 'balance';
  function renderLeaderboard() {
    lazy(function () {
      api('/leaderboard?by=' + lbBy).then(function (j) {
        if (!j.ok) return el('<div class="center">Error</div>');
        var chips = [['balance', '💰 Balance'], ['turnover', '🔄 Turnover'], ['deposit', '💵 Deposits'], ['bets', '🎯 Bets']]
          .map(function (c) { return '<button class="chip ' + (lbBy === c[0] ? 'on' : '') + '" onclick="mlp.lb(\'' + c[0] + '\')">' + c[1] + '</button>'; }).join('');
        var rows = j.rows.map(function (r, i) {
          return '<div class="leader-row"><div class="pos ' + (i < 3 ? 'top' : '') + '">' + (i + 1) + '</div>' +
            '<div><b>' + esc(r.name) + '</b><small> ' + esc(r.rank) + '</small></div>' +
            '<div class="val">' + fmt(r.value) + '</div></div>';
        }).join('');
        el('<div class="view"><h3>🏆 Leaderboard</h3><div class="chip-row">' + chips + '</div>' +
          '<div class="card">' + rows + '</div>' +
          '<button class="menu-item" onclick="mlp.go(\'home\')"><span class="arrow">‹ Back</span></button></div>');
      });
    });
  }
  window.mlp.lb = function (b) { lbBy = b; renderLeaderboard(); };

  /* ---------------- boot ---------------- */
  document.getElementById('btn-home').addEventListener('click', function () { go('home'); });
  document.getElementById('tabbar').querySelectorAll('button').forEach(function (b) {
    b.addEventListener('click', function () { go(b.dataset.view); });
  });
  window.addEventListener('hashchange', function () {
    var v = (location.hash || '#home').replace('#', '') || 'home';
    view = v;
    render();
    document.getElementById('tabbar').querySelectorAll('button').forEach(function (b) {
      b.classList.toggle('on', b.dataset.view === v);
    });
  });
  render();
})();