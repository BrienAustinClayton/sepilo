"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Bot, History, ShoppingCart, Store } from "lucide-react";
import { NavDrawer } from "@/components/Sidebar";
import { ApiCallError } from "@/shared/api/ApiCallError";
import { AgentKind } from "@/lib/types";
import { ToastTypeEnum } from "@/shared/enums";
import { showToast } from "@/shared/toast/toastManager";
import { AGENT_CHOICES, PAYPAL_NOTICE, promptsFor } from "../../constants";
import { ChatRoleEnum } from "../../enums";
import { useChatSessions } from "../../hooks/useChatSessions";
import { CartReview, ChatCartState, ChatMessageItem, ChatProductItem, ChatRuleOption } from "../../types";
import { ChatCartDrawer } from "../components/ChatCartDrawer";
import { AgentKindPicker } from "../components/AgentKindPicker";
import { ChatComposer } from "../components/ChatComposer";
import { ChatHistoryPanel } from "../components/ChatHistoryPanel";
import { ChatMessageItemView } from "../components/ChatMessageItemView";
import { ChatStarterPrompts } from "../components/ChatStarterPrompts";
import { ChatThinking } from "../components/ChatThinking";
import { ChatThreadSkeleton } from "../components/ChatThreadSkeleton";
import { ChatTitleEditor } from "../components/ChatTitleEditor";
import { RecentConversations } from "../components/RecentConversations";

const DEFAULT_EMPTY_CART: ChatCartState = { items: [], total: "0.00", count: 0, currency: "USD", stores: 0, issues: [] };

