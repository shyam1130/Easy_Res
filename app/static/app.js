const state = {
  authToken: sessionStorage.getItem("pos-auth-token") || "",
  user: null,
  table: null,
  adminTable: null,
  adminOrder: null,
  allBillHistory: [],
  order: null,
  menu: [],
  cart: new Map(),
};

const $ = (selector) => document.querySelector(selector);
const money = (amount) => `Rs. ${Number(amount || 0).toFixed(2)}`;

async function api(url, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.authToken) headers["X-Auth-Token"] = state.authToken;
  const response = await fetch(url, { ...options, headers });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && state.authToken) {
    clearAuth();
    showLoggedOut();
  }
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  window.setTimeout(() => element.classList.remove("show"), 2600);
}

async function refreshTables() {
  const tables = await api("/api/tables");
  renderTableGrid($("#tables"), tables, state.table, selectTable);
  renderTableGrid($("#admin-tables"), tables, state.adminTable, selectAdminTable);
}

function renderTableGrid(element, tables, selectedTable, onSelect) {
  if (!element) return;
  element.innerHTML = tables.map((table) => `
    <button class="table-card ${table.status.toLowerCase()} ${selectedTable === table.table_number ? "selected" : ""}" data-table="${table.table_number}">
      <span class="table-name">Table ${table.table_number}</span>
      <span class="table-state">${table.status === "EMPTY" ? "EMPTY" : money(table.total_amount)}</span>
    </button>`).join("");
  element.querySelectorAll("[data-table]").forEach((button) => {
    button.addEventListener("click", () => onSelect(Number(button.dataset.table)));
  });
}

async function loadMenu() {
  state.menu = await api("/api/menu");
  const categories = [...new Set(state.menu.map((item) => item.category))].sort();
  const selected = $("#category-filter").value;
  $("#category-filter").innerHTML = `<option value="">All categories</option>${categories.map((name) => `<option>${escapeHtml(name)}</option>`).join("")}`;
  if (categories.includes(selected)) $("#category-filter").value = selected;
  renderMenu();
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function renderMenu() {
  const search = $("#menu-search").value.trim().toLowerCase();
  const category = $("#category-filter").value;
  const visible = state.menu.filter((item) =>
    (!category || item.category === category) &&
    `${item.name} ${item.category}`.toLowerCase().includes(search));
  $("#menu-items").innerHTML = visible.length ? visible.map((item) => `
    <article class="menu-card">
      <div><h3>${escapeHtml(item.name)}</h3><p>${escapeHtml(item.category)} · ${money(item.price)}</p></div>
      <div class="menu-stepper">
        <button class="qty-button" data-cart-item="${item.id}" data-delta="-1" aria-label="Decrease ${escapeHtml(item.name)} pending quantity">−</button>
        <strong>${state.cart.get(item.id) || 0}</strong>
        <button class="add-one" data-cart-item="${item.id}" data-delta="1" aria-label="Increase ${escapeHtml(item.name)} pending quantity">+</button>
      </div>
    </article>`).join("") : '<p class="muted">No matching available items.</p>';
  $("#menu-items").querySelectorAll("[data-cart-item]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = Number(button.dataset.cartItem);
      const quantity = (state.cart.get(id) || 0) + Number(button.dataset.delta);
      if (quantity > 0) state.cart.set(id, quantity);
      else state.cart.delete(id);
      const totalQuantity = [...state.cart.values()].reduce((sum, value) => sum + value, 0);
      $("#add-items").disabled = totalQuantity === 0;
      $("#add-items").textContent = totalQuantity
        ? `Add ${totalQuantity} item${totalQuantity === 1 ? "" : "s"} to bill`
        : "Add items to bill";
      renderMenu();
    });
  });
}

async function selectTable(number) {
  state.table = number;
  state.cart.clear();
  $("#order-workspace").classList.remove("hidden");
  $("#bill-title").textContent = `Table ${number}`;
  $("#menu-title").textContent = `Menu · Table ${number}`;
  $("#add-items").disabled = true;
  await Promise.all([loadMenu(), refreshOrder(), refreshTables()]);
}

async function refreshOrder() {
  if (!state.table) return;
  state.order = await api(`/api/tables/${state.table}/order`);
  renderOrder();
}

