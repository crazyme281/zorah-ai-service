import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import { callAIBackend } from "../lib/aiBackend";
import type { Tables } from "../lib/database.types";

type Message = Tables<"messages">;

export function useMessages(conversationId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);

  const refresh = useCallback(async () => {
    if (!conversationId) {
      setMessages([]);
      return;
    }
    setLoading(true);
    const { data, error } = await supabase
      .from("messages")
      .select("*")
      .eq("conversation_id", conversationId)
      .order("created_at", { ascending: true });
    if (!error && data) setMessages(data);
    setLoading(false);
  }, [conversationId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function sendMessage(content: string) {
    if (!conversationId || !content.trim()) return;
    setSending(true);
    try {
      const { data: userMsg, error } = await supabase
        .from("messages")
        .insert({ conversation_id: conversationId, role: "user", content })
        .select()
        .single();
      if (error || !userMsg) throw error;
      setMessages((prev) => [...prev, userMsg]);

      // First user message in a fresh chat becomes its title, so the
      // sidebar doesn't just show "New Chat" forever.
      if (messages.length === 0) {
        const title = content.length > 48 ? `${content.slice(0, 48)}…` : content;
        await supabase.from("conversations").update({ title }).eq("id", conversationId);
      }

      const history = [...messages, userMsg].map((m) => ({ role: m.role, content: m.content }));
      const result = await callAIBackend(history, conversationId);

      const { data: aiMsg } = await supabase
        .from("messages")
        .insert({ conversation_id: conversationId, role: "assistant", content: result.reply })
        .select()
        .single();
      if (aiMsg) setMessages((prev) => [...prev, aiMsg]);
    } finally {
      setSending(false);
    }
  }

  return { messages, loading, sending, sendMessage, refresh };
}
