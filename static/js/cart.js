(function () {
  const cartList = document.querySelector("[data-cart-list]");
  const toast = document.querySelector("[data-cart-toast]");
  const headingCount = document.querySelector("[data-cart-heading-count]");

  if (!cartList) {
    return;
  }

  const showMessage = (message, isError) => {
    if (!toast || !message) return;
    toast.textContent = message;
    toast.classList.toggle("is-error", Boolean(isError));
    toast.classList.add("is-visible");
    window.setTimeout(() => toast.classList.remove("is-visible"), 2600);
  };

  const setBusy = (element, busy) => {
    element?.classList.toggle("is-loading", busy);
    element?.querySelectorAll("button").forEach((control) => {
      control.disabled = busy;
    });
  };

  const postForm = async (form) => {
    const response = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
    });
    const data = await response.json().catch(() => ({ ok: false, message: "Unexpected cart response." }));
    if (!response.ok || data.ok === false) {
      throw data;
    }
    return data;
  };

  const updateSummary = (data) => {
    const totals = data.totals || {};
    const productTotal = document.querySelector("[data-cart-product-total]");
    const subtotal = document.querySelector("[data-cart-subtotal]");
    const discount = document.querySelector("[data-cart-discount]");
    const delivery = document.querySelector("[data-cart-delivery]");
    const total = document.querySelector("[data-cart-total]");
    if (productTotal) productTotal.textContent = totals.product_total || productTotal.textContent;
    if (subtotal) subtotal.textContent = totals.subtotal || subtotal.textContent;
    if (discount) discount.textContent = `-${totals.discount || "Rs. 0"}`;
    if (delivery) delivery.textContent = totals.delivery_charge || delivery.textContent;
    if (total) total.textContent = totals.total || total.textContent;
    if (headingCount) headingCount.textContent = data.item_count ?? headingCount.textContent;

    const cartNav = Array.from(document.querySelectorAll(".nav-icons a")).find((link) => link.textContent.trim().startsWith("Cart"));
    if (cartNav && typeof data.cart_count === "number") {
      cartNav.textContent = `Cart (${data.cart_count})`;
    }
  };

  const updateItems = (data) => {
    const itemsById = new Map((data.items || []).map((item) => [String(item.id), item]));
    document.querySelectorAll("[data-cart-item]").forEach((row) => {
      const item = itemsById.get(row.dataset.cartItem);
      if (!item) {
        row.remove();
        return;
      }
      const quantity = row.querySelector("[data-cart-quantity]");
      const lineTotal = row.querySelector("[data-line-total]");
      const discount = row.querySelector("[data-item-discount]");
      if (quantity) quantity.value = item.quantity;
      if (lineTotal) lineTotal.textContent = item.line_total;
      if (discount) discount.textContent = `${item.discount} off`;
    });

    if (data.empty) {
      const content = document.querySelector("#cart-content");
      content?.replaceWith(emptyState());
    }
  };

  const emptyState = () => {
    const wrapper = document.createElement("div");
    wrapper.className = "empty-state";
    wrapper.setAttribute("data-cart-empty", "");
    wrapper.innerHTML = '<h2>Your cart is empty</h2><p>Fresh parts, accessories, and garage essentials are waiting.</p><a class="primary-action" href="/home">Shop now</a>';
    return wrapper;
  };

  const submitCartForm = async (form) => {
    const row = form.closest("[data-cart-item]");
    setBusy(row || form, true);
    try {
      const data = await postForm(form);
      updateSummary(data);
      updateItems(data);
      showMessage(data.message || "Cart updated.");
    } catch (error) {
      const message = error.message || "Cart update failed.";
      const inline = row?.querySelector("[data-cart-message]");
      if (inline) inline.textContent = message;
      showMessage(message, true);
    } finally {
      setBusy(row || form, false);
    }
  };

  cartList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-quantity-step]");
    if (!button) return;
    const form = button.closest("form");
    const input = form?.querySelector("[data-cart-quantity]");
    if (!form || !input) return;
    const step = Number(button.dataset.quantityStep);
    const min = Number(input.min || 1);
    const max = Number(input.max || 999999);
    const next = Math.min(Math.max(Number(input.value || min) + step, min), max);
    if (next === Number(input.value)) return;
    input.value = String(next);
    submitCartForm(form);
  });

  cartList.addEventListener("change", (event) => {
    const input = event.target.closest("[data-cart-quantity]");
    if (!input) return;
    const min = Number(input.min || 1);
    const max = Number(input.max || 999999);
    input.value = String(Math.min(Math.max(Number(input.value || min), min), max));
    submitCartForm(input.closest("form"));
  });

  cartList.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-cart-action]");
    if (!form) return;
    event.preventDefault();
    submitCartForm(form);
  });
})();