function renderOrder() {
  const order = state.order;
  const items = order?.items || [];
  $("#bill-status").textContent = order ? "OCCUPIED" : "EMPTY";
  $("#bill-status").classList.toggle("occupied", Boolean(order));
  $("#vat-toggle").checked = Boolean(order?.vat_rate);
  $("#vat-toggle").disabled = !order;
  $("#bill-lines").innerHTML = items.length ? items.map((item) => `
    <div class="bill-line">
      <span class="line-name">${escapeHtml(item.item_name)}</span>
      <span class="line-total">${money(item.line_total)}</span>
      <span class="line-meta">${money(item.unit_price)} each</span>
      <div class="line-controls">
        <button class="qty-button" data-qty="${item.id}" data-next="${Math.max(0, item.quantity - 1)}" aria-label="Decrease quantity">−</button>
        <strong>${item.quantity}</strong>
        <button class="qty-button" data-qty="${item.id}" data-next="${item.quantity + 1}" aria-label="Increase quantity">+</button>
      </div>
    </div>`).join("") : '<p class="muted">No items added yet.</p>';
  $("#bill-lines").querySelectorAll("[data-qty]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        state.order = await api(`/api/orders/items/${button.dataset.qty}`, {
          method: "PATCH", body: JSON.stringify({ quantity: Number(button.dataset.next) }),
        });
        renderOrder();
        await refreshTables();
      } catch (error) { toast(error.message); }
    });
  });
  $("#subtotal").textContent = money(order?.subtotal);
  $("#vat-amount").textContent = money(order?.vat_amount);
  $("#total").textContent = money(order?.total_amount);
}

async function selectAdminTable(number) {
  state.adminTable = number;
  $("#admin-bill-title").textContent = `Table ${number}`;
  await Promise.all([
    refreshAdminBill(),
    refreshAdminHistory(number),
    refreshTables(),
  ]);
}

async function refreshAdminBill() {
  if (!state.adminTable) return;
  const selectedTable = state.adminTable;
  const order = await api(`/api/tables/${selectedTable}/order`);
  if (state.adminTable !== selectedTable) return;
  state.adminOrder = order;
  $("#admin-bill-title").textContent = `Table ${selectedTable}`;
  $("#admin-bill-status").textContent = order ? "OCCUPIED" : "EMPTY";
  $("#admin-bill-status").classList.toggle("occupied", Boolean(order));
  $("#admin-bill-lines").innerHTML = order?.items.length
    ? order.items.map((item) => `
      <div class="bill-line">
        <span class="line-name">${escapeHtml(item.item_name)}</span>
        <span class="line-total">${money(item.line_total)}</span>
        <span class="line-meta">${money(item.unit_price)} each</span>
        <div class="line-controls">
          <button class="qty-button" data-qty="${item.id}" data-next="${Math.max(0, item.quantity - 1)}" aria-label="Decrease ${escapeHtml(item.item_name)} quantity">−</button>
          <strong>${item.quantity}</strong>
          <button class="qty-button" data-qty="${item.id}" data-next="${item.quantity + 1}" aria-label="Increase ${escapeHtml(item.item_name)} quantity">+</button>
        </div>
      </div>`).join("")
    : '<p class="muted">No active bill for this table.</p>';
  $("#admin-bill-lines").querySelectorAll("[data-qty]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/api/orders/items/${button.dataset.qty}`, {
          method: "PATCH",
          body: JSON.stringify({ quantity: Number(button.dataset.next) }),
        });
        await Promise.all([refreshAdminBill(), refreshTables()]);
        toast("Table bill updated");
      } catch (error) {
        toast(error.message);
      }
    });
  });
  $("#admin-subtotal").textContent = money(order?.subtotal);
  $("#admin-vat").textContent = money(order?.vat_amount);
  $("#admin-total").textContent = money(order?.total_amount);
  $("#admin-settle").disabled = !order;
  if (state.order?.table_number === selectedTable) {
    await refreshOrder();
  }
}

