import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { makeApiCall } from "@/shared/api/makeApiCall";
import { AgentKind } from "@/lib/types";
import { HttpMethodEnum } from "@/shared/enums";
import { ChatSummaryItem } from "../componentTypes";
import { IN_PROGRESS_ORDER } from "../constants";
import { ChatRoleEnum } from "../enums";
import { ChatCartState, ChatMessageItem, ChatRuleOption, CartReview } from "../types";

export interface ActiveChatThread {
  id: string;
  title: string;
  agent: { id: string; name: string; kind: AgentKind } | null;
  rule_id: string | null;
  rule_options: ChatRuleOption[];
  rules: ChatRuleOption[];
  messages: ChatMessageItem[];
  cart: ChatCartState;
}

interface MandateRow {
  id: string;
  agent_id: string;
  categories: string[];
  merchants: string[];
  budget_amount: string;
  budget_period: string;
  currency: string;
  revoked_at: string | null;
}

interface AgentRow {
  id: string;
  kind: AgentKind;
  managed: boolean;
  revoked_at: string | null;
}

const isInProgress = (thread: ActiveChatThread | undefined): boolean =>
  Boolean(thread?.messages?.some((m) =>
    m.run?.status === "running" || (m.run?.order_status != null && IN_PROGRESS_ORDER.has(m.run.order_status))));