export function ChatPage() {
  const router = useRouter();
  const params = useSearchParams();
  const activeChatId = params.get("c");
  const paypalNotice = PAYPAL_NOTICE[params.get("paypal") ?? ""] ?? null;

  const [inputText, setInputText] = useState("");
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const [pendingRule, setPendingRule] = useState<string | null>(null);
  const [pendingKind, setPendingKind] = useState<AgentKind>("channel3");
  const [addressRequired, setAddressRequired] = useState<string | null>(null);
  const [isCartOpen, setIsCartOpen] = useState(false);
  const [cartReview, setCartReview] = useState<CartReview | null>(null);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isAppMenuOpen, setIsAppMenuOpen] = useState(false);
  const [addingProductId, setAddingProductId] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const {
    chats,
    isLoadingChats,
    activeChat,
    arrivedIds,
    isLoadingActiveChat,
    activeChatError,
    myRules,
    createChat,
    sendMessage,
    isSendingMessage,
    setChatRule,
    renameChat,
    isSettingRule,
    addToCart,
    setCartQty,
    checkout,
    isCheckingOut,
    deleteChat,
  } = useChatSessions(activeChatId);

  const openChat = useCallback(
    (id: string | null) => {
      setIsHistoryOpen(false);
      setError(null);
      setCartReview(null);
      router.replace(id ? `/chat?c=${encodeURIComponent(id)}` : "/chat");
    },
    [router],
  );

  useEffect(() => {
    if (activeChatId && activeChatError) router.replace("/chat");
  }, [activeChatId, activeChatError, router]);

  const thread = activeChat && activeChat.id === activeChatId ? activeChat : null;
  const cart = thread?.cart ?? DEFAULT_EMPTY_CART;
  const messages = useMemo(() => thread?.messages ?? [], [thread]);
  const newChatRules = myRules.filter((r) => r.agent_kind === pendingKind);
  const ruleOptions: ChatRuleOption[] = thread?.rule_options ?? newChatRules;
  const ruleId = thread ? thread.rule_id : newChatRules.some((r) => r.id === pendingRule) ? pendingRule : null;
  const rulesInUse = thread?.rules ?? (newChatRules.filter((r) => r.id === ruleId).length ? newChatRules.filter((r) => r.id === ruleId) : newChatRules);
  const isSending = isSendingMessage || pendingMessage !== null;
  const lastMessage = messages[messages.length - 1];
  const pendingAlreadySaved =
    pendingMessage !== null && lastMessage?.role === ChatRoleEnum.User && lastMessage.content === pendingMessage;
  const showSkeleton = Boolean(activeChatId) && isLoadingActiveChat && !thread && !pendingMessage;
  const agentChoice = AGENT_CHOICES.find((choice) => choice.kind === pendingKind) ?? AGENT_CHOICES[0];
  const introChoice = AGENT_CHOICES.find((choice) => choice.kind === (thread?.agent?.kind ?? pendingKind)) ?? AGENT_CHOICES[0];

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pendingMessage]);

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || isSending) return;
    setError(null);
    setInputText("");
    setPendingMessage(content);
    try {
      let chatId = activeChatId;
      if (!chatId) {
        const created = await createChat({ ruleId, agentKind: pendingKind });
        chatId = created.id;
        openChat(chatId);
      }
      await sendMessage({ chatId, content });
    } catch (err) {
      const code = err instanceof ApiCallError ? err.errorCode : "";
      const message = err instanceof Error ? err.message : "Couldn't send that. Try again.";
      if (code === "no_hosted_agent") setBlocked(message);
      else setError(message);
      setInputText(content);
    } finally {
      setPendingMessage(null);
      inputRef.current?.focus();
    }
  };

  const pickRule = (id: string | null) => {
    if (!thread) {
      setPendingRule(id);
      return;
    }
    setChatRule({ chatId: thread.id, ruleId: id }).catch((err: Error) => setError(err.message));
  };

  const fillFromStarter = (prompt: string) => {
    setInputText(prompt);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(prompt.length, prompt.length);
    });
  };

  const handleAddToCart = (message: ChatMessageItem, product: ChatProductItem) => {
    if (!activeChatId || addingProductId) return;
    setAddingProductId(`${message.id}:${product.product_id}`);
    addToCart({ chatId: activeChatId, messageId: message.id, productId: product.product_id })
      .then((cartAfter) => {
        if (cartAfter.notice) showToast(cartAfter.notice, ToastTypeEnum.Info);
      })
      .catch(() => {})
      .finally(() => setAddingProductId(null));
  };

  const notice = error
    ? { tone: "error" as const, text: error }
    : paypalNotice
    ? { tone: "info" as const, text: paypalNotice }
    : null;

  const historyPanel = (
    <ChatHistoryPanel
      chats={chats}
      isLoading={isLoadingChats}
      activeChatId={activeChatId}
      onSelectChat={openChat}
      onNewChat={() => openChat(null)}
      onDeleteChat={(id: string) => {
        if (!window.confirm("Delete this chat? Orders it placed stay in Orders.")) return;
        deleteChat(id).catch(() => {});
        if (activeChatId === id) openChat(null);
      }}
      onOpenAppMenu={() => {
        setIsHistoryOpen(false);
        setIsAppMenuOpen(true);
      }}
    />
  );

  return (
    <div className="flex h-dvh bg-canvas overflow-hidden">
      <aside className="hidden lg:flex w-72 shrink-0 flex-col bg-sidebar border-r border-line">{historyPanel}</aside>

      <div className={`lg:hidden fixed inset-0 z-40 ${isHistoryOpen ? "" : "pointer-events-none"}`} aria-hidden={!isHistoryOpen}>
        <button
          type="button"
          aria-label="Close history"
          tabIndex={isHistoryOpen ? 0 : -1}
          onClick={() => setIsHistoryOpen(false)}
          className={`absolute inset-0 bg-black/50 transition-opacity duration-200 ${isHistoryOpen ? "opacity-100" : "opacity-0"}`}
        />
        <aside
          className={`absolute inset-y-0 left-0 w-72 max-w-[85vw] flex flex-col bg-sidebar border-r border-line transition-transform duration-200 ${
            isHistoryOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          {historyPanel}
        </aside>
      </div>

      <NavDrawer open={isAppMenuOpen} onClose={() => setIsAppMenuOpen(false)} />

      <main className="flex-1 flex flex-col min-w-0 min-h-0">
        <header className="h-14 border-b border-line flex items-center justify-between gap-3 px-3 sm:px-6 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <button
              type="button"
              onClick={() => setIsHistoryOpen(true)}
              className="lg:hidden p-2 -ml-1 text-fg-dim hover:text-fg rounded-md"
              aria-label="Chat history"
            >
              <History className="w-5 h-5" strokeWidth={1.8} />
            </button>
            <div className="min-w-0 flex-1">
              <ChatTitleEditor
                key={thread?.id ?? "new"}
                title={thread ? thread.title : "New chat"}
                editable={Boolean(thread)}
                onRename={(title: string) => renameChat({ chatId: thread!.id, title })}
              />
              <div className="flex items-center gap-1 text-xs text-fg-dim truncate">
                <Store className="w-3.5 h-3.5 shrink-0" strokeWidth={1.8} />
                {thread?.agent?.name ?? agentChoice.name}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setIsCartOpen(true)}
            disabled={!thread}
            className="intentlock-btn-outline btn-sm relative shrink-0"
            aria-label={`Cart, ${cart.count} items`}
          >
            <ShoppingCart className="w-4 h-4" strokeWidth={1.8} />
            <span className="hidden sm:inline">Cart</span>
            {cart.count > 0 && (
              <span className="min-w-5 h-5 px-1 rounded-full bg-blue-600 text-[11px] font-semibold text-white flex items-center justify-center">
                {cart.count}
              </span>
            )}
          </button>
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
          <div className="mx-auto w-full max-w-4xl px-4 sm:px-6 py-5 sm:py-8 space-y-6">
            {blocked ? (
              <div className="saas-card p-6 sm:p-8 text-center space-y-3">
                <Bot className="w-6 h-6 mx-auto text-fg-muted" strokeWidth={1.8} />
                <h2 className="text-base font-semibold">Create your shopping agent first</h2>
                <p className="text-sm text-fg-muted">{blocked}</p>
                <Link href="/agents" className="intentlock-btn-primary">
                  Go to Agents
                </Link>
              </div>
            ) : showSkeleton ? (
              <ChatThreadSkeleton />
            ) : messages.length === 0 && !pendingMessage ? (
              <div className="pt-4 sm:pt-12 text-center space-y-6">
                <div className="space-y-2">
                  <h1 className="text-xl sm:text-2xl font-semibold tracking-tight">What should Sepilo buy for you?</h1>
                  <p className="text-sm text-fg-muted max-w-lg mx-auto">{introChoice.intro}</p>
                </div>
                {!thread && <AgentKindPicker value={pendingKind} onChange={setPendingKind} />}
                <ChatStarterPrompts prompts={promptsFor(rulesInUse)} onPick={fillFromStarter} />
                <div className="pt-4 sm:pt-8">
                  <RecentConversations chats={chats} onOpen={openChat} />
                </div>
              </div>
            ) : (
              messages.map((message: ChatMessageItem) => (
                <ChatMessageItemView
                  key={message.id}
                  message={message}
                  cart={cart}
                  addingProductId={addingProductId}
                  onAddToCart={handleAddToCart}
                  animate={arrivedIds.has(message.id)}
                />
              ))
            )}
            {pendingMessage && !pendingAlreadySaved && (
              <div className="flex justify-end">
                <div className="max-w-lg rounded-3xl bg-fg/7 px-4 py-2.5 text-[15px] sm:text-sm leading-relaxed text-fg whitespace-pre-wrap wrap-break-word">
                  {pendingMessage}
                </div>
              </div>
            )}
            {pendingMessage && <ChatThinking />}
            <div ref={endRef} />
          </div>
        </div>

        <ChatComposer
          inputRef={inputRef}
          value={inputText}
          onChange={setInputText}
          onSend={() => send(inputText)}
          isSending={isSending}
          notice={notice}
          cart={cart}
          onOpenCart={() => setIsCartOpen(true)}
          ruleOptions={ruleOptions}
          ruleId={ruleId}
          isSettingRule={isSettingRule}
          onPickRule={pickRule}
        />
      </main>

      <ChatCartDrawer
        isOpen={isCartOpen}
        cart={cart}
        isBusy={isCheckingOut}
        onClose={() => setIsCartOpen(false)}
        onUpdateQty={(productId: string, qty: number) => {
          if (!activeChatId) return;
          setCartReview(null);
          setCartQty({ chatId: activeChatId, productId, qty: Math.max(0, qty) }).catch(() => {});
        }}
        onCheckout={(confirm: boolean) => {
          if (!activeChatId) return;
          setAddressRequired(null);
          checkout({ chatId: activeChatId, confirm })
            .then(() => {
              setCartReview(null);
              setIsCartOpen(false);
            })
            .catch((err: unknown) => {
              if (err instanceof ApiCallError && err.errorCode === "address_required") {
                setAddressRequired(err.message);
                return;
              }
              const review = err instanceof ApiCallError ? (err.data.review as CartReview | undefined) : undefined;
              setCartReview(review ?? null);
              if (!review) showToast(err instanceof Error ? err.message : "Checkout failed", ToastTypeEnum.Error);
            });
        }}
        review={cartReview}
        addressRequired={addressRequired}
      />
    </div>
  );
}