async function refreshAdminHistory(tableNumber = state.adminTable) {
  if (!tableNumber) return;
  const history = await api(`/api/tables/${tableNumber}/history`);
  if (state.adminTable !== tableNumber) return;
  $("#admin-history").innerHTML = history.length
    ? history.map((order) => renderHistoryEntry(order, false)).join("")
    : '<p class="muted">No settled bills for this table yet.</p>';
}

function renderHistoryEntry(order, includeTable) {
  const closedAt = order.closed_at || order.opened_at;
  const tableLabel = includeTable ? `Table ${order.table_number} · ` : "";
  return `
    <details class="history-entry">
      <summary>
        <span>${tableLabel}Bill #${order.id} · ${new Date(closedAt).toLocaleString()}</span>
        <strong>${money(order.total_amount)}</strong>
      </summary>
      <div class="history-lines">
        ${order.items.map((item) => `
          <div><span>${escapeHtml(item.item_name)} × ${item.quantity}</span><strong>${money(item.line_total)}</strong></div>
        `).join("")}
        <div><span>Subtotal</span><strong>${money(order.subtotal)}</strong></div>
        <div><span>VAT</span><strong>${money(order.vat_amount)}</strong></div>
        <div class="history-total"><span>Total paid</span><strong>${money(order.total_amount)}</strong></div>
      </div>
    </details>`;
}

async function loadAllBillHistory() {
  state.allBillHistory = await api("/api/admin/bills/history");
  renderAllBillHistory();
}

function renderAllBillHistory() {
  const search = $("#history-search").value.trim().toLowerCase();
  const bills = state.allBillHistory.filter((bill) =>
    `bill ${bill.id} table ${bill.table_number}`.includes(search));
  $("#all-bill-history").innerHTML = bills.length
    ? bills.map((bill) => renderHistoryEntry(bill, true)).join("")
    : state.allBillHistory.length
      ? '<p class="muted">No settled bills match that search.</p>'
      : '<p class="muted">No settled bills yet.</p>';
}

$("#add-items").addEventListener("click", async () => {
  const rows = [...state.cart.entries()].map(([menu_item_id, quantity]) => ({ menu_item_id, quantity }));
  if (!rows.length) return;
  try {
    state.order = await api(`/api/tables/${state.table}/items`, {
      method: "POST", body: JSON.stringify({ items: rows }),
    });
    state.cart.clear();
    renderMenu();
    $("#add-items").disabled = true;
    $("#add-items").textContent = "Add items to bill";
    renderOrder();
    await refreshTables();
    toast("Items added to the table bill");
  } catch (error) { toast(error.message); }
});

$("#vat-toggle").addEventListener("change", async (event) => {
  if (!state.order) return;
  try {
    state.order = await api(`/api/orders/${state.order.id}/vat`, {
      method: "PATCH", body: JSON.stringify({ enabled: event.target.checked }),
    });
    renderOrder();
    await refreshTables();
  } catch (error) {
    event.target.checked = !event.target.checked;
    toast(error.message);
  }
});

$("#admin-settle").addEventListener("click", async () => {
  const order = state.adminOrder;
  if (!order || !window.confirm(`Settle Table ${state.adminTable} for ${money(order.total_amount)}?`)) return;
  try {
    const closed = await api(`/api/orders/${order.id}/close`, { method: "POST" });
    if (state.order?.id === order.id) {
      state.order = null;
      renderOrder();
    }
    await Promise.all([
      refreshTables(),
      refreshAdminBill(),
      refreshAdminHistory(),
    ]);
    toast(`Bill #${closed.id} settled and archived`);
  } catch (error) { toast(error.message); }
});

$("#menu-search").addEventListener("input", renderMenu);
$("#category-filter").addEventListener("change", renderMenu);
$("#history-search").addEventListener("input", renderAllBillHistory);

function clearAuth() {
  state.authToken = "";
  state.user = null;
  sessionStorage.removeItem("pos-auth-token");
}

function showLoggedOut() {
  document.body.classList.add("login-mode");
  $("#login-form").reset();
  $("#login-email").value = "";
  $("#login-password").value = "";
  $("#login-error").textContent = "";
  $("#logged-in-user").textContent = "";
  $("#login-view").classList.remove("hidden");
  $("#waiter-view").classList.add("hidden");
  $("#admin-view").classList.add("hidden");
  $("#session-controls").classList.add("hidden");
  $("#admin-nav").classList.add("hidden");
}

