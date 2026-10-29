"use client";

import React from "react";
import Link from "next/link";
import { Minus, Plus, ShoppingCart, Trash2, X } from "lucide-react";
import { CartDrawerProps } from "../../componentTypes";
import { CartItemLine } from "../../types";
import { Button } from "@/shared/presentation/components/Button";
import { ButtonVariantEnum } from "@/shared/enums";
import { CartReviewDecisionEnum } from "../../enums";
import { CartCheckList } from "./CartCheckList";

export function ChatCartDrawer({
  isOpen,
  cart,
  isBusy,
  onClose,
  onUpdateQty,
  onCheckout,
  review,
  addressRequired,
}: CartDrawerProps) {
  const cartItems = cart && Array.isArray(cart.items) ? cart.items : [];
  const storeNames = Array.from(new Set(cartItems.map((item: CartItemLine) => item.merchant)));
  const hasNoItems = cartItems.length === 0;
  const isBlocked = review?.decision === CartReviewDecisionEnum.Block;
  const needsConfirmation = review?.decision === CartReviewDecisionEnum.Confirm;
  const cartIssues = Array.isArray(cart.issues) ? cart.issues : [];
  const checkoutLabel = isBusy
    ? "Checking cart…"
    : needsConfirmation
    ? "Buy anyway"
    : "Review & Checkout with PayPal";

  return (
    <div className={`fixed inset-0 z-50 ${isOpen ? "" : "pointer-events-none"}`} aria-hidden={!isOpen}>
      <button
        type="button"
        aria-label="Close cart"
        tabIndex={isOpen ? 0 : -1}
        onClick={onClose}
        className={`absolute inset-0 bg-black/40 backdrop-blur-[2px] transition-opacity duration-300 ${
          isOpen ? "opacity-100" : "opacity-0"
        }`}
      />

      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Cart"
        className={`sheet absolute inset-x-0 bottom-0 max-h-[88dvh] sm:inset-y-3 sm:left-auto sm:right-3 sm:max-h-none sm:w-105 flex flex-col overflow-hidden transition-transform duration-300 ${
          isOpen ? "translate-y-0 sm:translate-x-0" : "translate-y-full sm:translate-y-0 sm:translate-x-[calc(100%+1rem)]"
        }`}
      >
        <div className="flex items-center justify-between px-5 h-12 sm:h-16 shrink-0 border-b border-line">
          <div className="text-base font-semibold">
            Cart <span className="text-fg-dim font-normal">· {cart.count} items</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-full bg-fg/6 text-fg-dim hover:text-fg hover:bg-fg/10 transition"
            aria-label="Close cart"
          >
            <X className="w-4 h-4" strokeWidth={1.8} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {hasNoItems && (
            <div className="py-12 text-center text-sm text-fg-muted">
              <ShoppingCart className="w-8 h-8 mx-auto mb-3 text-fg-dim" strokeWidth={1.8} />
              Your cart is empty. Add products from the chat suggestions.
            </div>
          )}

          {storeNames.map((store: string) => {
            const storeItems = cartItems.filter((item: CartItemLine) => item.merchant === store);

            return (
              <div key={store} className="rounded-2xl bg-fg/4 p-3.5 space-y-3">
                <div className="text-xs font-semibold uppercase tracking-wider text-fg-dim">
                  {store}
                </div>

                {storeItems.map((item: CartItemLine) => (
                  <div key={item.product_id} className="flex gap-3">
                    <div className="h-14 w-14 shrink-0 rounded-xl bg-white p-1 flex items-center justify-center overflow-hidden">
                      {item.image && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={item.image}
                          alt=""
                          className="max-h-full max-w-full object-contain"
                        />
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-fg line-clamp-1">
                        {item.title}
                      </div>
                      <div className="text-xs text-fg-dim">
                        ${item.price} each
                      </div>

                      <div className="mt-2 flex items-center justify-between">
                        <div className="inline-flex items-center rounded-full bg-fg/6 px-1 py-0.5">
                          <button
                            type="button"
                            onClick={() => onUpdateQty(item.product_id, item.qty - 1)}
                            disabled={isBusy}
                            className="p-1 text-fg-muted hover:text-fg disabled:opacity-50"
                            aria-label="Decrease quantity"
                          >
                            {item.qty === 1 ? (
                              <Trash2 className="w-3 h-3 text-rose-400" />
                            ) : (
                              <Minus className="w-3 h-3" />
                            )}
                          </button>
                          <span className="min-w-6 text-center text-xs tabular-nums font-medium">
                            {item.qty}
                          </span>
                          <button
                            type="button"
                            onClick={() => onUpdateQty(item.product_id, item.qty + 1)}
                            disabled={isBusy}
                            className="p-1 text-fg-muted hover:text-fg disabled:opacity-50"
                            aria-label="Increase quantity"
                          >
                            <Plus className="w-3 h-3" />
                          </button>
                        </div>

                        <span className="text-sm font-semibold tabular-nums text-fg">
                          ${(Number(item.price) * item.qty).toFixed(2)}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </div>

        <div className="p-4 border-t border-line space-y-3 bg-canvas">
          <div className="flex items-center justify-between text-sm">
            <span className="text-fg-dim">Total:</span>
            <span className="text-lg font-bold tabular-nums text-fg">${cart.total}</span>
          </div>

          {review && <CartCheckList review={review} />}
          {addressRequired && (
            <div role="alert" className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-3.5 space-y-3">
              <p className="text-sm text-fg">{addressRequired}</p>
              <Link href="/address" className="intentlock-btn-primary btn-sm">
                Add shipping address
              </Link>
            </div>
          )}
          <p className="text-xs text-fg-dim">
            Sepilo checks your rules, the prices with Channel3 and the listings (with Jev&apos;s second opinion)
            before anything is paid.
          </p>
          <Button
            variant={ButtonVariantEnum.Primary}
            disabled={hasNoItems || isBlocked || cartIssues.length > 0}
            isLoading={isBusy}
            onClick={() => onCheckout(needsConfirmation)}
            className="w-full"
          >
            {checkoutLabel}
          </Button>
        </div>
      </aside>
    </div>
  );
}