export function useChatSessions(activeChatId: string | null = null) {
  const queryClient = useQueryClient();
  const [arrivedIds, setArrivedIds] = useState<Set<string>>(() => new Set());

  const chatsListQuery = useQuery<ChatSummaryItem[]>({
    queryKey: ["chatList"],
    queryFn: () =>
      makeApiCall<ChatSummaryItem[]>({
        endpoint: "/api/me/chats",
        method: HttpMethodEnum.Get,
      }),
  });

  const shouldFetchThread = activeChatId !== null && activeChatId.length > 0;
  const activeChatQuery = useQuery<ActiveChatThread>({
    queryKey: ["chatThread", activeChatId],
    queryFn: () =>
      makeApiCall<ActiveChatThread>({
        endpoint: `/api/me/chats/${encodeURIComponent(activeChatId || "")}`,
        method: HttpMethodEnum.Get,
      }),
    enabled: shouldFetchThread,
    refetchInterval: (query) => (isInProgress(query.state.data) ? 3000 : false),
  });

  const myRulesQuery = useQuery<ChatRuleOption[]>({
    queryKey: ["chatRuleOptions"],
    queryFn: () =>
      Promise.all([
        makeApiCall<MandateRow[]>({ endpoint: "/api/me/mandates", method: HttpMethodEnum.Get, silent: true }),
        makeApiCall<AgentRow[]>({ endpoint: "/api/me/agents", method: HttpMethodEnum.Get, silent: true }),
      ]).then(([mandates, agents]) => {
        const managedIds = new Set((Array.isArray(agents) ? agents : []).filter((a) => a.managed && !a.revoked_at).map((a) => a.id));
        return (Array.isArray(mandates) ? mandates : [])
          .filter((m) => !m.revoked_at && managedIds.has(m.agent_id))
          .map((m) => ({
            id: m.id, agent_id: m.agent_id, categories: m.categories, merchants: m.merchants,
            budget: m.budget_amount, remaining: m.budget_amount, period: m.budget_period, currency: m.currency,
          }));
      }),
  });

  const renameChatMutation = useMutation<ActiveChatThread, Error, { chatId: string; title: string }>({
    mutationFn: ({ chatId, title }) =>
      makeApiCall<ActiveChatThread, { title: string }>({
        endpoint: `/api/me/chats/${encodeURIComponent(chatId)}`,
        method: HttpMethodEnum.Patch,
        payload: { title },
      }),
    onMutate: ({ chatId, title }) => {
      queryClient.setQueryData<ActiveChatThread>(["chatThread", chatId], (thread) => (thread ? { ...thread, title } : thread));
    },
    onSettled: (_, __, { chatId }) => {
      queryClient.invalidateQueries({ queryKey: ["chatThread", chatId] });
      queryClient.invalidateQueries({ queryKey: ["chatList"] });
    },
  });

  const setChatRuleMutation = useMutation<ActiveChatThread, Error, { chatId: string; ruleId: string | null }>({
    mutationFn: ({ chatId, ruleId }) =>
      makeApiCall<ActiveChatThread, { mandate_id: string | null }>({
        endpoint: `/api/me/chats/${encodeURIComponent(chatId)}`,
        method: HttpMethodEnum.Patch,
        payload: { mandate_id: ruleId },
      }),
    onSuccess: (thread, { chatId }) => {
      queryClient.setQueryData(["chatThread", chatId], thread);
    },
  });

  const createChatMutation = useMutation<ChatSummaryItem, Error, { ruleId?: string | null }>({
    mutationFn: (payload) =>
      makeApiCall<ChatSummaryItem, { mandate_id?: string }>({
        endpoint: "/api/me/chats",
        method: HttpMethodEnum.Post,
        payload: payload.ruleId ? { mandate_id: payload.ruleId } : {},
        silent: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["chatList"] });
    },
  });

  const sendMessageMutation = useMutation<
    { messages: ChatMessageItem[]; title: string },
    Error,
    { chatId: string; content: string }
  >({
    mutationFn: ({ chatId, content }) =>
      makeApiCall<{ messages: ChatMessageItem[]; title: string }, { content: string }>({
        endpoint: `/api/me/chats/${encodeURIComponent(chatId)}/messages`,
        method: HttpMethodEnum.Post,
        payload: { content },
        silent: true,
      }),
    onSuccess: (out, variables) => {
      const replies = out.messages.filter((m) => m.role === ChatRoleEnum.Assistant).map((m) => m.id);
      setArrivedIds((prev) => new Set([...prev, ...replies]));
      queryClient.setQueryData<ActiveChatThread>(["chatThread", variables.chatId], (thread) => {
        if (!thread) return thread;
        const known = new Set(thread.messages.map((m) => m.id));
        return { ...thread, title: out.title, messages: [...thread.messages, ...out.messages.filter((m) => !known.has(m.id))] };
      });
      queryClient.invalidateQueries({ queryKey: ["chatList"] });
    },
  });

  const addToCartMutation = useMutation<
    ChatCartState & { notice?: string | null },
    Error,
    { chatId: string; messageId: string; productId: string }
  >({
    mutationFn: ({ chatId, messageId, productId }) =>
      makeApiCall<ChatCartState & { notice?: string | null }, { message_id: string; product_id: string }>({
        endpoint: `/api/me/chats/${encodeURIComponent(chatId)}/cart`,
        method: HttpMethodEnum.Post,
        payload: { message_id: messageId, product_id: productId },
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["chatThread", variables.chatId] });
    },
  });

  const setCartQtyMutation = useMutation<
    ChatCartState,
    Error,
    { chatId: string; productId: string; qty: number }
  >({
    mutationFn: ({ chatId, productId, qty }) =>
      makeApiCall<ChatCartState, { qty: number }>({
        endpoint: `/api/me/chats/${encodeURIComponent(chatId)}/cart/${encodeURIComponent(productId)}`,
        method: HttpMethodEnum.Patch,
        payload: { qty },
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["chatThread", variables.chatId] });
    },
  });

  const checkoutMutation = useMutation<
    { messages: ChatMessageItem[]; cart: ChatCartState; review: CartReview },
    Error,
    { chatId: string; confirm?: boolean }
  >({
    mutationFn: ({ chatId, confirm }) =>
      makeApiCall<{ messages: ChatMessageItem[]; cart: ChatCartState; review: CartReview }, { confirm: boolean }>({
        endpoint: `/api/me/chats/${encodeURIComponent(chatId)}/checkout`,
        method: HttpMethodEnum.Post,
        payload: confirm ? { confirm: true } : undefined,
        silent: true,
      }),
    onSuccess: (_, { chatId }) => {
      queryClient.invalidateQueries({ queryKey: ["chatThread", chatId] });
      queryClient.invalidateQueries({ queryKey: ["orders"] });
    },
  });

  const deleteChatMutation = useMutation<{ ok: boolean }, Error, string>({
    mutationFn: (chatId: string) =>
      makeApiCall<{ ok: boolean }>({
        endpoint: `/api/me/chats/${encodeURIComponent(chatId)}`,
        method: HttpMethodEnum.Delete,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["chatList"] });
    },
  });

  return {
    chats: Array.isArray(chatsListQuery.data) ? chatsListQuery.data : [],
    isLoadingChats: chatsListQuery.isLoading,
    activeChat: activeChatQuery.data || null,
    arrivedIds,
    isLoadingActiveChat: activeChatQuery.isLoading,
    activeChatError: activeChatQuery.error,
    myRules: myRulesQuery.data ?? [],
    setChatRule: setChatRuleMutation.mutateAsync,
    renameChat: renameChatMutation.mutateAsync,
    isSettingRule: setChatRuleMutation.isPending,
    createChat: createChatMutation.mutateAsync,
    isCreatingChat: createChatMutation.isPending,
    sendMessage: sendMessageMutation.mutateAsync,
    isSendingMessage: sendMessageMutation.isPending,
    addToCart: addToCartMutation.mutateAsync,
    isAddingToCart: addToCartMutation.isPending,
    setCartQty: setCartQtyMutation.mutateAsync,
    isSettingCartQty: setCartQtyMutation.isPending,
    checkout: checkoutMutation.mutateAsync,
    isCheckingOut: checkoutMutation.isPending,
    deleteChat: deleteChatMutation.mutateAsync,
    isDeletingChat: deleteChatMutation.isPending,
  };
}