async function showLoggedIn(user) {
  document.body.classList.remove("login-mode");
  state.user = user;
  $("#login-view").classList.add("hidden");
  $("#session-controls").classList.remove("hidden");
  $("#logged-in-user").textContent = `${user.email} · ${user.role}`;
  const isAdmin = user.role === "admin";
  $("#waiter-view").classList.toggle("hidden", isAdmin);
  $("#admin-view").classList.toggle("hidden", !isAdmin);
  $("#admin-nav").classList.toggle("hidden", !isAdmin);
  if (isAdmin) {
    switchAdminSection("bills");
    await Promise.all([loadWaiters(), loadAdminMenu()]);
  } else {
    await Promise.all([refreshTables(), loadMenu()]);
  }
}

function switchAdminSection(section) {
  for (const button of document.querySelectorAll("[data-admin-section]")) {
    const active = button.dataset.adminSection === section;
    button.classList.toggle("active", active);
  }
  $("#admin-bills-section").classList.toggle("hidden", section !== "bills");
  $("#admin-history-section").classList.toggle("hidden", section !== "history");
  $("#admin-waiters-section").classList.toggle("hidden", section !== "waiters");
  $("#admin-menu-section").classList.toggle("hidden", section !== "menu");
  if (section === "bills") refreshTables().catch((error) => toast(error.message));
  if (section === "history") loadAllBillHistory().catch((error) => toast(error.message));
  if (section === "waiters") loadWaiters().catch((error) => toast(error.message));
  if (section === "menu") loadAdminMenu().catch((error) => toast(error.message));
}

document.querySelectorAll("[data-admin-section]").forEach((button) => {
  button.addEventListener("click", () => switchAdminSection(button.dataset.adminSection));
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#login-error").textContent = "";
  try {
    const result = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: $("#login-email").value.trim(),
        password: $("#login-password").value,
      }),
    });
    state.authToken = result.token;
    sessionStorage.setItem("pos-auth-token", result.token);
    $("#login-password").value = "";
    await showLoggedIn(result.user);
  } catch (error) {
    $("#login-error").textContent = error.message;
  }
});

$("#logout").addEventListener("click", async () => {
  try {
    if (state.authToken) await api("/api/auth/logout", { method: "POST" });
  } catch (error) {
    toast(error.message);
  } finally {
    clearAuth();
    showLoggedOut();
  }
});

async function loadWaiters() {
  const waiters = await api("/api/admin/waiters");
  $("#waiter-list").innerHTML = waiters.length ? waiters.map((waiter) => `
    <div class="admin-row">
      <div><strong>${escapeHtml(waiter.email)}</strong><small>Waiter account</small></div>
      <span class="stock ${waiter.is_active ? "" : "out"}">${waiter.is_active ? "Active" : "Inactive"}</span>
      <div class="row-actions">
        <button class="button button-outline" data-waiter-edit="${waiter.id}">Edit</button>
        <button class="button button-outline" data-waiter-toggle="${waiter.id}" data-active="${waiter.is_active}">
          ${waiter.is_active ? "Deactivate" : "Activate"}
        </button>
      </div>
    </div>`).join("") : '<p class="muted">No waiter accounts yet.</p>';

  $("#waiter-list").querySelectorAll("[data-waiter-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      const waiter = waiters.find((entry) => entry.id === Number(button.dataset.waiterEdit));
      $("#waiter-id").value = waiter.id;
      $("#waiter-email").value = waiter.email;
      $("#waiter-password").value = "";
      $("#waiter-password").required = false;
      $("#waiter-password").placeholder = "Leave blank to keep current password";
      $("#waiter-active").checked = waiter.is_active;
      $("#waiter-form-title").textContent = "Edit waiter";
      $("#waiter-save").textContent = "Save waiter";
      $("#cancel-waiter-edit").classList.remove("hidden");
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  $("#waiter-list").querySelectorAll("[data-waiter-toggle]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/api/admin/waiters/${button.dataset.waiterToggle}`, {
          method: "PUT",
          body: JSON.stringify({ is_active: button.dataset.active !== "true" }),
        });
        await loadWaiters();
        toast("Waiter access updated");
      } catch (error) {
        toast(error.message);
      }
    });
  });
}

function resetWaiterForm() {
  $("#waiter-form").reset();
  $("#waiter-id").value = "";
  $("#waiter-password").required = true;
  $("#waiter-password").placeholder = "";
  $("#waiter-active").checked = true;
  $("#waiter-form-title").textContent = "Add waiter";
  $("#waiter-save").textContent = "Add waiter";
  $("#cancel-waiter-edit").classList.add("hidden");
}

$("#waiter-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = $("#waiter-id").value;
  const payload = {
    email: $("#waiter-email").value.trim(),
    is_active: $("#waiter-active").checked,
  };
  if (!id || $("#waiter-password").value) {
    payload.password = $("#waiter-password").value;
  }
  try {
    await api(id ? `/api/admin/waiters/${id}` : "/api/admin/waiters", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    resetWaiterForm();
    await loadWaiters();
    toast(id ? "Waiter updated" : "Waiter added");
  } catch (error) {
    toast(error.message);
  }
});

$("#cancel-waiter-edit").addEventListener("click", resetWaiterForm);

async function loadAdminMenu() {
  try {
    const menu = await api("/api/admin/menu");
    $("#admin-menu-list").innerHTML = menu.map((item) => `
      <div class="admin-row">
        <div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.category)} · ${money(item.price)}</small></div>
        <span class="stock ${item.is_available ? "" : "out"}">${item.is_available ? "In stock" : "Out of stock"}</span>
        <div class="row-actions">
          <button class="button button-outline" data-edit="${item.id}">Edit</button>
          <button class="button button-outline" data-delete="${item.id}">Remove</button>
        </div>
      </div>`).join("");
    $("#admin-menu-list").querySelectorAll("[data-edit]").forEach((button) => {
      button.addEventListener("click", () => {
        const item = menu.find((entry) => entry.id === Number(button.dataset.edit));
        $("#menu-id").value = item.id;
        $("#item-name").value = item.name;
        $("#item-category").value = item.category;
        $("#item-price").value = item.price;
        $("#item-available").checked = item.is_available;
        $("#admin-form-title").textContent = "Edit menu item";
        $("#cancel-edit").classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    });
    $("#admin-menu-list").querySelectorAll("[data-delete]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!window.confirm("Remove this menu item? Past bills will be retained.")) return;
        try {
          await api(`/api/admin/menu/${button.dataset.delete}`, { method: "DELETE" });
          await loadAdminMenu();
          toast("Menu item removed");
        } catch (error) { toast(error.message); }
      });
    });
  } catch (error) {
    toast(error.message);
  }
}

function resetMenuForm() {
  $("#menu-form").reset();
  $("#menu-id").value = "";
  $("#item-available").checked = true;
  $("#admin-form-title").textContent = "Add menu item";
  $("#cancel-edit").classList.add("hidden");
}

$("#menu-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = $("#menu-id").value;
  const payload = {
    name: $("#item-name").value.trim(),
    category: $("#item-category").value.trim(),
    price: Number($("#item-price").value).toFixed(2),
    is_available: $("#item-available").checked,
  };
  try {
    await api(id ? `/api/admin/menu/${id}` : "/api/admin/menu", {
      method: id ? "PUT" : "POST", body: JSON.stringify(payload),
    });
    resetMenuForm();
    await loadAdminMenu();
    toast(id ? "Menu item updated" : "Menu item added");
  } catch (error) { toast(error.message); }
});

$("#cancel-edit").addEventListener("click", resetMenuForm);
if (state.authToken) {
  api("/api/auth/me")
    .then(showLoggedIn)
    .catch(() => showLoggedOut());
} else {
  showLoggedOut();
}

window.setInterval(() => {
  if (!state.user) return;
  refreshTables().catch((error) => toast(error.message));
  if (state.user.role === "waiter" && state.table) {
    refreshOrder().catch((error) => toast(error.message));
  }
  if (state.user.role === "admin" && state.adminTable) {
    refreshAdminBill().catch((error) => toast(error.message));
  }
}, 12000);
